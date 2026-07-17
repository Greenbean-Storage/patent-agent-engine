"""busy-503 marker (3b) — 의도적 503 으로 DRO fallback/backoff 실경로 검증.

구 1-slot `_BusyState` 폐기 — 실 Actor 의 "1 컨테이너 = 1 작업" 의미론 자체가
persona 별 동시성 cap(src/slots.py, engine.config 집행)으로 대체되어, mock 에 1-slot 을
남기면 real 에 없는 제약을 시뮬레이트하게 된다 (mirror 위반). mock 은 즉답 replay 라
cap 포화가 관측되지 않으므로 동시성 cap 은 시뮬레이트하지 않고 (divergence 명기),
**의도적 503 = marker 가 전담**한다.

marker = `{BUSY_MARKER_DIR}/{pipeline_id}/{step_id}.json` — 이미지에 bake (변경 = make up rebuild).
내용 `{"times": N}` (기본 1): **모든** instance 가 해당 (pipeline, step) dispatch 를 처음 N회
503 으로 거절 — instance 비차별. DRO 의 후보 fallback 과 AllActorsBusy 시간예산 backoff 가
둘 다 실 경로로 검증된 뒤 chain 이 완주한다. malformed marker = fail-loud.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config

# (pipeline_id, step_id) → 이 instance 가 지금까지 503 으로 거절한 횟수 (프로세스 수명).
_marker_counts: dict[tuple[str, str], int] = {}


def marker_503(pipeline_id: str, step_id: str) -> bool:
    """marker 가 있고 아직 N회 미달이면 True (→ 503). 잘못된 marker 는 조용히 무시하지 않는다."""
    path = Path(config.BUSY_MARKER_DIR) / pipeline_id / f"{step_id}.json"
    if not path.exists():
        return False
    raw = json.loads(path.read_text(encoding="utf-8"))  # malformed → JSONDecodeError fail-loud
    if not isinstance(raw, dict):
        raise RuntimeError(f"busy marker must be a JSON object: {path}")
    times = int(raw.get("times", 1))
    key = (pipeline_id, step_id)
    used = _marker_counts.get(key, 0)
    if used >= times:
        return False
    _marker_counts[key] = used + 1
    return True
