"""drawing.* 전수 (invoke 단위) — 300.Actor/src/tools/drawing/__init__.py.

대상 handler: drawing.plantuml / drawing.openscad / drawing.schemdraw / drawing.render.
내부 helper: _run_cli / _has / _render_plantuml / _render_openscad / _render_schemdraw /
_render_dispatch / _pick_code.

CLI 의존:
  - plantuml / openscad 바이너리는 이 dev 환경에 없음 → _has() False.
    실제 호출하면 RuntimeError("... not installed") 분기를 그대로 검증 (mock 없이).
  - 성공 경로 (rc=0 + 산출파일 존재) 는 _run_cli + tempfile 산출물을 monkeypatch 로 구성해
    검증 — 바이너리 없는 환경에서 deterministic. CLI 가 있으면 그대로 통과(아래 success
    test 들은 _run_cli 를 mock 하므로 바이너리 유무와 무관하게 동작).

검증:
  - register 가 4 handler 모두 TOOLS 에 등록
  - _has: 존재(python3)·부재(없는 bin)
  - _pick_code: code 우선, dl_code fallback, 둘 다 없으면 ""
  - _run_cli: 정상 returncode/stdout/stderr, timeout → RuntimeError
  - 각 renderer 성공(b64 svg) / rc!=0 실패 / 산출파일 누락 실패 / 바이너리 부재(plantuml·openscad)
  - _render_dispatch: unsupported tool / renderer 예외 삼킴(status=error) / success
  - render handler: format alias(format/chosen_tool), code alias(code/dl_code), format 누락 error
  - plantuml/mermaid alias 가 같은 renderer

외부(subprocess)는 monkeypatch 로 격리 (asyncio.create_subprocess_exec / wait_for / _run_cli).

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴). 진짜 assert.
"""

from __future__ import annotations

import asyncio
import base64
import shutil
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools import drawing as dw  # noqa: E402
from src.tools import get as tool_get  # noqa: E402

_SVG = b"<svg>hi</svg>"
_SVG_B64 = base64.b64encode(_SVG).decode("ascii")


# ── registry ──────────────────────────────────────────────────────────────────


def test_handlers_registered():
    assert tool_get("drawing.plantuml") is dw.plantuml
    assert tool_get("drawing.openscad") is dw.openscad
    assert tool_get("drawing.schemdraw") is dw.schemdraw
    assert tool_get("drawing.render") is dw.render


def test_renderer_table_mermaid_aliases_plantuml():
    assert dw._RENDERERS["mermaid"] is dw._RENDERERS["plantuml"]


# ── _has ────────────────────────────────────────────────────────────────────────


def test_has_present_binary():
    """python3 은 PATH 에 존재."""
    assert dw._has("python3") is True


def test_has_absent_binary():
    assert dw._has("definitely-not-a-real-binary-xyz") is False


def test_has_monkeypatched(monkeypatch):
    monkeypatch.setattr(dw.shutil, "which", lambda name: "/usr/bin/" + name)
    assert dw._has("anything") is True
    monkeypatch.setattr(dw.shutil, "which", lambda name: None)
    assert dw._has("anything") is False


# ── _pick_code ───────────────────────────────────────────────────────────────


def test_pick_code_prefers_code():
    assert dw._pick_code("A", "B") == "A"


def test_pick_code_falls_back_to_dl_code():
    assert dw._pick_code(None, "B") == "B"


def test_pick_code_both_none_returns_empty():
    assert dw._pick_code(None, None) == ""


# ── _run_cli (real subprocess via python3 -c) ──────────────────────────────────


def test_run_cli_success():
    rc, out, err = asyncio.run(dw._run_cli(["python3", "-c", "print('ok')"]))
    assert rc == 0
    assert out.strip() == b"ok"
    assert err == b""


