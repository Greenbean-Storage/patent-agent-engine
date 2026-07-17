"""probe 의 CM-하네스 primitive — setup(token/session/seed/trigger) · CM fetch · rich 출력 · 최종 artifacts.

play track 이 이 모듈을 라이브러리로 import 해 pipeline 을 실행한다 — run_pipeline 등 '로직' 은 play 소유
(`play/_run.py`). probe 의 sub-command(view 등)도 동일 fetch/print 헬퍼 사용 — single source.

제공:
  setup: `_dev_token` · `_create_session` · `_seed_iom` · `_trigger_pipeline`
  fetch: `_fetch_iom` · `_fetch_drawings_manifest` · `_fetch_drawing_artifact` · `_fetch_rt` · `_fetch_trail_raw`
  출력: `_print_rt_step` · `_print_tool_call_*` · `_render_final_artifacts` · `_export_docx`
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from venezia_topology import service_url

DRO_URL = os.environ.get("DRO_URL", service_url("dro"))
CM_URL = os.environ.get("CM_URL", service_url("cm"))
# 100.Nexus 컨테이너 — 외부 게이트웨이 (auth + works + 모든 client 표면).
ACCOUNT_URL = os.environ.get("ACCOUNT_URL", service_url("nexus"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


async def _dev_token(http: httpx.AsyncClient) -> tuple[str, str]:
    """auth (구 /auth/dev-token 폐기) — OPEN 무토큰 / SECURE 공유 secret JWT mint."""
    uid = "00000000-0000-0000-0000-00000000open"
    auth_mode = "open"
    try:
        auth_mode = (
            ((await http.get(f"{ACCOUNT_URL}/health", timeout=5)).json() or {})
            .get("auth_mode", "open")
            .lower()
        )
    except Exception:  # noqa: BLE001
        pass
    if auth_mode == "secure":
        import jwt  # noqa: PLC0415
        from datetime import UTC, datetime, timedelta  # noqa: PLC0415

        secret = os.environ.get("JWT_SECRET_KEY") or "dev-only-jwt-secret-NOT-FOR-PRODUCTION-USE"
        now = datetime.now(UTC)
        tok = jwt.encode(  # nosemgrep
            {"sub": uid, "typ": "access", "iat": now, "exp": now + timedelta(hours=1)},
            secret,
            algorithm="HS256",
        )
        return tok, uid
    return "", uid


async def _create_session(http: httpx.AsyncClient, token: str) -> str:
    cookies = {"nx_access": token} if token else {}
    r = await http.post(f"{ACCOUNT_URL}/api/v1/user/works", cookies=cookies, timeout=30)
    r.raise_for_status()
    return r.json()["work_id"]


async def _seed_iom(
    http: httpx.AsyncClient,
    user_id: str,
    work_id: str,
    seed_path: Path,
) -> None:
    """파일에서 IOM JSON 을 로드해 CM 에 PUT — fixture/echo mode 전용 우회.

    Production mode 에서 P{NN} 의 정상 흐름은 P2 Director 가 IOM 작성하므로 이 우회는
    검증 도구만 사용. 호출자가 명시한 path 만 받아 inline default 미사용.
    """
    iom = json.loads(seed_path.read_text(encoding="utf-8"))
    r = await http.put(
        f"{CM_URL}/sessions/{user_id}/{work_id}/models/invention-object-model",
        json=iom,
        timeout=30,
    )
    if r.status_code not in (200, 201, 204):
        _log(f"WARN seed IOM status={r.status_code} body={r.text[:200]}")


async def _trigger_pipeline(
    http: httpx.AsyncClient,
    token: str,  # noqa: ARG001 — control 은 인증 없음 (내부망); 시그니처 호환 위해 유지
    user_id: str,
    work_id: str,
    pipeline_id: str,
) -> str:
    # pipeline trigger = DRO control/spawn (내부 — 개발/검증 직접 trigger, Q22). chain_id 는 caller 발급.
    import uuid  # noqa: PLC0415

    persona = int(pipeline_id[1:3]) if pipeline_id[:1] == "P" else 0
    chain_id = str(uuid.uuid4())
    r = await http.post(
        f"{DRO_URL}/control/spawn",
        json={
            "user_id": user_id,
            "work_id": work_id,
            "persona": persona,
            "pipeline_id": pipeline_id,
            "chain_id": chain_id,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["chain_id"]


async def _fetch_iom(http: httpx.AsyncClient, user_id: str, work_id: str) -> dict[str, Any]:
    r = await http.get(
        f"{CM_URL}/sessions/{user_id}/{work_id}/models/invention-object-model",
        timeout=10,
    )
    return r.json() if r.status_code == 200 else {}


async def _fetch_drawings_manifest(
    http: httpx.AsyncClient, user_id: str, work_id: str
) -> dict[str, Any]:
    r = await http.get(f"{CM_URL}/sessions/{user_id}/{work_id}/drawings/manifest", timeout=10)
    return r.json() if r.status_code == 200 else {}


async def _fetch_drawing_artifact(
    http: httpx.AsyncClient, user_id: str, work_id: str, drawing_id: str, kind: str
) -> dict[str, Any] | None:
    r = await http.get(
        f"{CM_URL}/sessions/{user_id}/{work_id}/drawings/{drawing_id}/{kind}",
        timeout=10,
    )
    return r.json() if r.status_code == 200 else None


async def _export_docx(http: httpx.AsyncClient, token: str, user_id: str, work_id: str) -> int:
    _ck = {"nx_access": token} if token else {}
    r = await http.post(
        f"{ACCOUNT_URL}/api/v1/works/{work_id}/output/draft",
        cookies=_ck,
        timeout=60,
    )
    if r.status_code != 200:
        _log(f"draft build status={r.status_code} body={r.text[:200]}")
        return 0

    g = await http.get(
        f"{ACCOUNT_URL}/api/v1/works/{work_id}/output/draft",
        cookies=_ck,
        timeout=30,
    )
    return len(g.content) if g.status_code == 200 else 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 실시간 stream viewer (cli.py 가 import)
# ---------------------------------------------------------------------------

from rich.console import Console  # noqa: E402  — late import (post-helper block, intentional)
from rich.rule import Rule  # noqa: E402

_console = Console()


def _short(s: str, n: int = 200) -> str:
    if not isinstance(s, str):
        s = str(s)
    s = s.replace("\n", " ")
    return s[:n] + ("…" if len(s) > n else "")


async def _fetch_rt(
    http: httpx.AsyncClient, user_id: str, work_id: str, chain_id: str, rt_id: str
) -> dict[str, Any]:
    r = await http.get(
        f"{CM_URL}/sessions/{user_id}/{work_id}/chains/{chain_id}/rts/{rt_id}",
        timeout=10,
    )
    return r.json() if r.status_code == 200 else {}


async def _fetch_trail_raw(
    http: httpx.AsyncClient, user_id: str, work_id: str, chain_id: str
) -> list[dict[str, Any]]:
    r = await http.get(
        f"{CM_URL}/sessions/{user_id}/{work_id}/chains/{chain_id}/trail",
        timeout=10,
    )
    if r.status_code != 200:
        return []
    out = []
    for line in (r.text or "").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _fmt_scalar(v: Any, max_len: int = 120) -> str:
    """primitive 값을 한 줄 문자열로."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "[green]true[/]" if v else "[red]false[/]"
    if isinstance(v, int | float):
        return f"[yellow]{v}[/]"
    s = str(v).replace("\n", " ⏎ ")
    return f"[green]{_short(s, max_len)}[/]"


