"""100.Nexus event_mapper — DRO raw SSE → client WS 비즈니스 이벤트 매핑 (invoke 단위).

대상: 100.Nexus/src/event_mapper.py.  envelope v2 {type,timestamp,seq,data} (scope/subject_id 없음).

전수 분기:
  _channel_for_persona       : None → support / known persona / unknown → support
  _display_status_from_step  : step 없음 / display_status 없음 / {ko,en} / ko 만 / ko 비문자열
  _latest_assistant_text     : 비-list / assistant 없음 / str content / 비-str content / 최신 선택
  handle_raw_event
    rt_started                       → work.progress {display_status, channel}  (모든 RT 시작)
    chain_completed(persona=1)       → message.reply {text}  (CM conversation 최신 assistant turn)
    chain_completed(persona=2)       → model.maturity {…} + model.roadmap {count}  (CM fetch)
       · maturity None → model.maturity 미발생 · roadmap None → model.roadmap 미발생
    chain_completed(persona=None/기타) → 미발생 (CM fetch 만, emit 0)
    rt_error / error                 → work.failed {message, channel}  (사용자 안전 sanitize, broadcast)
    rt_enqueued/rt_progress/rt_result → 사용자 미노출 (내부 관측, emit 0)
    unknown type                     → no-op
    missing/non-string user_id|work_id → early return (skip)

monkeypatch: event_mapper.get_production_ws_registry → emit 기록 fake · get_cm_client → fake CM.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

import src.event_mapper as event_mapper  # noqa: E402
from src.event_mapper import (  # noqa: E402
    _FALLBACK_CHANNEL,
    _FALLBACK_STATUS_EN,
    _FALLBACK_STATUS_KO,
    _channel_for_persona,
    _display_status_from_step,
    _latest_assistant,
    handle_raw_event,
)


class _FakeRegistry:
    """emit_business 호출을 기록하는 fake production WS registry."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit_business(self, user_id: str, work_id: str, event_type: str, data: dict) -> None:
        self.calls.append(
            {
                "user_id": user_id,
                "work_id": work_id,
                "event_type": event_type,
                "data": data,
            }
        )


class _FakeCM:
    """get_conversation / get_concept_maturity_model / get_user_roadmap fake (반환 주입)."""

    def __init__(self, *, conversation=None, maturity=None, roadmap=None) -> None:
        self._conv = conversation
        self._mat = maturity
        self._road = roadmap
        self.conv_calls: list[tuple[str, str]] = []
        self.mat_calls: list[tuple[str, str]] = []
        self.road_calls: list[tuple[str, str]] = []

    async def get_conversation(self, user_id: str, work_id: str):
        self.conv_calls.append((user_id, work_id))
        return self._conv

    async def get_concept_maturity_model(self, user_id: str, work_id: str):
        self.mat_calls.append((user_id, work_id))
        return self._mat

    async def get_user_roadmap(self, user_id: str, work_id: str):
        self.road_calls.append((user_id, work_id))
        return self._road


def _run(monkeypatch, raw: dict[str, Any], cm: _FakeCM | None = None) -> list[dict[str, Any]]:
    """fake registry(+선택적 fake CM) 주입 후 handle_raw_event 1회 구동, 기록된 emit 반환."""
    reg = _FakeRegistry()
    monkeypatch.setattr(event_mapper, "get_production_ws_registry", lambda: reg)
    if cm is not None:
        monkeypatch.setattr(event_mapper, "get_cm_client", lambda: cm)
    asyncio.run(handle_raw_event(raw))
    return reg.calls


