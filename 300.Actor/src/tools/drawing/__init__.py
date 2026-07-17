"""도면 코드 생성·렌더링 tool. 기존 05.Crafter 에서 이전.

CLI 의존성:
  - plantuml (jar 기반)
  - openscad (--export-format svg2d)
  - schemdraw (Python lib, subprocess)
바이너리 없으면 stub 응답.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .. import register

log = logging.getLogger(__name__)

_EXT_TO_MIME = {"svg": "image/svg+xml", "png": "image/png"}


async def _run_cli(cmd: list[str], timeout: float | None = None) -> tuple[int, bytes, bytes]:
    if timeout is None:
        from ... import engine_config

        timeout = float(engine_config.tools()["drawing"]["render_timeout_s"])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"render timeout after {timeout}s: {' '.join(cmd[:3])}")
    return (proc.returncode or 0), (out or b""), (err or b"")


def _has(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


async def _render_plantuml(dl_code: str) -> tuple[bytes, str]:
    if not _has("plantuml"):
        raise RuntimeError("plantuml binary not installed")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "diagram.puml"
        src.write_text(dl_code, encoding="utf-8")
        rc, _out, err = await _run_cli(["plantuml", "-tsvg", str(src)])
        svg = src.with_suffix(".svg")
        if rc != 0 or not svg.exists():
            raise RuntimeError(
                f"plantuml failed rc={rc} stderr={err.decode(errors='replace')[:300]}"
            )
        return svg.read_bytes(), "svg"


async def _render_openscad(dl_code: str) -> tuple[bytes, str]:
    if not _has("openscad"):
        raise RuntimeError("openscad binary not installed")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "model.scad"
        out = Path(td) / "model.svg"
        src.write_text(dl_code, encoding="utf-8")
        rc, _stdout, err = await _run_cli(
            [
                "openscad",
                "--export-format",
                "svg2d",
                "-o",
                str(out),
                str(src),
            ]
        )
        if rc != 0 or not out.exists():
            raise RuntimeError(
                f"openscad failed rc={rc} stderr={err.decode(errors='replace')[:300]}"
            )
        return out.read_bytes(), "svg"


async def _render_schemdraw(dl_code: str) -> tuple[bytes, str]:
    """LLM 이 생성한 schemdraw 코드를 격리 subprocess 에서 실행해 SVG 출력."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "circuit.svg"
        runner = f"import schemdraw\nOUT_PATH = r'{out}'\n{dl_code}\n"
        src = Path(td) / "runner.py"
        src.write_text(runner, encoding="utf-8")
        rc, _stdout, err = await _run_cli(["python", str(src)])
        if rc != 0 or not out.exists():
            raise RuntimeError(
                f"schemdraw failed rc={rc} stderr={err.decode(errors='replace')[:300]}"
            )
        return out.read_bytes(), "svg"


_RENDERERS = {
    "plantuml": _render_plantuml,
    "mermaid": _render_plantuml,
    "openscad": _render_openscad,
    "schemdraw": _render_schemdraw,
}


async def _render_dispatch(chosen_tool: str, dl_code: str) -> dict[str, Any]:
    fn = _RENDERERS.get(chosen_tool.lower())
    if fn is None:
        return {
            "status": "unsupported",
            "chosen_tool": chosen_tool,
            "figure_bytes_b64": "",
            "mime_type": "",
            "file_extension": "",
            "error": f"renderer not implemented for '{chosen_tool}'",
        }
    try:
        raw, ext = await fn(dl_code)
    except Exception as e:  # noqa: BLE001
        log.warning("renderer.failed tool=%s error=%s", chosen_tool, e)
        return {
            "status": "error",
            "chosen_tool": chosen_tool,
            "figure_bytes_b64": "",
            "mime_type": "",
            "file_extension": "",
            "error": str(e)[:500],
        }
    return {
        "status": "success",
        "chosen_tool": chosen_tool,
        "figure_bytes_b64": base64.b64encode(raw).decode("ascii"),
        "mime_type": _EXT_TO_MIME.get(ext, "application/octet-stream"),
        "file_extension": ext,
    }


def _pick_code(code: str | None, dl_code: str | None) -> str:
    """pipeline alias 흡수: code 또는 dl_code."""
    return code or dl_code or ""


@register("drawing.plantuml")
async def plantuml(code: str | None = None, dl_code: str | None = None) -> dict[str, Any]:
    return await _render_dispatch("plantuml", _pick_code(code, dl_code))


@register("drawing.openscad")
async def openscad(code: str | None = None, dl_code: str | None = None) -> dict[str, Any]:
    return await _render_dispatch("openscad", _pick_code(code, dl_code))


@register("drawing.schemdraw")
async def schemdraw(code: str | None = None, dl_code: str | None = None) -> dict[str, Any]:
    return await _render_dispatch("schemdraw", _pick_code(code, dl_code))


@register("drawing.render")
async def render(
    format: str | None = None,
    code: str | None = None,
    chosen_tool: str | None = None,
    dl_code: str | None = None,
    figure_format: str | None = None,
) -> dict[str, Any]:
    """pipeline alias 흡수.

    - chosen_tool ↔ format : 어느 렌더러 (plantuml/openscad/schemdraw)
    - dl_code ↔ code       : DL DSL 소스
    - figure_format        : 출력 이미지 포맷 (svg/png/pdf) — 현재 _render_dispatch 가
                              renderer 기본값으로 처리 (P05 contract 의 figure_format 흡수용).
    """
    fmt = format or chosen_tool or ""
    src = _pick_code(code, dl_code)
    if not fmt:
        return {
            "status": "error",
            "error": "format/chosen_tool required",
            "chosen_tool": "",
            "figure_bytes_b64": "",
            "mime_type": "",
            "file_extension": "",
        }
    return await _render_dispatch(fmt, src)
