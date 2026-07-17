"""Fetch tool 도메인 — LLM 이 RAG 처럼 CM 자원을 lazy fetch. (P-A v3)

본 모듈의 tool 들은 LlmAgent.tools 에 등록되어 LLM 의 native tool_use 로 호출됨.
각 tool 의 docstring 은 1-2줄 간단. 상세 사용 가이드는 system_prompt 의
[TOOL USAGE] section 에 통합.

IOM 은 prompt 의 [INVENTION] section 에 항상 inline → fetch_iom tool 없음.

dispatcher 가 매 RT 마다 user_id/work_id/persona/chain_id 를 closure 로 capture 한
새 tool 인스턴스를 만들어 LlmAgent.tools 에 등록. cross-persona 호출 금지 (self-chain only).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ...cm_client import CMClient


def make_fetch_tools(
    cm: CMClient,
    user_id: str,
    work_id: str,
    persona: int,
    chain_id: str,
    allowed_names: list[str] | None = None,
) -> list[Callable[..., Awaitable[Any]]]:
    """RT-scoped fetch tool list. user/invention/persona/chain 식별자를 closure 로 고정.

    P-A v3: persona 인자 추가 — chain 자료가 persona sub-folder 안.
    cross-persona fetch 금지 (self-chain only) — 자기 persona 의 dialog/RT 만 접근.
    D-3: `allowed_names` 가 주어지면 그 이름의 fetch tool 만 노출 (step 의 llm_tools 선언이
    실제 제어 — 선언 안 한 fetch_* 는 LLM 에 안 줌). None = 전체 (하위호환).
    """

    async def fetch_dialog(name: str) -> dict[str, Any]:
        """Fetch this persona's accumulated dialog. name 은 persona 의 allowlist 안
        (예: analysis, decisions, research, ...)."""
        result = await cm.get_persona_dialog(user_id, work_id, persona, name)
        return result or {}

    async def fetch_step_output(step_id: str) -> dict[str, Any]:
        """Fetch the output of a prior step in this chain. step_id matches pipeline JSON step.id."""
        result = await cm.get_step_output(user_id, work_id, persona, chain_id, step_id)
        return result or {}

    async def fetch_drawing(drawing_id: str, part: str) -> dict[str, Any]:
        """Fetch a drawing artifact. part ∈ numerals|dl|figure."""
        result = await cm.get_drawing_part(user_id, work_id, drawing_id, part)
        return result or {}

    async def list_drawings() -> dict[str, Any]:
        """List all drawings in this session (drawing_manifest)."""
        result = await cm.get_drawing_manifest(user_id, work_id)
        return result or {}

    async def fetch_outputs() -> dict[str, Any]:
        """List final outputs in this session (e.g., draft.docx). Returns outputs index,
        not binary body."""
        result = await cm.get_outputs_list(user_id, work_id)
        return result or {}

    async def fetch_conversation() -> dict[str, Any]:
        """Fetch session-wide user conversation (runtime/00.dro/conversation.json)."""
        result = await cm.get_conversation(user_id, work_id)
        return result or {}

    all_tools: list[Callable[..., Awaitable[Any]]] = [
        fetch_dialog,
        fetch_step_output,
        fetch_drawing,
        list_drawings,
        fetch_outputs,
        fetch_conversation,
    ]
    if allowed_names is None:
        return all_tools
    allowed = set(allowed_names)
    return [t for t in all_tools if t.__name__ in allowed]
