"""Stage 4 — Tool registry 정합 (pipeline tool step ↔ Actor @register).

tool step (`tool: "name"`) 의 호출 대상이 `300.Actor/src/tools/` 의
`@register("name")` 데코레이터로 실제 등록되어 있는지 + 파이프라인의
params key 가 그 함수 signature 와 일치하는지 검증. 등록 안 된 도구
또는 unknown param 발견 시 fail-loud (production 호출 시 fail 잠재 결함).
"""

from __future__ import annotations

import ast
from typing import Any

from .._common import ROOT, ValidationReport

STAGE_NAME = "tool registry"


def collect_actor_tool_signatures() -> dict[str, dict[str, Any]]:
    """`300.Actor/src/tools/` 의 모든 `@register("name") (async )?def fn(...)` 를 파싱.

    반환: {tool_name: {"params": [param_names], "has_varkw": bool}}
    - params: positional-or-keyword 파라미터 이름 list (self 제외, **kwargs 제외)
    - has_varkw: **kwargs 가 있으면 True (그러면 unknown param 허용)
    """
    tools_root = ROOT / "300.Actor" / "src" / "tools"
    sigs: dict[str, dict[str, Any]] = {}
    if not tools_root.exists():
        return sigs

    for py_file in tools_root.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            tool_name = None
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Name)
                    and dec.func.id == "register"
                    and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)
                ):
                    tool_name = dec.args[0].value
                    break
            if not tool_name:
                continue
            args = node.args
            param_names: list[str] = []
            for a in args.args:
                if a.arg == "self":
                    continue
                param_names.append(a.arg)
            for a in args.kwonlyargs:
                param_names.append(a.arg)
            has_varkw = args.kwarg is not None
            sigs[tool_name] = {"params": param_names, "has_varkw": has_varkw}
    return sigs


def validate_tool_registry(
    pid: str,
    raw: dict[str, Any],
    tool_sigs: dict[str, dict[str, Any]],
    rep: ValidationReport,
) -> bool:
    """tool step 의 호출 대상이 Actor 에 @register 되어 있고 params key 가 signature 와 일치."""
    ok = True
    steps = raw.get("steps") or []

    def _check(step: dict[str, Any], label: str) -> None:
        nonlocal ok
        tname = step.get("tool")
        if not tname:
            return
        sig = tool_sigs.get(tname)
        if sig is None:
            rep.err(
                f"[{pid}] stage4 step[{label}] tool '{tname}' — "
                f"`300.Actor/src/tools/` 에 @register 되어 있지 않음 (production 호출 시 fail)"
            )
            ok = False
            return
        params = step.get("params") or {}
        if not isinstance(params, dict):
            rep.err(f"[{pid}] stage4 step[{label}] params 가 dict 아님: {type(params).__name__}")
            ok = False
            return
        if sig["has_varkw"]:
            return  # **kwargs 면 모든 key 허용
        sig_params = set(sig["params"])
        for k in params.keys():
            if k not in sig_params:
                rep.err(
                    f"[{pid}] stage4 step[{label}] tool '{tname}' params 에 "
                    f"unknown key '{k}' — signature: {sorted(sig_params)}"
                )
                ok = False

    for idx, step in enumerate(steps):
        if isinstance(step, list):
            for sidx, sub in enumerate(step):
                if isinstance(sub, dict):
                    _check(sub, f"{idx}[{sidx}]")
            continue
        if isinstance(step, dict):
            _check(step, str(idx))

    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
