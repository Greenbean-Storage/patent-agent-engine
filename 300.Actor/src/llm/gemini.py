"""GeminiAgentSession — google-adk 기반 멀티턴 세션.

LlmAgent 1개 + InMemoryRunner + ADK Session으로 누적 컨텍스트 유지.
같은 session_id로 run_async를 반복 호출하면 ADK가 자동으로 events에 누적.

stage 정의 → LlmAgent 인자 매핑:
  - llm                  → model (예: 'gemini-3.1-pro-preview')
  - system_prompt        → instruction
  - available_tools[]    → tools=[MCPToolset(StreamableHTTPConnectionParams(url=...))]

추가 (LlmAgent.tools 가 Callable 도 받으므로):
  - function_tools[]     → tools 에 in-process callable 등록 (FunctionTool wrap 불필요)
  - response_schema      → LlmAgent.output_schema 로 native 강제 (응답 JSON 강제)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.genai import types as genai_types

log = logging.getLogger(__name__)

_APP_NAME = "venezia"


def _build_mcp_tools(
    available_tools: list[dict[str, Any]] | None,
    mcp_urls: dict[str, str],
) -> list[MCPToolset]:
    if not available_tools:
        return []
    toolsets: list[MCPToolset] = []
    seen: set[str] = set()
    for tool in available_tools:
        label = tool.get("mcp")
        if not label or label in seen:
            continue
        url = mcp_urls.get(label)
        if not url:
            log.warning("gemini_agent.mcp.no_url label=%s", label)
            continue
        params = StreamableHTTPConnectionParams(url=url)
        toolsets.append(MCPToolset(connection_params=params))
        seen.add(label)
    return toolsets


def _build_agent(
    stage: dict[str, Any],
    tools: list[Any] | None = None,
    response_schema: dict[str, Any] | None = None,
) -> LlmAgent:
    """LlmAgent 생성. tools 는 MCPToolset 또는 Callable 혼합 가능.

    response_schema 가 주어지면 LlmAgent.output_schema 로 native 강제
    (Gemini ADK 가 응답을 schema 적합 JSON 으로 강제).
    """
    kwargs: dict[str, Any] = {
        "name": stage.get("id", "agent"),
        "model": stage["llm"],
    }
    if stage.get("system_prompt"):
        kwargs["instruction"] = stage["system_prompt"]
    if tools:
        kwargs["tools"] = list(tools)
    if response_schema:
        kwargs["output_schema"] = response_schema
    # engine.config 의 effort 1급 키 — gemini 번역 = ThinkingConfig.thinking_level
    # (low/medium/high → LOW/MEDIUM/HIGH, xhigh/max 는 HIGH 로 clamp)
    if stage.get("thinking_level"):
        from google.genai import types as genai_types

        level = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(
            str(stage["thinking_level"]).lower(), "HIGH"
        )
        kwargs["generate_content_config"] = genai_types.GenerateContentConfig(
            thinking_config=genai_types.ThinkingConfig(thinking_level=level)
        )
    return LlmAgent(**kwargs)


class GeminiAgentSession:
    vendor = "gemini"

    def __init__(
        self,
        stage: dict[str, Any],
        mcp_urls: dict[str, str],
        function_tools: list[Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        prior_items: list[Any] | None = None,
    ) -> None:
        mcp_tools = _build_mcp_tools(stage.get("available_tools"), mcp_urls)
        all_tools: list[Any] = list(mcp_tools) + list(function_tools or [])
        self._tools = all_tools
        self._agent = _build_agent(stage, all_tools, response_schema=response_schema)
        self._runner = InMemoryRunner(agent=self._agent, app_name=_APP_NAME)
        self._user_id = f"venezia-{uuid.uuid4().hex[:8]}"
        self._session_id: str | None = None
        # prior_items = agent_state envelope 의 gemini 원형 (Event.model_dump(mode='json')
        # dict list) — _ensure_session 이 새 ADK 세션에 append_event 로 복원 (컨텍스트 ②)
        self._prior_items: list[Any] = list(prior_items or [])
        self._model = stage.get("llm")
        self._has_schema = response_schema is not None
        log.info(
            "gemini_agent.session.init model=%s tools=%d schema=%s",
            self._model,
            len(all_tools),
            self._has_schema,
        )

    async def _ensure_session(self) -> None:
        if self._session_id is not None:
            return
        sess = await self._runner.session_service.create_session(
            app_name=_APP_NAME, user_id=self._user_id
        )
        self._session_id = sess.id
        if self._prior_items:
            from google.adk.events.event import Event

            for d in self._prior_items:
                await self._runner.session_service.append_event(sess, Event.model_validate(d))

    async def run_stage(
        self,
        stage: dict[str, Any],
        prompt: str | list[Any],
    ) -> str:
        """user message 호출.

        prompt 가 str 이면 단일 Part(text=...). list 이면 Content.parts 그대로
        (multimodal: text + inline_data Blob 의 혼합).
        """
        await self._ensure_session()
        # _ensure_session post-condition 타입 narrowing
        assert self._session_id is not None  # nosec B101
        t0 = time.monotonic()

        if isinstance(prompt, str):
            parts = [genai_types.Part(text=prompt)]
        else:
            parts = list(prompt)  # 이미 Part list
        msg = genai_types.Content(role="user", parts=parts)
        text_parts: list[str] = []
        async for event in self._runner.run_async(
            user_id=self._user_id,
            session_id=self._session_id,
            new_message=msg,
        ):
            content = getattr(event, "content", None)
            if content is None:
                continue
            parts = getattr(content, "parts", None) or []
            for p in parts:
                t = getattr(p, "text", None)
                if t:
                    text_parts.append(t)

        text = "\n".join(text_parts)
        log.info(
            "gemini_agent.session.stage stage=%s ms=%d chars=%d",
            stage.get("id", "?"),
            int((time.monotonic() - t0) * 1000),
            len(text),
        )
        return text

    async def run_stage_structured(
        self,
        stage: dict[str, Any],
        prompt: str | list[Any],
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """LlmAgent.output_schema 가 init 시 설정됐으면 응답이 native JSON 강제.

        response_schema 인자는 호환 위해 받지만 LlmAgent 는 이미 init 시 schema
        고정. 매 RT 마다 새 session 이 생성되므로 init 시 schema 전달이 본질.
        """
        text = await self.run_stage(stage, prompt)
        import json as _json

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
        """agent_state envelope items (gemini 원형 = ADK session events dump).

        close(delete_session) **전** 호출 필수 — 호출자(ActorSession._invoke)가
        성공 경로에서 export → close 순서를 지킨다. 미실행(세션 없음)이면 prior 그대로.
        """
        if self._session_id is None:
            return list(self._prior_items)
        sess = await self._runner.session_service.get_session(
            app_name=_APP_NAME, user_id=self._user_id, session_id=self._session_id
        )
        if sess is None:
            return list(self._prior_items)
        return [e.model_dump(mode="json", exclude_none=True) for e in sess.events]

    async def close(self) -> None:
        if self._session_id is None:
            return
        try:
            await self._runner.session_service.delete_session(
                app_name=_APP_NAME,
                user_id=self._user_id,
                session_id=self._session_id,
            )
        except Exception as exc:
            log.warning("gemini_agent.session.close.error error=%s", exc)
        finally:
            self._session_id = None