def _fmt_list_item(item: Any, max_len: int = 100) -> str:
    """list 의 element 한 개를 한 줄로 (dict 면 핵심 필드 inline)."""
    if isinstance(item, dict):
        # 우선 보여줄 key 후보 (특허/도면/쿼리 등 도메인 친화)
        priority = (
            "application_number",
            "drawing_id",
            "claim_id",
            "id",
            "text",
            "title",
            "name",
            "query",
            "tool",
            "relevance_score",
            "type",
            "priority",
        )
        parts = []
        used = set()
        for k in priority:
            if k in item and item[k] is not None:
                parts.append(f"[cyan]{k}[/]={_fmt_scalar(item[k], 60)}")
                used.add(k)
                if len(parts) >= 4:
                    break
        if not parts:
            # 우선순위 hit 없으면 첫 3개 key
            for k, v in list(item.items())[:3]:
                parts.append(f"[cyan]{k}[/]={_fmt_scalar(v, 50)}")
                used.add(k)
        line = "  ".join(parts)
        extras = [k for k in item.keys() if k not in used]
        if extras:
            line += f"  [dim](+{len(extras)} more: {','.join(extras[:4])})[/]"
        return line
    return _fmt_scalar(item, max_len)


# 검색어/특허 list 같은 핵심 key 는 잘리지 않고 모두 출력 + 강조 박스로.
_FULL_LIST_KEYS = {
    "queries",
    "search_queries",
    "ranked_patents",
    "patents",
    "claim_elements",
    "drawings",
    "recommendations",
    "differentiation_points",
    "risk_factors",
    "additional_queries",
    "previous_queries",
    "covered_elements",
    "uncovered_elements",
    "technical_elements",
    "ipc_codes",
}