def _base(rtype: str, **extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {"type": rtype, "user_id": "u-1", "work_id": "i-1"}
    raw.update(extra)
    return raw


# ── _channel_for_persona (직접 호출) ─────────────────────────────────────────


def test_channel_for_persona_none_fallback():
    assert _channel_for_persona(None) == _FALLBACK_CHANNEL


def test_channel_for_persona_known():
    assert _channel_for_persona(1) == "support"
    assert _channel_for_persona(2) == "analysis"
    assert _channel_for_persona(6) == "review"


def test_channel_for_persona_unknown_fallback():
    assert _channel_for_persona(99) == _FALLBACK_CHANNEL


# ── _display_status_from_step (직접 호출) ────────────────────────────────────


def test_display_status_no_step_fallback():
    assert _display_status_from_step(None) == {"ko": _FALLBACK_STATUS_KO, "en": _FALLBACK_STATUS_EN}


def test_display_status_step_without_display_status_fallback():
    assert _display_status_from_step({"id": 0}) == {
        "ko": _FALLBACK_STATUS_KO,
        "en": _FALLBACK_STATUS_EN,
    }


def test_display_status_step_with_ko_and_en():
    out = _display_status_from_step({"display_status": {"ko": "검색 중", "en": "Searching"}})
    assert out == {"ko": "검색 중", "en": "Searching"}


def test_display_status_step_with_ko_only_en_fallback():
    out = _display_status_from_step({"display_status": {"ko": "검색 중"}})
    assert out == {"ko": "검색 중", "en": _FALLBACK_STATUS_EN}


def test_display_status_non_string_ko_fallback():
    out = _display_status_from_step({"display_status": {"ko": 123}})
    assert out == {"ko": _FALLBACK_STATUS_KO, "en": _FALLBACK_STATUS_EN}


# ── _latest_assistant (직접 호출) — (id=위치, text) 반환 ──────────────────────


def test_latest_assistant_non_dict_none():
    # CM 의 get_conversation 은 dict {"messages":[...]} 반환 — dict 아니면 (None, None).
    assert _latest_assistant(None) == (None, None)
    assert _latest_assistant("not a dict") == (None, None)
    assert _latest_assistant([{"role": "assistant", "content": "x"}]) == (None, None)


def test_latest_assistant_dict_without_messages_none():
    assert _latest_assistant({"total_user_turns": 0}) == (None, None)


def test_latest_assistant_no_assistant_turn():
    assert _latest_assistant({"messages": [{"role": "user", "content": "hi"}]}) == (None, None)


def test_latest_assistant_str_content():
    conv = {
        "messages": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "응답입니다"},
        ]
    }
    assert _latest_assistant(conv) == (1, "응답입니다")  # id = 0-based 위치


def test_latest_assistant_non_str_content_none_text():
    # content 가 str 아니면 text=None, id 는 그 위치.
    assert _latest_assistant({"messages": [{"role": "assistant", "content": {"x": 1}}]}) == (0, None)


def test_latest_assistant_returns_latest():
    conv = {
        "messages": [
            {"role": "assistant", "content": "첫 응답"},
            {"role": "user", "content": "추가 질문"},
            {"role": "assistant", "content": "최신 응답"},
        ]
    }
    assert _latest_assistant(conv) == (2, "최신 응답")  # 최신 assistant 위치


# ── handle_raw_event: rt_started → progress ──────────────────────────────────


def test_rt_started_progress_with_step_and_persona(monkeypatch):
    raw = _base(
        "rt_started",
        persona=3,
        step={"display_status": {"ko": "조사 중", "en": "Researching"}},
    )
    calls = _run(monkeypatch, raw)
    assert len(calls) == 1
    c = calls[0]
    assert c["user_id"] == "u-1"
    assert c["work_id"] == "i-1"
    assert c["event_type"] == "work.progress"
    assert c["data"] == {
        "display_status": {"ko": "조사 중", "en": "Researching"},
        "channel": "research",
    }


def test_rt_started_progress_no_step_no_persona_fallback(monkeypatch):
    calls = _run(monkeypatch, _base("rt_started"))
    assert calls[0]["data"] == {
        "display_status": {"ko": _FALLBACK_STATUS_KO, "en": _FALLBACK_STATUS_EN},
        "channel": _FALLBACK_CHANNEL,
    }


def test_rt_started_channel_per_persona(monkeypatch):
    assert _run(monkeypatch, _base("rt_started", persona=5))[0]["data"]["channel"] == "drafting"


def test_rt_started_unknown_persona_fallback_channel(monkeypatch):
    assert (
        _run(monkeypatch, _base("rt_started", persona=99))[0]["data"]["channel"]
        == _FALLBACK_CHANNEL
    )


def test_rt_started_non_int_persona_fallback(monkeypatch):
    # persona int 아니면 None → support.
    assert (
        _run(monkeypatch, _base("rt_started", persona="2"))[0]["data"]["channel"]
        == _FALLBACK_CHANNEL
    )


