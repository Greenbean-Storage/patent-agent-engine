"""SSE 응답 helper (event 직렬화).

DRO→Nexus event 채널의 프레이밍 — `dispatcher.parse_sse` 의 역방향.
300.Actor/src/sse.py 와 동일 포맷 (event:/data:, ensure_ascii=False).
"""

from __future__ import annotations

import json
from typing import Any


def event(name: str, data: dict[str, Any]) -> str:
    """SSE 이벤트 1개 직렬화."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {name}\ndata: {payload}\n\n"
