"""Stage 5 — `$.inputs.<custom>` placeholder 금지 검증.

caller_inputs body 메커니즘이 폐기됐으므로 pipeline 정의에서
`$.inputs.user_id/work_id/chain_id` 외의 키는 금지.

대체 통로:
  - 부모 chain 의 step output → `$.parent_outputs.<step_id>.<field>`
  - 사용자 message payload → `$.user_input.<field>`
  - CM 영속 데이터 (IOM, contexts) → inject_context 의 `cm://` spec + `$.<inject_name>.*`
"""

from __future__ import annotations

from typing import Any

from .._common import ValidationReport

STAGE_NAME = "no inputs placeholder"

# 시스템 메타 (orchestrator 가 항상 박는 키) 만 허용.
_ALLOWED_INPUTS_KEYS = {"user_id", "work_id", "chain_id"}


def _walk_strings(node: Any):
    """JSON tree 의 모든 string leaf 를 yield."""
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)
    elif isinstance(node, str):
        yield node


def validate_no_inputs_placeholder(
    pid: str,
    raw: dict[str, Any],
    rep: ValidationReport,
) -> bool:
    """`$.inputs.<custom>` 발견 시 fail-loud."""
    ok = True
    for s in _walk_strings(raw):
        if not s.startswith("$.inputs."):
            continue
        rest = s.removeprefix("$.inputs.")
        head = rest.split(".", 1)[0]
        if head in _ALLOWED_INPUTS_KEYS:
            continue
        rep.err(
            f"[{pid}] stage5 forbidden placeholder '{s}' — `$.inputs.<custom>` 는 폐기. "
            f"`$.parent_outputs.<step_id>.<x>` / `$.user_input.<x>` / "
            f"`$.<inject_name>.<x>` (cm:// inject_context 경유) 중 하나 사용."
        )
        ok = False
    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