def test_rt_started_non_dict_step_fallback(monkeypatch):
    calls = _run(monkeypatch, _base("rt_started", step=["not", "a", "dict"]))
    assert calls[0]["data"]["display_status"] == {
        "ko": _FALLBACK_STATUS_KO,
        "en": _FALLBACK_STATUS_EN,
    }


# ── handle_raw_event: chain_completed(persona=1) → reply ──────────────────────


def test_chain_completed_persona1_reply_text(monkeypatch):
    cm = _FakeCM(conversation={"messages": [{"role": "assistant", "content": "답장 텍스트"}]})
    calls = _run(monkeypatch, _base("chain_completed", persona=1), cm=cm)
    assert len(calls) == 1
    assert calls[0]["event_type"] == "message.reply"
    assert calls[0]["data"] == {"id": 0, "text": "답장 텍스트"}  # id = assistant turn 위치
    assert cm.conv_calls == [("u-1", "i-1")]


def test_chain_completed_persona1_reply_empty_conversation_null_text(monkeypatch):
    # CM 빈값(예: dro:fake) → id/text None.
    cm = _FakeCM(conversation=None)
    calls = _run(monkeypatch, _base("chain_completed", persona=1), cm=cm)
    assert calls[0]["event_type"] == "message.reply"
    assert calls[0]["data"] == {"id": None, "text": None}


# ── handle_raw_event: chain_completed(persona=2) → model.maturity + model.roadmap ─


def test_chain_completed_persona2_both_models(monkeypatch):
    cm = _FakeCM(
        maturity={
            "overall_score": 0.72,
            "scores": {
                "clarity": 0.8,
                "completeness": 0.7,
                "potential": 0.6,
            },
            "weights": {
                "clarity": 0.30,
                "completeness": 0.45,
                "potential": 0.25,
            },
        },
        roadmap=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
    )
    calls = _run(monkeypatch, _base("chain_completed", persona=2), cm=cm)
    by_type = {c["event_type"]: c for c in calls}
    assert by_type["model.maturity"]["data"] == {
        "overall_score": 0.72,
        "scores": {
            "clarity": 0.8,
            "completeness": 0.7,
            "potential": 0.6,
        },
        "weights": {
            "clarity": 0.30,
            "completeness": 0.45,
            "potential": 0.25,
        },
    }
    assert by_type["model.roadmap"]["data"] == {"count": 3}


def test_chain_completed_persona2_maturity_empty_defaults(monkeypatch):
    # overall_score None → 0.0, scores/weights None → {}; roadmap [] → count 0.
    cm = _FakeCM(maturity={}, roadmap=[])
    calls = _run(monkeypatch, _base("chain_completed", persona=2), cm=cm)
    by_type = {c["event_type"]: c for c in calls}
    assert by_type["model.maturity"]["data"] == {"overall_score": 0.0, "scores": {}, "weights": {}}
    assert by_type["model.roadmap"]["data"] == {"count": 0}


def test_chain_completed_persona2_maturity_none_skips_maturity(monkeypatch):
    # maturity 비-dict(None) → model.maturity 미발생, roadmap 만.
    cm = _FakeCM(maturity=None, roadmap=[{"id": "x"}])
    calls = _run(monkeypatch, _base("chain_completed", persona=2), cm=cm)
    types = [c["event_type"] for c in calls]
    assert "model.maturity" not in types
    assert types == ["model.roadmap"]
    assert calls[0]["data"] == {"count": 1}


def test_chain_completed_persona2_roadmap_none_skips_roadmap(monkeypatch):
    # roadmap 비-list(None) → model.roadmap 미발생, maturity 만.
    cm = _FakeCM(maturity={"overall_score": 0.5}, roadmap=None)
    calls = _run(monkeypatch, _base("chain_completed", persona=2), cm=cm)
    types = [c["event_type"] for c in calls]
    assert types == ["model.maturity"]
    assert "model.roadmap" not in types


def test_chain_completed_persona2_both_none_no_emit(monkeypatch):
    # dro:fake CM 빈값 — maturity/roadmap 둘 다 None → emit 0 (skip 규약 근거).
    cm = _FakeCM(maturity=None, roadmap=None)
    calls = _run(monkeypatch, _base("chain_completed", persona=2), cm=cm)
    assert calls == []
    assert cm.mat_calls == [("u-1", "i-1")]
    assert cm.road_calls == [("u-1", "i-1")]


