"""C4 — client WS 프레임을 `@contracts/00.dro/websocket-events.json` 에 실측 검증.

봉투 top-level(`{type,timestamp,seq,data}` · additionalProperties:false · type enum) +
type별 data(`_payload_schemas[type]`). `tests/play/play/_sse.py` 의 raw-sse 검증과 같은 취지 —
계약이 코드 산출물과 정합하는지 테스트측에서 집행(프로덕션 hot-path 아님).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@contracts").is_dir())
_SCHEMA = json.loads(
    (_ROOT / "@contracts" / "00.dro" / "websocket-events.json").read_text(encoding="utf-8")
)
_PAYLOADS = _SCHEMA.get("_payload_schemas", {})
# 봉투 검증기 — `_payload_schemas` 는 Draft7 미지원 키워드라 무시됨(annotation 취급).
_ENVELOPE = jsonschema.Draft7Validator(_SCHEMA)


def validate_ws_frame(frame: object) -> list[str]:
    """봉투 + type별 data 검증. 위반 메시지 리스트 반환 (빈 리스트 = 적합)."""
    if not isinstance(frame, dict):
        return [f"not an object: {type(frame).__name__}"]
    errs = [f"envelope: {e.message}" for e in _ENVELOPE.iter_errors(frame)]
    ev_type = frame.get("type")
    ps = _PAYLOADS.get(ev_type)
    data = frame.get("data")
    if isinstance(ps, dict) and isinstance(data, dict):
        errs += [
            f"data[{ev_type}]: {e.message}"
            for e in jsonschema.Draft7Validator(ps).iter_errors(data)
        ]
    return errs