def _print_structured(d: dict, indent: str = "      ", max_list: int = 5) -> None:
    """structured LLM output 의 각 key 를 보기 좋게 출력. 핵심 key 는 전수 + 박스."""
    for k, v in d.items():
        if isinstance(v, list):
            n = len(v)
            if k in _FULL_LIST_KEYS and n > 0:
                # 핵심 list — 강조 박스로 전수 출력
                from rich.panel import Panel

                lines = [
                    f"[bold yellow]{i:>3}.[/] {_fmt_list_item(item, max_len=300)}"
                    for i, item in enumerate(v, 1)
                ]
                _console.print()
                _console.print(
                    Panel(
                        "\n".join(lines),
                        title=f"[bold yellow]{k}[/]  [dim](전수 × {n})[/]",
                        border_style="yellow",
                        padding=(0, 1),
                    )
                )
                continue
            _console.print(f"{indent}[bold cyan]{k}[/] [dim](list × {n})[/]:")
            for i, item in enumerate(v[:max_list], 1):
                _console.print(f"{indent}  [{i}] {_fmt_list_item(item)}")
            if n > max_list:
                _console.print(f"{indent}  [dim]… +{n - max_list} more[/]")
        elif isinstance(v, dict):
            inner = ", ".join(
                f"[cyan]{ik}[/]={_fmt_scalar(iv, 40)}" for ik, iv in list(v.items())[:5]
            )
            _console.print(f"{indent}[bold cyan]{k}[/]: {{ {inner} }}")
        else:
            _console.print(f"{indent}[bold cyan]{k}[/]: {_fmt_scalar(v, 200)}")


def _print_rt_step(step_idx: int, rt: dict, chain_id: str) -> None:
    """RT 본체 1개를 step block 으로 출력."""
    step_id = rt.get("step_id", "?")
    persona = rt.get("persona", "?")
    inp = rt.get("input") or {}
    out = rt.get("output") or {}
    rt_id = rt.get("rt_id") or ""
    prompt = _short(inp.get("prompt") or "", 200)
    sysp = _short(inp.get("system_prompt") or "", 160)
    structured = out.get("structured") if isinstance(out.get("structured"), dict) else None

    _console.print()
    _console.print(f"[bold cyan][Step {step_idx}][/] [bold]{step_id}[/] [dim]persona={persona}[/]")
    if prompt:
        _console.print(f"  ▸ prompt:        {prompt}")
    if sysp:
        _console.print(f"  ▸ system_prompt: {sysp}")
    if structured:
        _console.print("  ▸ [bold]output[/]:")
        _print_structured(structured, indent="      ")
    else:
        text = out.get("text") if isinstance(out, dict) else None
        if text:
            _console.print(f"  ▸ text:          {_short(text, 200)}")
    if rt_id:
        _console.print(f"  ▸ [dim]saved → chains/{chain_id[:8]}…/rts/{rt_id[:8]}….json[/]")


def _print_tool_call_header(step_idx: int, step_id: str, tool: str) -> None:
    """fan_out parallel_task 의 첫 호출 도착 시 한 번만 출력하는 step header."""
    _console.print()
    _console.print(f"[bold magenta][Step {step_idx}][/] [bold]{step_id}[/] [dim]tool={tool}[/]")


