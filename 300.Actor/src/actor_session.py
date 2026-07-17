"""DRC Actor 전용 LLM 세션 wrapper.

ActorSession 이 vendor adapter (300.Actor/src/llm/{claude,gemini,openai}.py 의
*AgentSession) 를 호출. DRC 는 MCP 폐기 → mcp_urls={} 로 호출 + tool 은
tool registry 에서 가져온 in-process Python 함수로 교체.

Continuation (컨텍스트 ② — A3·D-2):
  - prior_state: dispatcher 가 CM agent_state 를 parse_agent_state 로 해석해 주입
    (vendor 원형 envelope {schema_version, vendor, model, items} | None).
  - vendor 일치 → items 를 adapter 에 native seed (claude=SessionStore+resume,
    gemini=Event append, openai=input items). 불일치 → items_to_plain 텍스트 강등.
  - 성공 _invoke 가 adapter.export_items() 로 이번 교환까지의 vendor 원형을 캡처,
    export_state() 가 다음 RT 용 envelope 반환. vendor 세션은 계속 RT-ephemeral.
  - 구 "## 이전 대화" system-prompt 텍스트 주입은 폐기 (vendor 교체 강등 시
    claude 한정 user-prompt preamble 로만 잔존).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# effort 1급 공통 키 → vendor stage 키 번역 (engine.config — claude/openai 는 SDK 동명 개념,
# gemini 는 ThinkingConfig.thinking_level 로 어댑터가 변환)
_EFFORT_STAGE_KEY = {"claude": "effort", "openai": "reasoning_effort", "gemini": "thinking_level"}


def _validate_against_response_schema(
    structured: dict[str, Any] | list[Any], schema: dict[str, Any]
) -> list[str]:
    """jsonschema Draft7 검증. 오류 메시지 list 반환 (빈 list = 통과).

    top-level array root 도 검증.
    """
    try:
        import jsonschema
    except ImportError:
        log.warning("jsonschema not installed — schema validation skipped")
        return []
    validator = jsonschema.Draft7Validator(schema)
    errs = [
        f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator.iter_errors(structured)
    ]
    return errs


def _augment_prompt_with_validation_errors(prompt: str, errors: list[str]) -> str:
    """schema validation 실패 errors 를 prompt 뒤에 추가해 재시도용 prompt 작성."""
    err_text = "\n".join(f"- {e}" for e in errors[:10])
    return (
        f"{prompt}\n\n"
        "## 직전 응답 검증 실패 — 다시 작성\n"
        f"{err_text}\n\n"
        "위 오류를 모두 수정한 JSON object 만 반환하세요. prose / 코드펜스 / 설명문 금지."
    )


@dataclass
class ActorSession:
    """DRC RT 1회 처리용 LLM 세션. SDK 인스턴스는 Lazy 생성.

    Fallback / retry 책임:
      - 작업 1 (model fallback): primary 모델 실패 시 같은 vendor 의 fallback 모델 1회 시도.
      - 작업 2 (SDK backoff): 각 모델 시도 안에서 retryable 에러 (5xx/429/network)
        만 exponential backoff 으로 max 3회 재시도. permanent 에러는 즉시 raise.
      - 작업 4 (schema retry): response_schema 가 있고 응답이 schema 와 안 맞으면
        prompt 에 errors 추가 후 1회만 재시도 (같은 모델). 여전히 실패면 PermanentLLMError raise.
    """

    persona: int
    sdk: str
    model: str
    # 컨텍스트 ② — 직전 RT 까지의 vendor 원형 envelope (parse_agent_state 결과, 없으면 None)
    prior_state: dict[str, Any] | None = None
    # 이하 engine.config 주입 (llm/__init__.create_session) — persona 별 코드 상수 폐기.
    # fallback_model: 같은 vendor 안에서의 1회 fallback (동일 값 = 같은 모델 retry).
    fallback_model: str | None = None
    # effort: 1급 공통 키 — sdk 별 stage 키로 번역 (claude→effort, openai→reasoning_effort,
    # gemini→thinking_level). llm_settings: vendor 전용 passthrough (adapter 가 아는 키만 read).
    effort: str | None = None
    llm_settings: dict[str, Any] = field(default_factory=dict)
    retry_cfg: dict[str, Any] = field(default_factory=dict)
    defaults_cfg: dict[str, Any] = field(default_factory=dict)
    # 성공 _invoke 가 캡처 — export_state() 의 원천 (init 아님)
    _last_items: list[Any] | None = field(default=None, init=False, repr=False)
    _used_model: str | None = field(default=None, init=False, repr=False)

    async def run(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        media_refs: list[str] | None = None,
        max_iterations: int | None = None,
        response_schema: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        function_tools: list[Any] | None = None,
    ) -> dict[str, Any]:
        """LLM 1회 호출. 실 SDK 직접 사용.

        강화 후:
        - context 통째 prompt inline 제거 — DRO 가 만든 prompt (step.instructions +
          [INVENTION] + [INPUTS] etc.) 그대로 전달.
        - response_schema 는 LlmAgent.output_schema 로 native 강제 (prompt 텍스트 append X).
        - function_tools 가 LlmAgent.tools 에 등록되어 LLM 의 native tool_use loop.
        - tools (legacy dict list) 는 system_prompt 안내용으로만 유지 (Phase D 후 제거 예정).
        - prior 컨텍스트는 system_prompt 텍스트가 아니라 _make_sdk_session 의 native seed
          (컨텍스트 ②) — vendor 교체 강등의 claude 한정 preamble 만 user prompt 앞에.
        """
        preamble = self._claude_downgrade_preamble()
        if preamble:
            prompt = f"{preamble}\n\n---\n\n{prompt}"

        step_proxy: dict[str, Any] = {
            "id": f"actor_{self.persona}",
            "llm": self.model,
            "system_prompt": system_prompt,
        }
        # vendor 전용 추가 옵션 passthrough — adapter 가 아는 키만 read (engine.config llm_settings)
        step_proxy.update(self.llm_settings)
        effort_key = _EFFORT_STAGE_KEY.get(self.sdk)
        if self.effort and effort_key:
            step_proxy[effort_key] = self.effort
        if max_iterations is None:
            max_iterations = self.defaults_cfg.get("max_iterations")
        if max_iterations:
            step_proxy["max_iterations"] = max_iterations

        t0 = time.monotonic()
        try:
            result = await self._call_sdk(
                step_proxy,
                prompt,
                response_schema,
                function_tools=function_tools,
            )
        except Exception:
            log.exception("actor_session.run.error sdk=%s persona=%s", self.sdk, self.persona)
            raise

        text = result.get("text", "")
        structured = result.get("structured")

        # 작업 4 — schema validation retry. response_schema 가 있고 structured 가 dict | list 면
        # jsonschema 검증 (top-level array root contract 도 검증). 실패 시 prompt 에 errors 추가 후
        # 같은 모델로 재시도 (횟수 = engine.config defaults.schema_retry, 현행 1).
        # 소진 후도 실패면 _PermanentLLMError raise (orchestrator 의 작업 3 정책에 위임).
        if response_schema and isinstance(structured, dict | list):
            errors = _validate_against_response_schema(structured, response_schema)
            retries_left = int(self.defaults_cfg.get("schema_retry", 1))
            while errors and retries_left > 0:
                from .llm.retry import _PermanentLLMError

                retries_left -= 1
                log.warning(
                    "schema validation failed (%d errors) — " "retry with error feedback. first=%s",
                    len(errors),
                    errors[0],
                )
                retry_prompt = _augment_prompt_with_validation_errors(
                    prompt,
                    errors,
                )
                try:
                    result2 = await self._call_sdk(
                        step_proxy,
                        retry_prompt,
                        response_schema,
                        function_tools=function_tools,
                    )
                except Exception:
                    log.exception("actor_session.run.schema_retry.error")
                    raise
                text = result2.get("text", text)
                structured2 = result2.get("structured")
                if not isinstance(structured2, dict | list):
                    raise _PermanentLLMError(
                        "schema validation retry returned non-dict structured output"
                    )
                structured = structured2
                errors = _validate_against_response_schema(structured, response_schema)
            if errors:
                from .llm.retry import _PermanentLLMError

                # 재시도 소진 후도 schema 위반 — orchestrator 정책에 위임
                raise _PermanentLLMError(f"schema validation failed after retry: {errors[:3]}")

        elapsed = int((time.monotonic() - t0) * 1000)
        log.info(
            "actor_session.run.done persona=%s sdk=%s ms=%d chars=%d structured=%s",
            self.persona,
            self.sdk,
            elapsed,
            len(text),
            structured is not None,
        )

        return {"text": text, "structured": structured}

    def _resolve_fallback_model(self) -> str | None:
        """fallback 모델 — engine.config llm.fallback_model 주입값 (없으면 fallback 없음)."""
        return self.fallback_model or None

    # ── 컨텍스트 ② — prior envelope → vendor seed ──────────────────────────────

    def _seed_items_for(self, model: str) -> list[Any] | None:
        """invoke model 용 native seed items. vendor 불일치 시 텍스트 강등 변환.

        claude 로의 강등만 native 주입 불가 (assistant turn 합성 불가) → None
        (run() 의 _claude_downgrade_preamble 경로가 담당).
        """
        st = self.prior_state
        if not st:
            return None
        from .llm.state import items_to_plain, openai_seed_items, plain_to_gemini_events

        if st["vendor"] == self.sdk:
            if self.sdk == "openai":
                return openai_seed_items(st["items"], st.get("model"), model)
            return list(st["items"])
        if self.sdk == "claude":
            return None
        plain = items_to_plain(st["vendor"], st["items"])
        if self.sdk == "gemini":
            return plain_to_gemini_events(plain, agent_author=f"actor_{self.persona}")
        return list(plain)  # openai — 평문 {role, content} 가 그대로 합법 input item

    def _claude_downgrade_preamble(self) -> str:
        """vendor 교체 강등에서 claude 가 타깃일 때만 — user prompt 앞 텍스트."""
        st = self.prior_state
        if not st or self.sdk != "claude" or st["vendor"] == "claude":
            return ""
        from .llm.state import items_to_plain, plain_to_preamble

        return plain_to_preamble(items_to_plain(st["vendor"], st["items"]))

    async def _call_sdk(
        self,
        step: dict[str, Any],
        prompt: Any,
        response_schema: dict[str, Any] | None,
        function_tools: list[Any] | None = None,
    ) -> dict[str, Any]:
        """작업 1 + 2 — primary 모델로 시도 (SDK backoff 적용).

        retryable 실패 시 fallback 모델 1회 시도.
        """
        from .llm.retry import _PermanentLLMError, _RetryableLLMError  # noqa: F401

        primary_model = self.model
        fallback_model = self._resolve_fallback_model()

        try:
            return await self._invoke(primary_model, step, prompt, response_schema, function_tools)
        except _RetryableLLMError as e:
            if not fallback_model or fallback_model == primary_model:
                log.warning(
                    "primary model %s failed (retryable) and no fallback available — raising",
                    primary_model,
                )
                raise
            log.warning(
                "primary model %s failed (%s) — trying fallback model %s",
                primary_model,
                e,
                fallback_model,
            )
            return await self._invoke(fallback_model, step, prompt, response_schema, function_tools)

    async def _invoke(
        self,
        model: str,
        step: dict[str, Any],
        prompt: Any,
        response_schema: dict[str, Any] | None,
        function_tools: list[Any] | None = None,
    ) -> dict[str, Any]:
        """단일 모델로 호출 + SDK backoff retry (작업 2)."""
        from .llm.retry import _classify_llm_error, with_backoff
        from .llm.session import run_stage_structured

        invoke_step = {**step, "llm": model}

        async def _do() -> dict[str, Any]:
            sess = self._make_sdk_session(invoke_step, response_schema, function_tools)
            try:
                try:
                    result = await run_stage_structured(
                        sess, invoke_step, prompt, response_schema=response_schema
                    )
                except Exception as raw_exc:
                    raise _classify_llm_error(raw_exc) from raw_exc
                # 컨텍스트 ② — 성공 교환의 vendor 원형 캡처 (export → close 순서.
                # 실패 attempt 는 캡처 없이 폐기 — schema retry/fallback 의 새 세션이
                # 같은 prior 로 seed 되므로 실패 교환은 자연 탈락).
                self._last_items = await sess.export_items()
                self._used_model = model
                return result
            finally:
                await sess.close()

        return await with_backoff(
            _do,
            max_attempts=int(self.retry_cfg.get("max_attempts", 3)),
            backoff_seconds=list(self.retry_cfg.get("backoff_seconds") or [2.0, 5.0, 10.0]),
            on_attempt=lambda att, exc: log.warning(
                "SDK backoff retry model=%s attempt=%d: %s", model, att, exc
            ),
        )

    def _make_sdk_session(
        self,
        step: dict[str, Any],
        response_schema: dict[str, Any] | None = None,
        function_tools: list[Any] | None = None,
    ):
        """vendor → adapter 인스턴스. prior seed (컨텍스트 ②) + native 옵션 전달."""
        prior_items = self._seed_items_for(step.get("llm") or self.model)
        if self.sdk == "claude":
            from .llm.claude import ClaudeAgentSession

            return ClaudeAgentSession(
                step,
                mcp_urls={},
                function_tools=function_tools,
                response_schema=response_schema,
                prior_items=prior_items,
            )
        if self.sdk == "gemini":
            from .llm.gemini import GeminiAgentSession

            return GeminiAgentSession(
                step,
                mcp_urls={},
                function_tools=function_tools,
                response_schema=response_schema,
                prior_items=prior_items,
            )
        if self.sdk == "openai":
            from .llm.openai import OpenAIAgentSession

            return OpenAIAgentSession(
                step,
                mcp_urls={},
                function_tools=function_tools,
                response_schema=response_schema,
                prior_items=prior_items,
            )
        raise ValueError(f"unknown sdk: {self.sdk}")

    def export_state(self) -> dict[str, Any]:
        """다음 RT 용 agent_state envelope (CM PUT body) — 컨텍스트 ②."""
        from .llm.state import build_agent_state

        if self._last_items is None:
            raise RuntimeError("export_state() before a successful run() — items 미캡처")
        return build_agent_state(self.sdk, self._used_model or self.model, self._last_items)
