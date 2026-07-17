"""Placeholder 치환 — RT input 의 $.path 표현식 → context lookup.

DRC P{NN} 포맷 전용. 구설계 branch 평가 (eval_condition/eval_next_conditional) 폐기.
"""

from __future__ import annotations

import re
from typing import Any

_PATH_RE = re.compile(r"^\$\.")


def _resolve(expr: str, context: dict[str, Any]) -> Any:
    if not isinstance(expr, str):
        return expr
    if not _PATH_RE.match(expr):
        return expr
    parts = expr[2:].split(".")
    cur: Any = context
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if 0 <= idx < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def substitute_placeholders(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str) and _PATH_RE.match(value):
        return _resolve(value, context)
    if isinstance(value, dict):
        return {k: substitute_placeholders(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute_placeholders(v, context) for v in value]
    return value
