"""SSE 응답 helper."""

from __future__ import annotations

import json
from typing import Any


def event(name: str, data: dict[str, Any]) -> str:
    """SSE 이벤트 1개 직렬화."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {name}\ndata: {payload}\n\n"
