"""ClaudeAgentSession — claude-agent-sdk 기반 멀티턴 세션.

ClaudeSDKClient 한 인스턴스에 query를 누적해서 호출. 파이프라인의 모든 stage가
같은 client의 conversation을 공유. tool-use 루프와 MCP 호출은 SDK가 자체 처리.

stage 정의 → ClaudeAgentOptions 매핑:
  - llm                  → model
  - system_prompt        → system_prompt
  - max_iterations       → max_turns
  - available_tools[]    → mcp_servers (Streamable HTTP)

available_tools의 mcp 라벨은 PipelineExecutor의 mcp_clients dict (라벨→URL)에서 resolve.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import (
    AssistantMessage,
    McpHttpServerConfig,
    TextBlock,
)

log = logging.getLogger(__name__)


def _build_mcp_servers(
    available_tools: list[dict[str, Any]] | None,
    mcp_urls: dict[str, str],
) -> dict[str, Any]:
    if not available_tools:
        return {}
    servers: dict[str, Any] = {}
    seen: set[str] = set()
    for tool in available_tools:
        label = tool.get("mcp")
        if not label or label in seen:
            continue
        url = mcp_urls.get(label)
        if not url:
            log.warning("claude_agent.mcp.no_url label=%s", label)
            continue
        servers[label] = McpHttpServerConfig(type="http", url=url)
        seen.add(label)
    return servers


def _resolve_knowledge_prefix(keys: list[str] | None) -> str:
    """Resolve `inject_knowledge` keys → concatenated static prefix string.

    Each key maps to a text-returning function on `.knowledge`.
    Putting the prefix in `system_prompt` (instead of the per-stage user message)
    lets claude-agent-sdk apply prompt caching to the static block — turning a
    ~10K-token guide into a sunk cost amortized across many director rounds.
    """
    if not keys:
        return ""
    from .knowledge import (
        load_drafting_raw,
        load_drafting_summary,
        load_rejections_summary,
    )

    chunks: list[str] = []
    for key in keys:
        try:
            if key == "drafting_summary":
                chunks.append(load_drafting_summary())
            elif key.startswith("drafting_raw:"):
                part = key.split(":", 1)[1]
                chunks.append(load_drafting_raw(part))
            elif key == "rejections_summary":
                chunks.append(load_rejections_summary())
            else:
                log.warning("inject_knowledge.unknown_key key=%s", key)
        except Exception as exc:
            log.warning("inject_knowledge.failed key=%s error=%s", key, exc)
    if not chunks:
        return ""
    return "\n\n---\n\n".join(chunks)


def _compose_system_prompt(stage: dict[str, Any]) -> str:
    """Compose system_prompt = (knowledge prefix) + (stage prompt)."""
    base = stage.get("system_prompt") or ""
    prefix = _resolve_knowledge_prefix(stage.get("inject_knowledge"))
    if prefix:
        return f"{prefix}\n\n---\n\n## Stage Instructions\n\n{base}" if base else prefix
    return base


def _build_options(
    stage: dict[str, Any],
    mcp_urls: dict[str, str],
    session_store: Any = None,
    resume: str | None = None,
) -> ClaudeAgentOptions:
    kwargs: dict[str, Any] = {}
    if stage.get("llm"):
        kwargs["model"] = stage["llm"]
    composed = _compose_system_prompt(stage)
    if composed:
        kwargs["system_prompt"] = composed
    if stage.get("max_iterations"):
        kwargs["max_turns"] = int(stage["max_iterations"])
    # engine.config 의 effort 1급 키 (ClaudeAgentOptions.effort: low|medium|high|xhigh|max)
    # + llm_settings passthrough 의 thinking ({"type": "enabled", "budget_tokens": N} 등)
    if stage.get("effort"):
        kwargs["effort"] = stage["effort"]
    if stage.get("thinking"):
        kwargs["thinking"] = stage["thinking"]
    mcp_servers = _build_mcp_servers(stage.get("available_tools"), mcp_urls)
    if mcp_servers:
        kwargs["mcp_servers"] = mcp_servers
    # 컨텍스트 ② — transcript 미러(store 항상 장착, export 원천) + prior 있으면 resume
    if session_store is not None:
        kwargs["session_store"] = session_store
    if resume:
        kwargs["resume"] = resume
    return ClaudeAgentOptions(**kwargs)


class ClaudeAgentSession:
    vendor = "claude"

    def __init__(
        self,
        stage: dict[str, Any],
        mcp_urls: dict[str, str],
        function_tools: list[Any] | None = None,
        response_schema: dict[str, Any] | None = None,
        prior_items: list[Any] | None = None,
    ) -> None:
        # 컨텍스트 ② — prior_items = agent_state envelope 의 claude 원형 (session
        # transcript entries). store 를 pre-seed + resume=<entries 의 sessionId> 로
        # SDK 가 풀 원형 복원 (load→temp JSONL→subprocess resume). 신규 세션도 store
        # 장착 (턴 중 미러가 export_items 의 원천).
        from .state import ClaudeTranscriptStore, claude_session_id

        seed = list(prior_items or [])
        self._store = ClaudeTranscriptStore(entries=seed)
        resume = claude_session_id(seed) if seed else None
        options = _build_options(stage, mcp_urls, session_store=self._store, resume=resume)
        self._client = ClaudeSDKClient(options=options)
        self._connected = False
        self._model = options.model
        # Phase E minimal: function_tools / response_schema 인자 수용 (호환성).
        # Native wiring (Anthropic tool_use 기반 in-process callable + JSON strict)
        # 은 별도 PR. 현재는 fallback (run_stage_structured 가 prompt 강제 + parse).
        self._function_tools = function_tools or []
        self._response_schema = response_schema
        log.info(
            "claude_agent.session.init model=%s function_tools=%d schema=%s",
            self._model,
            len(self._function_tools),
            response_schema is not None,
        )

    async def _ensure_connected(self) -> None:
        if not self._connected:
            await self._client.connect()
            self._connected = True

    async def run_stage(self, stage: dict[str, Any], prompt: str) -> str:
        await self._ensure_connected()
        t0 = time.monotonic()
        await self._client.query(prompt)

        text_parts: list[str] = []
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
                    elif hasattr(block, "text"):
                        text_parts.append(block.text)

        text = "\n".join(text_parts)
        log.info(
            "claude_agent.session.stage stage=%s ms=%d chars=%d",
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

        Native wiring (Anthropic tool_use 기반 strict JSON 강제) 는 별도 PR.
        """
        import json as _json

        if response_schema:
            schema_text = _json.dumps(response_schema, ensure_ascii=False, indent=2)
            augmented = (
                f"{prompt}\n\n"
                "## RESPONSE FORMAT (REQUIRED)\n"
                "Return ONLY a JSON object matching the following JSON Schema. "
                "No prose, no markdown code fences.\n\n"
                f"```json\n{schema_text}\n```"
            )
        else:
            augmented = f"{prompt}\n\n## RESPONSE FORMAT\nReturn ONLY a JSON object."
        text = await self.run_stage(stage, augmented)
        structured: dict[str, Any] | list[Any] | None = None
        try:
            parsed = _json.loads(text)
            # update_roadmap 같이 top-level array 가 정합인 step 도 있음 (RFC 6901
            # array 와 별개). dict | list 모두 accept — 그 외 (string/number/null) 만 reject.
            if isinstance(parsed, dict | list):
                structured = parsed
        except (ValueError, TypeError):
            structured = None
        return {"text": text, "structured": structured}

    async def export_items(self) -> list[Any]:
        """agent_state envelope items (claude 원형 = transcript entries).

        내부에서 먼저 close (멱등) — teardown final flush 가 result 이후 늦은
        frame(summary 류)까지 store 로 밀어내고 나서 entries 를 읽는다.
        """
        await self.close()
        return self._store.export()

    async def close(self) -> None:
        if self._connected:
            try:
                await self._client.disconnect()
            except Exception as exc:
                log.warning("claude_agent.session.close.error error=%s", exc)
            finally:
                self._connected = False
