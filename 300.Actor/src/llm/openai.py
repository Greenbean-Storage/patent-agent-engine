"""OpenAIAgentSession — openai-agents 기반 멀티턴 세션.

Agent 인스턴스 1개를 보유, Runner.run에 누적된 input list를 매 stage 호출마다
넘겨 multi-turn을 유지. result.to_input_list()로 다음 호출용 input을 갱신.

stage 정의 → Agent 인자 매핑:
  - llm                  → model (예: 'o3', 'gpt-5')
  - system_prompt        → instructions
  - max_iterations       → max_turns (Runner.run 인자)
  - available_tools[]    → mcp_servers (MCPServerStreamableHttp)
  - reasoning_effort     → ModelSettings(reasoning=Reasoning(effort=...))
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agents import Agent, ModelSettings, Runner
from agents.mcp import MCPServerStreamableHttp
from agents.mcp.server import MCPServerStreamableHttpParams
from openai.types.shared import Reasoning

log = logging.getLogger(__name__)


def _build_mcp_servers(
    available_tools: list[dict[str, Any]] | None,
    mcp_urls: dict[str, str],
) -> list[MCPServerStreamableHttp]:
    if not available_tools:
        return []
    servers: list[MCPServerStreamableHttp] = []
    seen: set[str] = set()
    for tool in available_tools:
        label = tool.get("mcp")
        if not label or label in seen:
            continue
        url = mcp_urls.get(label)
        if not url:
            log.warning("openai_agent.mcp.no_url label=%s", label)
            continue
        params = MCPServerStreamableHttpParams(url=url)
        servers.append(MCPServerStreamableHttp(params=params, name=label, cache_tools_list=True))
        seen.add(label)
    return servers


def _build_model_settings(stage: dict[str, Any]) -> ModelSettings | None:
    effort = stage.get("reasoning_effort")
    if not effort:
        return None
    return ModelSettings(reasoning=Reasoning(effort=effort))


def _build_agent(stage: dict[str, Any], mcp_servers: list[MCPServerStreamableHttp]) -> Agent:
    kwargs: dict[str, Any] = {
        "name": stage.get("id", "agent"),
        "model": stage["llm"],
    }
    if stage.get("system_prompt"):
        kwargs["instructions"] = stage["system_prompt"]
    if mcp_servers:
        kwargs["mcp_servers"] = mcp_servers
    settings = _build_model_settings(stage)
    if settings is not None:
        kwargs["model_settings"] = settings
    return Agent(**kwargs)


class OpenAIAgentSession:
    vendor = "openai"

    def __init__(
        self,
        stage: dict[str, Any],
        mcp_urls: dict[str, str],
        function_tools: list[Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        prior_items: list[Any] | None = None,
    ) -> None:
        self._mcp_servers = _build_mcp_servers(stage.get("available_tools"), mcp_urls)
        self._mcp_connected = False
        self._agent = _build_agent(stage, self._mcp_servers)
        # prior_items = agent_state envelope 의 openai 원형 (to_input_list 산출물,
        # 호출자가 state.openai_seed_items 로 reasoning id 정규화 후 전달 — 컨텍스트 ②)
        self._cumulative: list[Any] = list(prior_items or [])
        self._input_list_failed = False
        self._model = stage.get("llm")
        # Phase E minimal: function_tools / response_schema 인자 수용. Native wiring
        # (openai-agents 의 tools 등록 + response_format json_schema) 은 별도 PR.
        self._function_tools = function_tools or []
        self._response_schema = response_schema
        log.info(
            "openai_agent.session.init model=%s function_tools=%d schema=%s",
            self._model,
            len(self._function_tools),
            response_schema is not None,
        )

    async def _ensure_mcp_connected(self) -> None:
        if self._mcp_connected:
            return
        for srv in self._mcp_servers:
            if hasattr(srv, "connect"):
                await srv.connect()
        self._mcp_connected = True

    async def run_stage(self, stage: dict[str, Any], prompt: str) -> str:
        await self._ensure_mcp_connected()
        t0 = time.monotonic()

        new_input: str | list[Any]
        if self._cumulative:
            new_input = self._cumulative + [{"role": "user", "content": prompt}]
        else:
            new_input = prompt

        max_turns = int(stage.get("max_iterations") or 10)
        result = await Runner.run(self._agent, new_input, max_turns=max_turns)

        # 누적 갱신 — 실패 시 export_items 가 fail-loud (stale prior 의 silent 저장 차단)
        try:
            self._cumulative = result.to_input_list()
        except Exception as exc:
            self._input_list_failed = True
            log.warning("openai_agent.session.input_list_error error=%s", exc)

        text = str(result.final_output) if result.final_output is not None else ""
        log.info(
            "openai_agent.session.stage stage=%s ms=%d chars=%d",
            stage.get("id", "?"),
            int((time.monotonic() - t0) * 1000),
            len(text),
        )
        return text

    async def run_stage_structured(
        self,
        stage: dict[str, Any],
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Phase E minimal: prompt 에 schema 텍스트 강제 후 text → JSON parse fallback.

        Native wiring (openai-agents 의 response_format json_schema) 은 별도 PR.
        """
        import json as _json

        if response_schema:
            schema_text = _json.dumps(response_schema, ensure_ascii=False, indent=2)
            augmented = (
                f"{prompt}\n\n"
                "## RESPONSE FORMAT (REQUIRED)\n"
                "Return ONLY a JSON object matching the following JSON Schema.\n\n"
                f"```json\n{schema_text}\n```"
            )
        else:
            augmented = f"{prompt}\n\n## RESPONSE FORMAT\nReturn ONLY a JSON object."
        text = await self.run_stage(stage, augmented)
        structured: dict[str, Any] | list[Any] | None = None
        try:
            parsed = _json.loads(text)
            # top-level array 도 정합 (예: update_roadmap step output_contract).
            if isinstance(parsed, dict | list):
                structured = parsed
        except (ValueError, TypeError):
            structured = None
        return {"text": text, "structured": structured}

    async def export_items(self) -> list[Any]:
        """agent_state envelope items (openai 원형 = to_input_list 누적). close 전후 무관."""
        if self._input_list_failed:
            raise RuntimeError(
                "openai to_input_list() 실패 — export 가 stale prior 가 됨 (silent 손실 차단)"
            )
        return list(self._cumulative)

    async def close(self) -> None:
        if not self._mcp_connected:
            return
        for srv in self._mcp_servers:
            try:
                if hasattr(srv, "cleanup"):
                    await srv.cleanup()
            except Exception as exc:
                log.warning("openai_agent.session.close.error error=%s", exc)
        self._mcp_connected = False
