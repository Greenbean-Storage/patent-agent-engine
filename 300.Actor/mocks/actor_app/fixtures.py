"""llm-fixture strict load — 실 FixtureSession 과 같은 파일, 다른 miss 정책.

`{FIXTURE_PATH}/{pipeline_id}/{step_id}.json` (compose 가 `tests/data/llm-fixtures` 를
ro mount). 실 FixtureSession 의 echo fallback 은 미러하지 않는다 — mock 에서 fixture miss
= 명시적 실패 (3g strict fail-loud, false-green 방지).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config


class FixtureMiss(Exception):
    """fixture 부재/비정상 — 호출측이 SSE error event 로 변환."""


def load(pipeline_id: str, step_id: str) -> dict[str, Any] | list[Any]:
    path = Path(config.FIXTURE_PATH) / pipeline_id / f"{step_id}.json"
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise FixtureMiss(f"mock-actor strict fixture miss: {pipeline_id}/{step_id}.json") from e
    except json.JSONDecodeError as e:
        raise FixtureMiss(
            f"mock-actor fixture parse error: {pipeline_id}/{step_id}.json — {e}"
        ) from e
    if not isinstance(data, dict | list):
        raise FixtureMiss(f"mock-actor fixture not dict|list: {pipeline_id}/{step_id}.json")
    return data
