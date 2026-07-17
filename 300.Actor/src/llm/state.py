"""agent_state envelope — vendor 원형 컨텍스트의 build/parse/변환 (A3·D-2).

envelope = {"schema_version": 1, "vendor": str, "model": str | None, "items": [...]}

items 의 vendor 원형:
  - claude  = session transcript entries (claude-agent-sdk SessionStore 가 미러하는
              JSONL line dict — pass-through blob, sessionId UUID 포함)
  - gemini  = ADK Event.model_dump(mode='json') dict
  - openai  = openai-agents result.to_input_list() item dict
  - fixture = 평문 {role, content} (FixtureSession — llm:fake)

원칙: 무변형 저장·복원 (D-2). vendor 교체 시에만 items_to_plain 으로 텍스트 강등.
본 모듈은 SDK import 0 — plain dict 처리만 (invoke 라인 게이트 대상).
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

SCHEMA_VERSION = 1

_VENDORS = {"claude", "gemini", "openai", "fixture"}


def build_agent_state(vendor: str, model: str | None, items: list[Any]) -> dict[str, Any]:
    """CM PUT body 가 되는 envelope 생성 (persona/updated_at 은 CM 이 스탬프)."""
    if vendor not in _VENDORS:
        raise RuntimeError(f"unknown agent_state vendor: {vendor!r} (allowed: {sorted(_VENDORS)})")
    return {
        "schema_version": SCHEMA_VERSION,
        "vendor": vendor,
        "model": model,
        "items": list(items),
    }


def parse_agent_state(state: dict[str, Any]) -> dict[str, Any] | None:
    """CM GET 응답 → prior envelope (없으면 None).

    - items 비어있음 (CM default 포함) = prior 없음 → None.
    - legacy 평문(messages 비어있지 않음) = fail-loud — 컨텍스트 ② 로 폐기된 포맷.
    """
    if not isinstance(state, dict):
        raise RuntimeError(f"agent_state 가 dict 가 아님: {type(state).__name__}")
    if "items" in state:
        items = state.get("items") or []
        if not items:
            return None
        vendor = state.get("vendor")
        if vendor not in _VENDORS:
            raise RuntimeError(
                f"agent_state envelope 의 vendor 불명: {vendor!r} (items {len(items)}건)"
            )
        return {
            "schema_version": state.get("schema_version", SCHEMA_VERSION),
            "vendor": vendor,
            "model": state.get("model"),
            "items": list(items),
        }
    if state.get("messages"):
        raise RuntimeError(
            "legacy agent_state(평문 messages) 발견 — vendor 원형 envelope(items) 로 "
            "전환됨 (컨텍스트 ②). 구 포맷은 fail-loud."
        )
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 텍스트 강등 (vendor 교체 시에만) — vendor 원형 → 평문 {role, content}
# ─────────────────────────────────────────────────────────────────────────────


def _text_of_blocks(content: Any) -> str:
    """str | block list → text 결합. text 키 있는 block 만 (thinking/tool_* 강등 제외)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [b.get("text") for b in content if isinstance(b, dict) and b.get("text")]
        return "\n".join(t for t in texts if isinstance(t, str))
    return ""


def _claude_to_plain(items: list[Any]) -> list[dict[str, str]]:
    plain: list[dict[str, str]] = []
    for e in items:
        if not isinstance(e, dict) or e.get("type") not in ("user", "assistant"):
            continue
        if e.get("isMeta") or e.get("isSidechain"):
            continue
        message = e.get("message") or {}
        text = _text_of_blocks(message.get("content"))
        if text:
            plain.append({"role": str(message.get("role") or e["type"]), "content": text})
    return plain


def _gemini_to_plain(items: list[Any]) -> list[dict[str, str]]:
    plain: list[dict[str, str]] = []
    for e in items:
        if not isinstance(e, dict):
            continue
        content = e.get("content") or {}
        parts = content.get("parts") or []
        texts = [p.get("text") for p in parts if isinstance(p, dict) and p.get("text")]
        text = "\n".join(t for t in texts if isinstance(t, str))
        if text:
            role = "user" if e.get("author") == "user" else "assistant"
            plain.append({"role": role, "content": text})
    return plain


def _openai_to_plain(items: list[Any]) -> list[dict[str, str]]:
    plain: list[dict[str, str]] = []
    for it in items:
        if not isinstance(it, dict) or "role" not in it:
            continue  # reasoning / function_call / function_call_output 류
        text = _text_of_blocks(it.get("content"))
        if text:
            plain.append({"role": str(it["role"]), "content": text})
    return plain


def _fixture_to_plain(items: list[Any]) -> list[dict[str, str]]:
    return [
        {"role": str(m.get("role", "?")), "content": str(m.get("content", ""))}
        for m in items
        if isinstance(m, dict) and m.get("content")
    ]


def items_to_plain(vendor: str, items: list[Any]) -> list[dict[str, str]]:
    """vendor 원형 items → 평문 {role, content} list (텍스트 강등 — D-2)."""
    extractor = {
        "claude": _claude_to_plain,
        "gemini": _gemini_to_plain,
        "openai": _openai_to_plain,
        "fixture": _fixture_to_plain,
    }.get(vendor)
    if extractor is None:
        raise RuntimeError(f"items_to_plain: unknown vendor {vendor!r}")
    return extractor(items)


