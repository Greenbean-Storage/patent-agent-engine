"""300.Actor sse — event() SSE 직렬화 전수 (invoke 단위).

대상: 300.Actor/src/sse.py:event
  - `event: <name>\\ndata: <json>\\n\\n` 프레이밍 정확성.
  - dict payload 가 json.dumps(ensure_ascii=False) 로 직렬화 (한글 raw 보존).
  - 빈 dict / 중첩 dict / 비-ASCII 분기.

순수 함수 — 외부 의존 없음. 진짜 assert (프레임 구조·역파싱 일치).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest  # noqa: F401  (suite 일관 — venv 보장)

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src import sse  # noqa: E402


def _split_frame(frame: str) -> tuple[str, str]:
    """`event: X\\ndata: Y\\n\\n` → (X, Y). 구조 불변식도 assert."""
    assert frame.endswith("\n\n")
    lines = frame[:-2].split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("event: ")
    assert lines[1].startswith("data: ")
    return lines[0][len("event: ") :], lines[1][len("data: ") :]


def test_event_basic_framing():
    out = sse.event("started", {"rt_id": "rt1"})
    assert out == 'event: started\ndata: {"rt_id": "rt1"}\n\n'


def test_event_roundtrip_parse():
    name, data_str = _split_frame(sse.event("result", {"a": 1, "b": [2, 3]}))
    assert name == "result"
    assert json.loads(data_str) == {"a": 1, "b": [2, 3]}


def test_event_empty_data():
    out = sse.event("pong", {})
    assert out == "event: pong\ndata: {}\n\n"


def test_event_nested_dict():
    name, data_str = _split_frame(sse.event("progress", {"phase": "x", "meta": {"n": 1}}))
    assert name == "progress"
    assert json.loads(data_str) == {"phase": "x", "meta": {"n": 1}}


def test_event_non_ascii_not_escaped():
    """ensure_ascii=False — 한글이 \\u 이스케이프 없이 raw 로 들어가야 한다."""
    out = sse.event("error", {"message": "오류"})
    _, data_str = _split_frame(out)
    assert "오류" in out  # raw 한글이 프레임 안에
    assert "\\u" not in data_str  # 이스케이프 안 됨
    assert json.loads(data_str) == {"message": "오류"}
