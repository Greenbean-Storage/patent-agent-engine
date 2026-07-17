"""SSE 응답 helper — 실 `src/sse.py` 동형 (wire format 일치)."""

from __future__ import annotations

import json
from typing import Any


def event(name: str, data: dict[str, Any]) -> str:
    """SSE 이벤트 1개 직렬화."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {name}\ndata: {payload}\n\n"