def _print_tool_call_started(evt: dict) -> None:
    """tool_call_started event — 호출 직전 params 강조 출력 (KIPRIS queries 등).

    KIPRIS 검색어는 simulator 의 가장 중요한 출력 — 압도적인 시각 강조로 표시.
    """
    tool = evt.get("tool", "?")
    params_summary = evt.get("params_summary") or {}
    queries = params_summary.get("queries")
    if isinstance(queries, dict) and queries.get("_full"):
        from rich.table import Table
        from rich.text import Text
        from rich.align import Align

        items = queries["_full"]
        n = len(items)

        # ─── 헤더: 압도적 강조 (큰 emoji + 두꺼운 ASCII rule) ────────────────
        _console.print()
        _console.print()
        rule_top = "━" * 78
        _console.print(f"[bold bright_red]{rule_top}[/]")
        _console.print(
            Align.center(
                Text(f"🔍🔍🔍  KIPRIS 검색어 × {n}  🔍🔍🔍", style="bold bright_yellow on red"),
                width=78,
            )
        )
        _console.print(
            Align.center(
                Text(f"tool = {tool}", style="bold white"),
                width=78,
            )
        )
        _console.print(f"[bold bright_red]{rule_top}[/]")
        _console.print()

        # ─── 표 형태 — 각 query 가 한 행, 검색어 본문은 형광 노란색 큰 글자 ──
        table = Table(
            show_header=True,
            header_style="bold bright_white on dark_red",
            border_style="bright_yellow",
            expand=True,
            padding=(0, 1),
            show_lines=True,  # 각 행 분리선
        )
        table.add_column("#", style="bold bright_yellow", justify="right", width=4)
        table.add_column(
            "검색어 (KIPRIS 에 전달되는 본문)",
            style="bold black on bright_yellow",
            no_wrap=False,
            ratio=3,
        )
        table.add_column("type", style="bright_cyan", width=11)
        table.add_column("prio", style="bright_magenta", justify="center", width=5)
        table.add_column("target_element", style="dim white", ratio=2)

        for i, q in enumerate(items, 1):
            if isinstance(q, dict):
                qtext = str(q.get("query") or q.get("text") or "")
                qtype = str(q.get("type") or "")
                prio = str(q.get("priority") or "")
                target = str(q.get("target_element") or q.get("ipc_hint") or "")
                table.add_row(str(i), f" {qtext} ", qtype, prio, target)
            else:
                table.add_row(str(i), f" {q} ", "", "", "")

        _console.print(table)
        _console.print(f"[bold bright_red]{rule_top}[/]")
        _console.print()
    elif params_summary:
        # 단순 dict — 첫 줄로
        kv = ", ".join(
            f"[cyan]{k}[/]={v}"
            for k, v in list(params_summary.items())[:5]
            if not isinstance(v, dict)
        )
        if kv:
            _console.print(f"      [dim]params:[/] {kv}")
    # 디버그 정보 (substitute_placeholders 결과 추적)
    debug = evt.get("_debug")
    if debug:
        ps = debug.get("params_spec")
        if ps:
            _console.print(f"      [dim]params_spec:[/] {ps}")
        keys = debug.get("ctx_steps_keys")
        if keys is not None:
            _console.print(f"      [dim]ctx.steps.keys:[/] {keys}")


def _print_tool_call_body(evt: dict, sub_idx: int) -> None:
    """tool_call_done event 의 summary 만 indent 로 출력 (header 없이)."""
    summary = evt.get("summary") or {}
    prefix = f"  ({sub_idx})" if sub_idx > 0 else "      "
    if "query" in summary:
        cnt = summary.get("patents_count")
        cnt_part = f"  → [green]{cnt}[/] 건" if cnt is not None else ""
        _console.print(f"{prefix} query: [green]{summary['query']}[/]{cnt_part}")
        for i, p in enumerate(summary.get("patents_preview", []), 1):
            _console.print(
                f"          [{i}] [cyan]{p.get('application_number')}[/]  {p.get('title', '')}"
            )
    elif "patents_count" in summary:
        _console.print(f"{prefix} patents: [green]{summary['patents_count']}[/] 건")
    if "figure_bytes" in summary:
        _console.print(
            f"{prefix} figure: [green]{summary['figure_bytes']}B[/] SVG  tool={summary.get('chosen_tool')}"
        )
    if "overall_pass" in summary:
        op = summary["overall_pass"]
        _console.print(f"{prefix} review: overall_pass=[{'green' if op else 'red'}]{op}[/]")


