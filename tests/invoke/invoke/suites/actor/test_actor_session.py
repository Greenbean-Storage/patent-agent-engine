"""300.Actor actor_session — ActorSession + helper 전수 (invoke 단위).

대상: 300.Actor/src/actor_session.py (컨텍스트 ② — A3·D-2)
  - 순수 helper: _validate_against_response_schema / _augment_prompt_with_validation_errors
  - ActorSession.run: _call_sdk 를 async mock 으로 교체(canned {text,structured}).
    response_schema 검증 retry(1회 재시도 후 _PermanentLLMError), system_prompt 무주입
    (구 "## 이전 대화" 폐기), claude 강등 preamble, max_iterations.
  - _seed_items_for / _claude_downgrade_preamble (prior envelope → vendor seed).
  - _resolve_fallback_model / _call_sdk / _invoke(원형 캡처) / _make_sdk_session /
    export_state.

벤더 SDK(claude/gemini/openai) 직접 호출은 피하고 run_stage_structured 를 monkeypatch.
async 는 asyncio.run(...) (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import builtins
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src.actor_session import (  # noqa: E402
    ActorSession,
    _augment_prompt_with_validation_errors,
    _validate_against_response_schema,
)
from src.llm.retry import _PermanentLLMError, _RetryableLLMError  # noqa: E402


def _env(vendor: str, items: list, model: str = "m-prior") -> dict[str, Any]:
    """prior_state(envelope) 헬퍼."""
    return {"schema_version": 1, "vendor": vendor, "model": model, "items": items}


# ── _validate_against_response_schema ─────────────────────────────────────────

_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": False,
}


def test_validate_schema_pass():
    assert _validate_against_response_schema({"name": "ok"}, _SCHEMA) == []


def test_validate_schema_fail_returns_messages():
    errs = _validate_against_response_schema({}, _SCHEMA)
    assert errs and any("<root>" in e or "name" in e for e in errs)


def test_validate_schema_array_root():
    arr_schema = {"type": "array", "items": {"type": "integer"}}
    assert _validate_against_response_schema([1, 2, 3], arr_schema) == []
    errs = _validate_against_response_schema(["bad"], arr_schema)
    assert errs and "0:" in errs[0]


def test_validate_schema_import_error_skips(monkeypatch):
    """jsonschema 미설치 분기 — import 가 ImportError 면 빈 list (검증 skip)."""
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ImportError("no jsonschema")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    # 스키마 위반 데이터지만 import 실패라 검증 skip → 빈 list
    assert _validate_against_response_schema({}, _SCHEMA) == []


# ── _augment_prompt_with_validation_errors ────────────────────────────────────


def test_augment_prompt_with_validation_errors():
    out = _augment_prompt_with_validation_errors("PROMPT", ["e1", "e2"])
    assert out.startswith("PROMPT")
    assert "직전 응답 검증 실패" in out
    assert "- e1" in out and "- e2" in out


def test_augment_prompt_truncates_to_ten_errors():
    errs = [f"e{i}" for i in range(20)]
    out = _augment_prompt_with_validation_errors("P", errs)
    assert "- e9" in out
    assert "- e10" not in out


# ── ActorSession.run — _call_sdk mock ─────────────────────────────────────────


def _session(persona=2, sdk="claude", model="claude-opus-4-7", prior_state=None, fallback=None):
    return ActorSession(
        persona=persona,
        sdk=sdk,
        model=model,
        prior_state=prior_state,
        fallback_model=fallback,
    )


def _patch_call_sdk(sess: ActorSession, results: list[dict[str, Any]]):
    """_call_sdk 를 순차 canned 결과로 교체. 호출 인자 capture."""
    calls: list[dict[str, Any]] = []
    seq = iter(results)

    async def _fake(step, prompt, response_schema, function_tools=None):
        calls.append(
            {
                "step": step,
                "prompt": prompt,
                "response_schema": response_schema,
                "function_tools": function_tools,
            }
        )
        return next(seq)

    sess._call_sdk = _fake  # type: ignore[method-assign]
    return calls


def test_run_basic_no_schema():
    sess = _session()
    calls = _patch_call_sdk(sess, [{"text": "answer", "structured": {"a": 1}}])
    out = asyncio.run(sess.run("PROMPT", system_prompt="SYS"))
    assert out == {"text": "answer", "structured": {"a": 1}}
    # step_proxy 기본 필드 — system_prompt 는 base 그대로 (구 "## 이전 대화" 주입 폐기)
    assert calls[0]["step"]["id"] == "actor_2"
    assert calls[0]["step"]["llm"] == "claude-opus-4-7"
    assert calls[0]["step"]["system_prompt"] == "SYS"
    assert calls[0]["prompt"] == "PROMPT"
    assert "max_iterations" not in calls[0]["step"]


def test_run_no_system_prompt_injection_even_with_prior():
    """prior 가 있어도 system_prompt 무주입 — 컨텍스트는 native seed (컨텍스트 ②)."""
    sess = _session(
        sdk="gemini",
        model="g",
        prior_state=_env("gemini", [{"author": "user", "content": {"role": "user", "parts": []}}]),
    )
    calls = _patch_call_sdk(sess, [{"text": "t", "structured": None}])
    asyncio.run(sess.run("P", system_prompt="STAGE"))
    assert calls[0]["step"]["system_prompt"] == "STAGE"
    assert calls[0]["prompt"] == "P"


def test_run_claude_downgrade_preamble_prefixes_prompt():
    """vendor 교체 강등에서 claude 타깃만 user prompt 앞 preamble (native 주입 불가)."""
    sess = _session(
        sdk="claude",
        prior_state=_env("fixture", [{"role": "user", "content": "earlier"}]),
    )
    calls = _patch_call_sdk(sess, [{"text": "t", "structured": None}])
    asyncio.run(sess.run("REAL-PROMPT", system_prompt="STAGE"))
    assert calls[0]["step"]["system_prompt"] == "STAGE"  # system 은 여전히 무주입
    p = calls[0]["prompt"]
    assert p.startswith("## 이전 대화 (Continuation)")
    assert "earlier" in p and p.endswith("REAL-PROMPT")


def test_run_claude_downgrade_preamble_carries_into_schema_retry():
    sess = _session(
        sdk="claude",
        prior_state=_env("fixture", [{"role": "user", "content": "earlier"}]),
    )
    calls = _patch_call_sdk(
        sess,
        [
            {"text": "bad", "structured": {}},  # name 누락 → 검증 실패
            {"text": "good", "structured": {"name": "fixed"}},
        ],
    )
    asyncio.run(sess.run("P", response_schema=_SCHEMA))
    assert calls[1]["prompt"].startswith("## 이전 대화 (Continuation)")
    assert "직전 응답 검증 실패" in calls[1]["prompt"]


def test_run_max_iterations_set_on_step():
    sess = _session()
    calls = _patch_call_sdk(sess, [{"text": "t", "structured": None}])
    asyncio.run(sess.run("P", max_iterations=7))
    assert calls[0]["step"]["max_iterations"] == 7


def test_run_step_proxy_engine_config_injection():
    """effort(1급 키 — sdk 별 번역) + llm_settings passthrough + defaults.max_iterations."""
    sess = _session(persona=2, sdk="claude", model="claude-opus-4-7")
    sess.effort = "high"
    sess.llm_settings = {"thinking": {"type": "enabled", "budget_tokens": 1000}}
    sess.defaults_cfg = {"max_iterations": 9}
    calls = _patch_call_sdk(sess, [{"text": "t", "structured": None}])
    asyncio.run(sess.run("P"))
    step = calls[0]["step"]
    assert step["effort"] == "high"  # claude → effort
    assert step["thinking"] == {"type": "enabled", "budget_tokens": 1000}
    assert step["max_iterations"] == 9  # 인자 미지정 → defaults.max_iterations


def test_run_effort_translated_per_sdk():
    """openai→reasoning_effort, gemini→thinking_level 번역 키."""
    for sdk, key in (("openai", "reasoning_effort"), ("gemini", "thinking_level")):
        sess = _session(persona=4, sdk=sdk, model="m")
        sess.effort = "medium"
        calls = _patch_call_sdk(sess, [{"text": "t", "structured": None}])
        asyncio.run(sess.run("P"))
        assert calls[0]["step"][key] == "medium"


def test_run_passes_function_tools_and_response_schema():
    sess = _session()
    tools = [object()]
    calls = _patch_call_sdk(sess, [{"text": "t", "structured": {"name": "ok"}}])
    asyncio.run(sess.run("P", response_schema=_SCHEMA, function_tools=tools))
    assert calls[0]["function_tools"] is tools
    assert calls[0]["response_schema"] == _SCHEMA


def test_run_schema_valid_no_retry():
    sess = _session()
    calls = _patch_call_sdk(sess, [{"text": "t", "structured": {"name": "ok"}}])
    out = asyncio.run(sess.run("P", response_schema=_SCHEMA))
    assert out["structured"] == {"name": "ok"}
    assert len(calls) == 1  # 검증 통과 → 재시도 없음


def test_run_schema_invalid_then_retry_success():
    sess = _session()
    calls = _patch_call_sdk(
        sess,
        [
            {"text": "bad", "structured": {}},  # name 누락 → 검증 실패
            {"text": "good", "structured": {"name": "fixed"}},  # 재시도 통과
        ],
    )
    out = asyncio.run(sess.run("P", response_schema=_SCHEMA))
    assert out == {"text": "good", "structured": {"name": "fixed"}}
    assert len(calls) == 2
    # 재시도 prompt 에 검증 실패 안내가 들어감
    assert "직전 응답 검증 실패" in calls[1]["prompt"]


def test_run_schema_invalid_twice_raises_permanent():
    sess = _session()
    _patch_call_sdk(
        sess,
        [
            {"text": "bad1", "structured": {}},
            {"text": "bad2", "structured": {}},
        ],
    )
    with pytest.raises(_PermanentLLMError, match="schema validation failed after retry"):
        asyncio.run(sess.run("P", response_schema=_SCHEMA))


def test_run_schema_retry_non_dict_structured_raises_permanent():
    sess = _session()
    _patch_call_sdk(
        sess,
        [
            {"text": "bad", "structured": {}},  # 검증 실패 → 재시도
            {"text": "x", "structured": "not-a-dict"},  # 재시도 structured 가 dict/list 아님
        ],
    )
    with pytest.raises(_PermanentLLMError, match="non-dict structured output"):
        asyncio.run(sess.run("P", response_schema=_SCHEMA))


def test_run_schema_skipped_when_structured_not_dict():
    """structured 가 dict|list 아니면 schema 검증 분기 자체를 안 탐."""
    sess = _session()
    calls = _patch_call_sdk(sess, [{"text": "t", "structured": None}])
    out = asyncio.run(sess.run("P", response_schema=_SCHEMA))
    assert out["structured"] is None
    assert len(calls) == 1


def test_run_call_sdk_exception_reraises():
    sess = _session()

    async def _boom(step, prompt, response_schema, function_tools=None):
        raise RuntimeError("sdk down")

    sess._call_sdk = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="sdk down"):
        asyncio.run(sess.run("P"))


def test_run_schema_retry_call_sdk_exception_reraises():
    sess = _session()
    seq = iter([{"text": "bad", "structured": {}}])

    async def _fake(step, prompt, response_schema, function_tools=None):
        try:
            return next(seq)
        except StopIteration:
            raise RuntimeError("retry sdk down") from None

    sess._call_sdk = _fake  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="retry sdk down"):
        asyncio.run(sess.run("P", response_schema=_SCHEMA))


# ── _resolve_fallback_model ───────────────────────────────────────────────────


def test_resolve_fallback_instance_override():
    sess = _session(fallback="custom-fb")
    assert sess._resolve_fallback_model() == "custom-fb"


def test_resolve_fallback_injected_from_engine_config():
    """fallback = engine.config llm.fallback_model 주입값 (persona 코드 상수 폐기)."""
    sess = _session(
        persona=1,
        sdk="gemini",
        model="gemini-3.1-pro-preview",
        fallback="gemini-3-flash-preview",
    )
    assert sess._resolve_fallback_model() == "gemini-3-flash-preview"


def test_resolve_fallback_no_entry_returns_none():
    sess = _session(persona=99, sdk="claude", model="m")
    assert sess._resolve_fallback_model() is None


# ── _call_sdk (작업 1: fallback) ──────────────────────────────────────────────


def _patch_invoke(sess: ActorSession, behavior):
    """_invoke 를 behavior(model)->awaitable 로 교체. 호출 model 순서 capture."""
    seen: list[str] = []

    async def _fake(model, step, prompt, response_schema, function_tools=None):
        seen.append(model)
        return await behavior(model)

    sess._invoke = _fake  # type: ignore[method-assign]
    return seen


def test_call_sdk_primary_success():
    sess = _session()

    async def _ok(model):
        return {"text": "primary", "structured": None}

    seen = _patch_invoke(sess, _ok)
    out = asyncio.run(sess._call_sdk({"id": "x"}, "P", None))
    assert out["text"] == "primary"
    assert seen == ["claude-opus-4-7"]


def test_call_sdk_retryable_falls_back_to_fallback_model():
    sess = _session(
        persona=1,
        sdk="gemini",
        model="gemini-3.1-pro-preview",
        fallback="gemini-3-flash-preview",
    )

    async def _behavior(model):
        if model == "gemini-3.1-pro-preview":
            raise _RetryableLLMError("primary transient")
        return {"text": "fallback-ok", "structured": None}

    seen = _patch_invoke(sess, _behavior)
    out = asyncio.run(sess._call_sdk({"id": "x"}, "P", None))
    assert out["text"] == "fallback-ok"
    assert seen == ["gemini-3.1-pro-preview", "gemini-3-flash-preview"]


def test_call_sdk_retryable_no_distinct_fallback_raises():
    """fallback 모델이 primary 와 같으면(claude) 재시도 없이 raise."""
    sess = _session(persona=2, sdk="claude", model="claude-opus-4-7")

    async def _behavior(model):
        raise _RetryableLLMError("primary transient")

    seen = _patch_invoke(sess, _behavior)
    with pytest.raises(_RetryableLLMError, match="primary transient"):
        asyncio.run(sess._call_sdk({"id": "x"}, "P", None))
    assert seen == ["claude-opus-4-7"]


def test_call_sdk_retryable_no_fallback_entry_raises():
    """persona 가 fallback 매핑에 없으면(None) raise."""
    sess = _session(persona=99, sdk="claude", model="m")

    async def _behavior(model):
        raise _RetryableLLMError("transient")

    seen = _patch_invoke(sess, _behavior)
    with pytest.raises(_RetryableLLMError, match="transient"):
        asyncio.run(sess._call_sdk({"id": "x"}, "P", None))
    assert seen == ["m"]


# ── _invoke (작업 2: SDK backoff) — run_stage_structured monkeypatch ───────────


class _FakeSDKSession:
    def __init__(self, items: list | None = None) -> None:
        self.closed = False
        self.order: list[str] = []
        self._items = items if items is not None else [{"k": 1}]

    async def export_items(self):
        self.order.append("export")
        return list(self._items)

    async def close(self):
        self.order.append("close")
        self.closed = True


def _patch_make_session(sess: ActorSession):
    """_make_sdk_session 을 fake (export_items/close) 로 교체."""
    fake = _FakeSDKSession()

    def _make(step, response_schema=None, function_tools=None):
        return fake

    sess._make_sdk_session = _make  # type: ignore[method-assign]
    return fake


def test_invoke_success_captures_items_then_closes(monkeypatch):
    sess = _session()
    fake = _patch_make_session(sess)
    captured: dict[str, Any] = {}

    async def _fake_run_stage(session, step, prompt, response_schema=None):
        captured["step_llm"] = step["llm"]
        captured["prompt"] = prompt
        return {"text": "ok", "structured": {"x": 1}}

    monkeypatch.setattr("src.llm.session.run_stage_structured", _fake_run_stage)
    out = asyncio.run(sess._invoke("model-A", {"id": "x"}, "PROMPT", None))
    assert out == {"text": "ok", "structured": {"x": 1}}
    assert captured["step_llm"] == "model-A"  # invoke_step llm 덮어쓰기
    assert fake.closed is True
    # 컨텍스트 ② — 성공 교환의 원형 캡처 (export → close 순서) + 실사용 모델 기록
    assert fake.order == ["export", "close"]
    assert sess._last_items == [{"k": 1}]
    assert sess._used_model == "model-A"


def test_invoke_failure_skips_capture(monkeypatch):
    """실패 attempt 는 캡처 없음 — 실패 교환은 자연 탈락."""
    sess = _session()
    fake = _patch_make_session(sess)

    async def _bad(session, step, prompt, response_schema=None):
        import httpx

        raise httpx.HTTPStatusError(
            "unauthorized",
            request=httpx.Request("POST", "http://x"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr("src.llm.session.run_stage_structured", _bad)
    with pytest.raises(_PermanentLLMError):
        asyncio.run(sess._invoke("model-A", {"id": "x"}, "P", None))
    assert sess._last_items is None
    assert fake.order == ["close"]  # export 없이 close 만


def test_invoke_retryable_then_backoff_retry_success(monkeypatch):
    sess = _session()
    _patch_make_session(sess)

    # backoff sleep 무력화 (실제 sleep 회피 — recursion 없이 즉시 반환)
    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr("src.llm.retry.asyncio.sleep", _no_sleep)

    attempts = {"n": 0}

    async def _flaky(session, step, prompt, response_schema=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            import httpx

            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("POST", "http://x"),
                response=httpx.Response(503),
            )
        return {"text": "recovered", "structured": None}

    monkeypatch.setattr("src.llm.session.run_stage_structured", _flaky)
    out = asyncio.run(sess._invoke("model-A", {"id": "x"}, "P", None))
    assert out["text"] == "recovered"
    assert attempts["n"] == 2


def test_invoke_permanent_error_no_retry(monkeypatch):
    sess = _session()
    _patch_make_session(sess)

    async def _bad(session, step, prompt, response_schema=None):
        import httpx

        raise httpx.HTTPStatusError(
            "unauthorized",
            request=httpx.Request("POST", "http://x"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr("src.llm.session.run_stage_structured", _bad)
    with pytest.raises(_PermanentLLMError):
        asyncio.run(sess._invoke("model-A", {"id": "x"}, "P", None))


# ── _make_sdk_session (vendor 분기) ───────────────────────────────────────────


def test_make_sdk_session_claude():
    sess = _session(persona=2, sdk="claude", model="claude-opus-4-7")
    inst = sess._make_sdk_session({"id": "x", "llm": "claude-opus-4-7"})
    from src.llm.claude import ClaudeAgentSession

    assert isinstance(inst, ClaudeAgentSession)


def test_make_sdk_session_gemini():
    sess = _session(persona=1, sdk="gemini", model="gemini-3.1-pro-preview")
    inst = sess._make_sdk_session({"id": "x", "llm": "gemini-3.1-pro-preview"})
    from src.llm.gemini import GeminiAgentSession

    assert isinstance(inst, GeminiAgentSession)


def test_make_sdk_session_openai():
    sess = _session(persona=4, sdk="openai", model="o3")
    inst = sess._make_sdk_session({"id": "x", "llm": "o3"})
    from src.llm.openai import OpenAIAgentSession

    assert isinstance(inst, OpenAIAgentSession)


def test_make_sdk_session_unknown_raises():
    sess = _session(sdk="nope")
    with pytest.raises(ValueError, match="unknown sdk: nope"):
        sess._make_sdk_session({"id": "x"})


# ── _seed_items_for / _claude_downgrade_preamble (컨텍스트 ②) ──────────────────


def test_seed_no_prior_returns_none():
    assert _session()._seed_items_for("claude-opus-4-7") is None


def test_seed_vendor_match_passes_items_verbatim():
    items = [{"author": "user", "content": {"role": "user", "parts": [{"text": "q"}]}}]
    sess = _session(sdk="gemini", model="g", prior_state=_env("gemini", items))
    seeded = sess._seed_items_for("g")
    assert seeded == items
    assert seeded is not items  # 복사본


def test_seed_openai_match_normalizes_reasoning():
    items = [{"role": "user", "content": "q"}, {"type": "reasoning", "id": "rs_1", "summary": []}]
    sess = _session(sdk="openai", model="o3", prior_state=_env("openai", items, model="o3"))
    # 같은 model → id 만 strip
    assert sess._seed_items_for("o3") == [
        {"role": "user", "content": "q"},
        {"type": "reasoning", "summary": []},
    ]
    # model 불일치 (fallback 잔재) → reasoning drop
    assert sess._seed_items_for("o4") == [{"role": "user", "content": "q"}]


def test_seed_mismatch_to_gemini_synthesizes_events():
    sess = _session(
        persona=1,
        sdk="gemini",
        model="g",
        prior_state=_env("fixture", [{"role": "assistant", "content": "prev"}]),
    )
    assert sess._seed_items_for("g") == [
        {"author": "actor_1", "content": {"role": "model", "parts": [{"text": "prev"}]}}
    ]


def test_seed_mismatch_to_openai_plain_passthrough():
    sess = _session(
        sdk="openai",
        model="o3",
        prior_state=_env("fixture", [{"role": "user", "content": "q"}]),
    )
    assert sess._seed_items_for("o3") == [{"role": "user", "content": "q"}]


def test_seed_mismatch_to_claude_returns_none_preamble_path():
    sess = _session(
        sdk="claude",
        prior_state=_env("fixture", [{"role": "user", "content": "q"}]),
    )
    assert sess._seed_items_for("claude-opus-4-7") is None
    assert "## 이전 대화 (Continuation)" in sess._claude_downgrade_preamble()


def test_claude_preamble_empty_when_vendor_match_or_not_claude():
    match = _session(sdk="claude", prior_state=_env("claude", [{"sessionId": "s"}]))
    assert match._claude_downgrade_preamble() == ""
    other = _session(
        sdk="gemini", model="g", prior_state=_env("fixture", [{"role": "user", "content": "q"}])
    )
    assert other._claude_downgrade_preamble() == ""
    assert _session()._claude_downgrade_preamble() == ""  # prior 없음


def test_make_sdk_session_passes_prior_items(monkeypatch):
    """_make_sdk_session 이 seed 를 adapter prior_items 로 전달."""
    captured: dict[str, Any] = {}

    class _Fake:
        def __init__(
            self, step, mcp_urls, function_tools=None, response_schema=None, prior_items=None
        ):
            captured["prior_items"] = prior_items

    monkeypatch.setattr("src.llm.gemini.GeminiAgentSession", _Fake)
    items = [{"author": "user", "content": {"role": "user", "parts": [{"text": "q"}]}}]
    sess = _session(persona=1, sdk="gemini", model="g", prior_state=_env("gemini", items))
    sess._make_sdk_session({"id": "x", "llm": "g"})
    assert captured["prior_items"] == items


# ── export_state (컨텍스트 ②) ─────────────────────────────────────────────────


def test_export_state_before_run_raises():
    with pytest.raises(RuntimeError, match="export_state"):
        _session().export_state()


def test_export_state_envelope_after_invoke(monkeypatch):
    sess = _session(sdk="gemini", model="g-primary")
    _patch_make_session(sess)

    async def _ok(session, step, prompt, response_schema=None):
        return {"text": "ok", "structured": None}

    monkeypatch.setattr("src.llm.session.run_stage_structured", _ok)
    asyncio.run(sess._invoke("g-fallback", {"id": "x"}, "P", None))
    env = sess.export_state()
    # 실사용 모델(fallback) 반영 + vendor 원형 items
    assert env == {
        "schema_version": 1,
        "vendor": "gemini",
        "model": "g-fallback",
        "items": [{"k": 1}],
    }
