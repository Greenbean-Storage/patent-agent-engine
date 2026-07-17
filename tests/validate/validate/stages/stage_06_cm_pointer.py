"""Stage 6 — `cm://X.dot.path` 표기 폐기 검증.

P-E 정합: cm:// 의 부분 read 는 RFC 6901 slash 표기 (`cm://X/sub/path`) 로만 허용.
client-side `_walk` 폐기와 짝이 됨 — dot-path 가 남아 있으면 _cm_fetch 가 RuntimeError.

허용:
  - `cm://invention_object_model`               (root 전체)
  - `cm://concept_discovery_stack/purpose`      (sub-tree, RFC 6901 slash)
  - `cm://dialogs/<persona>.<name>.json`        (persona dialog — 단일 resource, dot 은 segment 내부)

금지:
  - `cm://concept_discovery_stack.purpose`      (옛 dot-path)
"""

from __future__ import annotations

import re
from typing import Any

from .._common import ValidationReport

STAGE_NAME = "cm:// pointer notation"

_CM_PREFIX = "cm://"


def _walk_strings(node: Any):
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)
    elif isinstance(node, str):
        yield node


def _is_dialog_path(path: str) -> bool:
    """`dialogs/<int>.<name>.json` 형식 — dot 이 resource 식별자 내부."""
    return bool(re.match(r"^dialogs/\d+\.[a-zA-Z0-9_-]+(\.json)?$", path))


def validate_cm_pointer(
    pid: str,
    raw: dict[str, Any],
    rep: ValidationReport,
) -> bool:
    ok = True
    for s in _walk_strings(raw):
        if not s.startswith(_CM_PREFIX):
            continue
        path = s.removeprefix(_CM_PREFIX)
        if _is_dialog_path(path):
            continue
        if "." in path:
            rep.err(f"[{pid}] stage6 cm:// dot-path 폐기 — RFC 6901 slash 표기 사용: '{s}'")
            ok = False
    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