async def _render_final_artifacts(
    http: httpx.AsyncClient,
    user_id: str,
    work_id: str,
    chain_id: str,
    pipeline_id: str,
    chain: dict,
    events: list[dict],
    token: str,
) -> dict[str, Any]:
    """chain done 후 trail/IOM/drawings/contexts/docx 최종 출력. 검증 결과 반환."""
    _console.print()
    _console.print(Rule("[bold]final artifacts[/]"))

    # chain manifest
    status = chain.get("status", "?")
    color = "green" if status == "done" else "red"
    _console.print(f"  ✓ chain manifest:   status=[{color}]{status}[/]")

    # trail summary
    trail = await _fetch_trail_raw(http, user_id, work_id, chain_id)
    evt_count: dict[str, int] = {}
    for e in trail:
        et = e.get("event", "?")
        evt_count[et] = evt_count.get(et, 0) + 1
    _console.print(f"  ✓ trail events:     {len(trail)}  {dict(sorted(evt_count.items()))}")

    # tool_call summary — summary.query / patents_count / figure_bytes / overall_pass
    # 가 있으면 함께 표시해서 "뭘 검색했고 몇 건 나왔는지" 한눈에 보이게.
    tool_calls = [
        e
        for e in trail
        if e.get("event") in ("tool_call_started", "tool_call_done", "tool_call_failed")
    ]
    if tool_calls:
        done = [e for e in tool_calls if e.get("event") == "tool_call_done"]
        _console.print(f"  ✓ tool calls:       {len(done)}")
        for e in done[:30]:
            summ = e.get("summary") or {}
            extras: list[str] = []
            if "query" in summ:
                cnt = summ.get("patents_count")
                cnt_s = f"  patents=[green]{cnt}[/]" if cnt is not None else ""
                extras.append(f"query=[green]{summ['query']}[/]{cnt_s}")
            if "figure_bytes" in summ:
                extras.append(
                    f"figure=[green]{summ['figure_bytes']}B[/] tool={summ.get('chosen_tool')}"
                )
            if "overall_pass" in summ:
                op = summ["overall_pass"]
                extras.append(f"overall_pass=[{'green' if op else 'red'}]{op}[/]")
            tail = ("  " + "  ".join(extras)) if extras else ""
            _console.print(
                f"      [green]✓[/] [cyan]{e.get('tool')}[/]  step_id={e.get('step_id')}  "
                f"status={e.get('status')}{tail}"
            )
        if len(done) > 30:
            _console.print(f"      [dim]… +{len(done) - 30} more[/]")

    # IOM
    iom = await _fetch_iom(http, user_id, work_id)
    claims = (iom or {}).get("claims") or []
    iom_marker = "✓" if claims else "─"
    _console.print(
        f"  {iom_marker} IOM.claims:       {len(claims)} {'(' + pipeline_id + ' 시나리오라 정상)' if not claims else ''}"
    )

    # drawings
    manifest = await _fetch_drawings_manifest(http, user_id, work_id)
    drawings = (manifest or {}).get("drawings") or []
    dr_marker = "✓" if drawings else "─"
    _console.print(f"  {dr_marker} drawings:         {len(drawings)}")
    for d in drawings:
        did = d.get("drawing_id") or "?"
        numerals = await _fetch_drawing_artifact(http, user_id, work_id, did, "numerals")
        dl = await _fetch_drawing_artifact(http, user_id, work_id, did, "dl")
        figure = await _fetch_drawing_artifact(http, user_id, work_id, did, "figure")
        n_ok = "✓" if numerals else "✗"
        dl_ok = "✓" if dl else "✗"
        fig_ok = "✓" if figure else "✗"
        size = 0
        if figure:
            import base64 as _b64

            try:
                size = len(
                    _b64.b64decode(figure.get("data_b64") or figure.get("figure_bytes_b64") or "")
                )
            except Exception:
                size = 0
        _console.print(f"      [{did}] numerals={n_ok} dl={dl_ok} figure={fig_ok}  SVG={size}B")

    # docx export 시도 — IOM 의 claims 가 충분히 있으면 의미 있음 (P02 가 IOM 채운 시나리오).
    # pipeline_id hardcode special-case 폐기 — chain 결과의 IOM 상태로 자동 판단.
    docx_size = 0
    if len(claims) >= 1:
        try:
            docx_size = await _export_docx(http, token, user_id, work_id)
            _console.print(f"  ✓ docx export:      {docx_size} bytes")
        except Exception as e:
            _console.print(f"  [dim](docx export skip — {e})[/]")

    return {
        "status": status,
        "claims": len(claims),
        "drawings": len(drawings),
        "docx_size": docx_size,
        "tool_calls": len(tool_calls) // 2 if tool_calls else 0,  # started+done 쌍
    }
