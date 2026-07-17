"""AgentSession — vendor-agnostic Agent 세션 Protocol.

DRC Actor 가 RT 1개 처리 시 ActorSession (Inner) 안에서 본 Protocol 의 구현체
(ClaudeAgentSession / GeminiAgentSession / OpenAIAgentSession — Outer) 를 호출.

각 vendor adapter 는 SDK 의 native 컨텍스트 객체 (ClaudeSDKClient / LlmAgent
+InMemoryRunner / Agent+Runner) 를 그대로 보유. wrapper 추상이 아니다.

vendor 식별 = engine.config personas 의 llm.sdk (create_session 이 ActorSession 에 주입).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentSession(Protocol):
    @property
    def vendor(self) -> str:
        """이 세션이 다루는 vendor 식별자 ('claude' | 'openai' | 'gemini')."""
        ...

    async def run_stage(self, stage: dict[str, Any], prompt: str) -> str:
        """stage 정의와 user prompt 를 받아 누적 컨텍스트에 추가, assistant 응답 반환."""
        ...

    async def export_items(self) -> list[Any]:
        """agent_state envelope 의 items (vendor 원형 — JSON-safe dict list, 컨텍스트 ②).

        호출자는 export → close 순서를 지킨다. close 와의 내부 순서(claude = close 후
        store read, gemini = delete 전 events dump)는 어댑터 책임.
        """
        ...

    async def close(self) -> None:
        """세션 정리 (연결 끊기, 메모리 해제 등)."""
        ...


async def run_stage_structured(
    session: AgentSession,
    stage: dict[str, Any],
    prompt: str,
    *,
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """SDK 의 native structured output 을 사용해 JSON 응답을 강제하는 helper.

    각 adapter (claude/gemini/openai) 가 자체 `run_stage_structured` 메서드를
    제공하면 그것을 호출. 없으면 기존 `run_stage` 호출 후 응답 text 에서 JSON 파싱 시도.

    반환:
        {"text": <원본 또는 직렬화된 문자열>,
         "structured": <dict | list | None>}
    """
    method = getattr(session, "run_stage_structured", None)
    if callable(method):
        return await method(stage, prompt, response_schema=response_schema)
    # Fallback — 기존 adapter 는 text 만 반환. JSON 파싱 best-effort.
    import json as _json

    text = await session.run_stage(stage, prompt)
    structured: dict[str, Any] | list[Any] | None = None
    try:
        parsed = _json.loads(text)
        # top-level array 도 정합 (예: update_roadmap step output_contract).
        if isinstance(parsed, dict | list):
            structured = parsed
    except (ValueError, TypeError):
        structured = None
    return {"text": text, "structured": structured}