def test_run_cli_nonzero_rc_with_stderr():
    rc, _out, err = asyncio.run(
        dw._run_cli(["python3", "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])
    )
    assert rc == 3
    assert b"boom" in err


def test_run_cli_timeout_raises(monkeypatch):
    """wait_for 가 TimeoutError → proc.kill/wait 후 RuntimeError."""

    class _FakeProc:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):  # pragma: no cover - 호출 전에 timeout
            return b"", b""

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

        @property
        def returncode_(self):
            return None

    proc = _FakeProc()

    async def _fake_exec(*_a, **_kw):
        return proc

    async def _fake_wait_for(_coro, timeout):
        # 넘긴 coroutine 은 닫아 RuntimeWarning 방지.
        _coro.close()
        raise TimeoutError

    monkeypatch.setattr(dw.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(dw.asyncio, "wait_for", _fake_wait_for)

    with pytest.raises(RuntimeError, match="render timeout after 0.01s"):
        asyncio.run(dw._run_cli(["python3", "-c", "x"], timeout=0.01))
    assert proc.killed is True
    assert proc.waited is True


def test_run_cli_none_returncode_and_streams_default(monkeypatch):
    """returncode None / out None / err None → (0, b'', b'') 정규화."""

    class _FakeProc:
        returncode = None

        async def communicate(self):
            return None, None

    async def _fake_exec(*_a, **_kw):
        return _FakeProc()

    monkeypatch.setattr(dw.asyncio, "create_subprocess_exec", _fake_exec)
    rc, out, err = asyncio.run(dw._run_cli(["x"]))
    assert (rc, out, err) == (0, b"", b"")


# ── renderer success (mock _run_cli + 산출파일 작성) ───────────────────────────


def _patch_run_cli_writing(monkeypatch, target_suffix: str, rc: int = 0, write: bool = True):
    """_run_cli 를 가로채, cmd 의 산출 경로에 SVG 를 쓴 뒤 (rc, b'', b'') 반환.

    plantuml: src.with_suffix('.svg'). openscad/schemdraw: cmd 에 -o <out> 또는 마지막 인자.
    """

    async def _fake(cmd, timeout=120.0):
        if write:
            if target_suffix == "plantuml":
                # cmd = ["plantuml", "-tsvg", "<src.puml>"]
                src = Path(cmd[-1])
                src.with_suffix(".svg").write_bytes(_SVG)
            elif target_suffix == "openscad":
                # cmd = [..., "-o", "<out.svg>", "<src.scad>"]
                out = Path(cmd[cmd.index("-o") + 1])
                out.write_bytes(_SVG)
            elif target_suffix == "schemdraw":
                # cmd = ["python", "<runner.py>"]; OUT_PATH 는 runner 안. 직접 추론:
                runner = Path(cmd[-1])
                circuit = runner.parent / "circuit.svg"
                circuit.write_bytes(_SVG)
        return rc, b"", (b"" if rc == 0 else b"stderr-text")

    monkeypatch.setattr(dw, "_run_cli", _fake)


def test_render_plantuml_success(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml")
    raw, ext = asyncio.run(dw._render_plantuml("@startuml\nA->B\n@enduml"))
    assert raw == _SVG
    assert ext == "svg"


def test_render_plantuml_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: False)
    with pytest.raises(RuntimeError, match="plantuml binary not installed"):
        asyncio.run(dw._render_plantuml("x"))


def test_render_plantuml_nonzero_rc_raises(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml", rc=1, write=False)
    with pytest.raises(RuntimeError, match="plantuml failed rc=1"):
        asyncio.run(dw._render_plantuml("x"))


def test_render_plantuml_missing_output_raises(monkeypatch):
    """rc=0 이지만 svg 산출 안 됨 → not svg.exists() 분기."""
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml", rc=0, write=False)
    with pytest.raises(RuntimeError, match="plantuml failed rc=0"):
        asyncio.run(dw._render_plantuml("x"))


def test_render_openscad_success(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "openscad")
    raw, ext = asyncio.run(dw._render_openscad("cube([1,1,1]);"))
    assert raw == _SVG
    assert ext == "svg"


def test_render_openscad_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: False)
    with pytest.raises(RuntimeError, match="openscad binary not installed"):
        asyncio.run(dw._render_openscad("x"))


def test_render_openscad_nonzero_rc_raises(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "openscad", rc=2, write=False)
    with pytest.raises(RuntimeError, match="openscad failed rc=2"):
        asyncio.run(dw._render_openscad("x"))


def test_render_schemdraw_success(monkeypatch):
    """schemdraw 는 _has 체크 없음 — _run_cli 만 mock."""
    _patch_run_cli_writing(monkeypatch, "schemdraw")
    raw, ext = asyncio.run(dw._render_schemdraw("d = schemdraw.Drawing()"))
    assert raw == _SVG
    assert ext == "svg"


def test_render_schemdraw_failure_raises(monkeypatch):
    _patch_run_cli_writing(monkeypatch, "schemdraw", rc=1, write=False)
    with pytest.raises(RuntimeError, match="schemdraw failed rc=1"):
        asyncio.run(dw._render_schemdraw("bad code"))


# ── _render_dispatch ───────────────────────────────────────────────────────────


def test_dispatch_unsupported_tool():
    out = asyncio.run(dw._render_dispatch("graphviz", "x"))
    assert out["status"] == "unsupported"
    assert out["chosen_tool"] == "graphviz"
    assert "graphviz" in out["error"]
    assert out["figure_bytes_b64"] == ""


def test_dispatch_success(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml")
    out = asyncio.run(dw._render_dispatch("plantuml", "@startuml\n@enduml"))
    assert out["status"] == "success"
    assert out["chosen_tool"] == "plantuml"
    assert out["figure_bytes_b64"] == _SVG_B64
    assert out["mime_type"] == "image/svg+xml"
    assert out["file_extension"] == "svg"


def test_dispatch_renderer_exception_becomes_error_status(monkeypatch):
    """renderer 예외(바이너리 부재) → status=error 로 삼킴."""
    monkeypatch.setattr(dw, "_has", lambda name: False)
    out = asyncio.run(dw._render_dispatch("plantuml", "x"))
    assert out["status"] == "error"
    assert out["chosen_tool"] == "plantuml"
    assert "not installed" in out["error"]
    assert out["figure_bytes_b64"] == ""


def test_dispatch_case_insensitive_tool(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml")
    out = asyncio.run(dw._render_dispatch("PlantUML", "x"))
    assert out["status"] == "success"


def test_dispatch_unknown_ext_mime_fallback(monkeypatch):
    """renderer 가 'svg'/'png' 외 ext 반환 → mime octet-stream fallback."""

    async def _fake_renderer(_code):
        return b"\x00\x01", "pdf"

    monkeypatch.setitem(dw._RENDERERS, "fakefmt", _fake_renderer)
    out = asyncio.run(dw._render_dispatch("fakefmt", "x"))
    assert out["status"] == "success"
    assert out["file_extension"] == "pdf"
    assert out["mime_type"] == "application/octet-stream"


# ── thin handlers (plantuml/openscad/schemdraw) ────────────────────────────────


def test_plantuml_handler_routes(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml")
    out = asyncio.run(dw.plantuml(code="@startuml\n@enduml"))
    assert out["status"] == "success"
    assert out["chosen_tool"] == "plantuml"


def test_plantuml_handler_dl_code_alias(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml")
    out = asyncio.run(dw.plantuml(dl_code="@startuml\n@enduml"))
    assert out["status"] == "success"


def test_openscad_handler_routes(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "openscad")
    out = asyncio.run(dw.openscad(code="cube([1,1,1]);"))
    assert out["status"] == "success"
    assert out["chosen_tool"] == "openscad"


def test_schemdraw_handler_routes(monkeypatch):
    _patch_run_cli_writing(monkeypatch, "schemdraw")
    out = asyncio.run(dw.schemdraw(code="d = schemdraw.Drawing()"))
    assert out["status"] == "success"
    assert out["chosen_tool"] == "schemdraw"


# ── render handler (alias 흡수) ─────────────────────────────────────────────────


def test_render_format_arg(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml")
    out = asyncio.run(dw.render(format="plantuml", code="@startuml\n@enduml"))
    assert out["status"] == "success"
    assert out["chosen_tool"] == "plantuml"


def test_render_chosen_tool_arg(monkeypatch):
    """format 누락 시 chosen_tool 사용."""
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "openscad")
    out = asyncio.run(dw.render(chosen_tool="openscad", dl_code="cube();"))
    assert out["status"] == "success"
    assert out["chosen_tool"] == "openscad"


def test_render_format_takes_priority_over_chosen_tool(monkeypatch):
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml")
    out = asyncio.run(
        dw.render(format="plantuml", chosen_tool="openscad", code="@startuml\n@enduml")
    )
    assert out["chosen_tool"] == "plantuml"


def test_render_figure_format_arg_ignored_for_routing(monkeypatch):
    """figure_format 은 흡수만 — 라우팅에 영향 없음."""
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "schemdraw")
    out = asyncio.run(
        dw.render(format="schemdraw", code="d = schemdraw.Drawing()", figure_format="png")
    )
    assert out["status"] == "success"


def test_render_missing_format_returns_error():
    out = asyncio.run(dw.render(code="x"))
    assert out["status"] == "error"
    assert out["error"] == "format/chosen_tool required"
    assert out["chosen_tool"] == ""
    assert out["figure_bytes_b64"] == ""


def test_render_no_code_passes_empty_source(monkeypatch):
    """code/dl_code 둘 다 없어도 format 있으면 dispatch (빈 소스)."""
    monkeypatch.setattr(dw, "_has", lambda name: True)
    _patch_run_cli_writing(monkeypatch, "plantuml")
    out = asyncio.run(dw.render(format="plantuml"))
    assert out["status"] == "success"


# ── 실제 바이너리 없을 때 (skip 유지 — 환경 게이트) ─────────────────────────────


def test_real_plantuml_skips_when_absent():
    """실제 plantuml CLI 가 없으면 미설치 분기를 검증, 있으면 skip (mock 없는 실호출 회피)."""
    if shutil.which("plantuml") is not None:  # pragma: no cover - dev 환경엔 없음
        pytest.skip("plantuml binary present — mock 없는 실호출 회피")
    out = asyncio.run(dw.plantuml(code="@startuml\n@enduml"))
    assert out["status"] == "error"
    assert "not installed" in out["error"]


def test_real_openscad_skips_when_absent():
    if shutil.which("openscad") is not None:  # pragma: no cover - dev 환경엔 없음
        pytest.skip("openscad binary present — mock 없는 실호출 회피")
    out = asyncio.run(dw.openscad(code="cube();"))
    assert out["status"] == "error"
    assert "not installed" in out["error"]