# ─────────────────────────────────────────────────────────────────────────────
# claude — SessionStore (resume 용 in-memory transcript store)
# ─────────────────────────────────────────────────────────────────────────────


def claude_session_id(items: list[Any]) -> str:
    """transcript entries 의 sessionId 추출 + UUID 검증.

    UUID 형식이 아니면 SDK 의 materialize 가 silent skip 후 CLI resume 에 그대로
    전달돼 조용한 컨텍스트 손실이 가능 — fail-loud 로 차단.
    """
    for e in items:
        if isinstance(e, dict) and e.get("sessionId"):
            sid = str(e["sessionId"])
            try:
                _uuid.UUID(sid)
            except ValueError as exc:
                raise RuntimeError(
                    f"claude transcript sessionId 가 UUID 아님: {sid!r} — resume 불가"
                ) from exc
            return sid
    raise RuntimeError("claude transcript entries 에 sessionId 없음 — resume 불가")


class ClaudeTranscriptStore:
    """claude-agent-sdk SessionStore 의 구조적(duck-typed) 구현 — 단일 세션 전용.

    SDK 계약 (claude_agent_sdk.types.SessionStore):
      - append(key, entries): 턴 중 ~100ms 배치 미러. 부분 실패 retry 가 overlap
        재전송할 수 있어 uuid 있는 entry 는 upsert, 없는 entry 는 그대로 append.
      - load(key): resume 직전 1회 — main transcript entries (없으면 None).
    subpath(서브에이전트 transcript) 는 분리 보관 + export 제외 — Actor 는
    subagent 미사용 (수신 시 warning 은 adapter 측 로깅 없이 조용히 분리만).
    """

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        self._main: list[dict[str, Any]] = list(entries or [])
        self._sub: dict[str, list[dict[str, Any]]] = {}

    async def append(self, key: Any, entries: list[dict[str, Any]]) -> None:
        subpath = key.get("subpath") if isinstance(key, dict) else None
        bucket = self._sub.setdefault(subpath, []) if subpath else self._main
        for e in entries:
            u = e.get("uuid") if isinstance(e, dict) else None
            if u:
                for i, existing in enumerate(bucket):
                    if isinstance(existing, dict) and existing.get("uuid") == u:
                        bucket[i] = e
                        break
                else:
                    bucket.append(e)
            else:
                bucket.append(e)

    async def load(self, key: Any) -> list[dict[str, Any]] | None:
        subpath = key.get("subpath") if isinstance(key, dict) else None
        if subpath:
            return None  # subagent transcript 미보유 — SDK 가 스킵
        return list(self._main) or None

    def export(self) -> list[dict[str, Any]]:
        """main transcript 원형 (envelope items 로 들어갈 값)."""
        return list(self._main)


# ─────────────────────────────────────────────────────────────────────────────
# openai — seed 정규화 (저장은 무변형, 복원 시에만)
# ─────────────────────────────────────────────────────────────────────────────


def openai_seed_items(
    items: list[Any], stored_model: str | None, target_model: str | None
) -> list[Any]:
    """to_input_list() 원형 → Runner.run input 재주입용 정규화.

    - 같은 model: reasoning item 의 `id` 만 strip (이전 response 에 묶인 id 재전송 방지,
      내용 보존 — openai-agents 의 reasoning_item_id_policy 'omit' 동등).
    - model 불일치 (fallback 잔재): reasoning item 자체 drop — 타 모델 reasoning
      재주입은 API 400.
    """
    out: list[Any] = []
    for it in items:
        if isinstance(it, dict) and it.get("type") == "reasoning":
            if stored_model != target_model:
                continue
            it = {k: v for k, v in it.items() if k != "id"}
        out.append(it)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 강등 평문 → vendor 주입형
# ─────────────────────────────────────────────────────────────────────────────


def plain_to_gemini_events(plain: list[dict[str, str]], agent_author: str) -> list[dict[str, Any]]:
    """평문 turns → ADK Event.model_validate 가능한 최소 event dict (강등 주입용)."""
    events: list[dict[str, Any]] = []
    for m in plain:
        text = m.get("content") or ""
        if not text:
            continue
        if m.get("role") == "user":
            events.append(
                {"author": "user", "content": {"role": "user", "parts": [{"text": text}]}}
            )
        else:
            events.append(
                {"author": agent_author, "content": {"role": "model", "parts": [{"text": text}]}}
            )
    return events


def plain_to_preamble(plain: list[dict[str, str]]) -> str:
    """평문 turns → user prompt 앞 텍스트 preamble (claude 강등 주입용 — native
    assistant turn 주입이 불가한 유일 vendor)."""
    if not plain:
        return ""
    lines = ["## 이전 대화 (Continuation)"]
    for msg in plain:
        lines.append(f"\n### {msg.get('role', '?')}\n{msg.get('content', '')}")
    return "\n".join(lines)