def test_chain_completed_persona_none_no_emit(monkeypatch):
    # persona 식별 안 됨 → reply/model 분기 모두 비해당 → emit 0 (CM fetch 도 없음).
    cm = _FakeCM(conversation=[{"role": "assistant", "content": "x"}])
    calls = _run(monkeypatch, _base("chain_completed"), cm=cm)
    assert calls == []
    assert cm.conv_calls == []


# ── handle_raw_event: 내부 관측 RAW (rt_enqueued/progress/result) → emit 0 ─


def test_internal_raw_events_no_emit(monkeypatch):
    # rt_error/error 는 이제 work.failed 로 노출 → 여기선 진짜 내부 관측만.
    for rtype in ("rt_enqueued", "rt_progress", "rt_result"):
        calls = _run(monkeypatch, _base(rtype, persona=1, payload={"text": "x"}))
        assert calls == [], f"{rtype} 는 사용자 미노출이어야 (emit 0)"


# ── handle_raw_event: rt_error / error → work.failed (사용자 안전 sanitize, broadcast) ─


def test_rt_error_maps_to_work_failed(monkeypatch):
    calls = _run(monkeypatch, _base("rt_error", persona=3, payload={"message": "boom internal"}))
    assert len(calls) == 1
    c = calls[0]
    assert c["event_type"] == "work.failed"
    assert c["data"]["channel"] == "research"
    assert isinstance(c["data"]["message"], str) and c["data"]["message"]
    # 내부 message 는 비노출(sanitize) — 사용자 안전 문구만.
    assert "boom internal" not in c["data"]["message"]


def test_error_maps_to_work_failed_persona_fallback(monkeypatch):
    # chain error → work.failed. persona 없으면 channel fallback.
    calls = _run(monkeypatch, _base("error", payload={"chain_id": "c1", "message": "x"}))
    assert len(calls) == 1
    c = calls[0]
    assert c["event_type"] == "work.failed"
    assert c["data"]["channel"] == _FALLBACK_CHANNEL


# ── handle_raw_event: unknown type → no-op ───────────────────────────────────


def test_unknown_type_noop(monkeypatch):
    assert _run(monkeypatch, _base("totally_unknown")) == []


def test_none_type_noop(monkeypatch):
    assert _run(monkeypatch, {"user_id": "u-1", "work_id": "i-1"}) == []


# ── handle_raw_event: missing / non-string user_id | work_id → early return ───


def test_missing_user_id_skips(monkeypatch):
    assert _run(monkeypatch, {"type": "rt_started", "work_id": "i-1"}) == []


def test_missing_work_id_skips(monkeypatch):
    assert _run(monkeypatch, {"type": "rt_started", "user_id": "u-1"}) == []


def test_non_string_user_id_skips(monkeypatch):
    assert _run(monkeypatch, {"type": "rt_started", "user_id": 123, "work_id": "i-1"}) == []


def test_non_string_work_id_skips(monkeypatch):
    assert _run(monkeypatch, {"type": "rt_started", "user_id": "u-1", "work_id": None}) == []


# ── handle_raw_event: output_ready → output.ready (C6) ────────────────────────


def test_output_ready_maps_to_output_ready_event(monkeypatch):
    raw = _base(
        "output_ready",
        payload={"document_id": "draft", "filename": "draft.docx", "size_bytes": 2048},
    )
    calls = _run(monkeypatch, raw)
    assert len(calls) == 1
    c = calls[0]
    assert c["event_type"] == "output.ready"
    assert c["data"] == {
        "document_id": "draft",
        "filename": "draft.docx",
        "size_bytes": 2048,
        "preview_url": "/api/v1/works/i-1/output/draft/preview",
        "download_url": "/api/v1/works/i-1/output/draft",
    }


def test_output_ready_missing_payload_defaults_none(monkeypatch):
    # payload 비-dict(부재) → {} → document_id None. URL 은 고정 draft route (C10 — doc_id 무관).
    calls = _run(monkeypatch, _base("output_ready"))
    assert len(calls) == 1
    c = calls[0]
    assert c["event_type"] == "output.ready"
    assert c["data"]["document_id"] is None
    assert c["data"]["filename"] is None
    assert c["data"]["size_bytes"] is None
    assert c["data"]["preview_url"] == "/api/v1/works/i-1/output/draft/preview"
    assert c["data"]["download_url"] == "/api/v1/works/i-1/output/draft"
