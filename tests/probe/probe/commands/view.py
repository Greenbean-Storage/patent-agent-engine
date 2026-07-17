"""Read-only chain viewer — 기존 chain_id 의 trail + RT + artifacts 재구성.

호출자: `simulator/cli.py:cmd_viewer` → `run_viewer(chain_id, ...)`
WS stream 없이 CM 의 chain 자산만 fetch 해서 step 순서대로 출력.
"""

from __future__ import annotations


import httpx
from rich.console import Console
from rich.rule import Rule

from .. import _pipeline as pipeline_mod

_console = Console()


async def _find_invention_for_chain(
    http: httpx.AsyncClient,
    cm_url: str,
    user_id: str,
    chain_id: str,
) -> str | None:
    """CM 의 sessions/{user_id} 목록을 훑어서 chain_id 가 속한 work_id 찾기.

    각 invention 의 chains list endpoint (lightweight) 호출 → chain_id 매칭. 최대 50개.
    그 이상 누적 시 사용자가 `INVENTION_ID=<id>` 명시 권장.
    """
    try:
        r = await http.get(f"{cm_url}/sessions/{user_id}", timeout=5)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    body = r.json() or {}
    invs = body.get("inventions") or []
    # 최근 50개부터 (역순 — 최근 생성된 invention 이 chain 가질 가능성 높음)
    for inv in reversed(invs[-50:]):
        iid = inv.get("work_id")
        if not iid:
            continue
        try:
            cr = await http.get(
                f"{cm_url}/sessions/{user_id}/{iid}/chains",
                timeout=2,
            )
        except Exception:
            continue
        if cr.status_code != 200:
            continue
        chains = (cr.json() or {}).get("chains") or []
        for c in chains:
            if c.get("chain_id") == chain_id:
                return iid
    return None


async def run_viewer(
    chain_id: str,
    user_id: str,
    work_id: str | None,
    cm_url: str,
    verbose: bool = False,
) -> int:
    pipeline_mod.CM_URL = cm_url

    _console.print()
    _console.print(Rule(f"[bold cyan]SIMULATOR viewer  chain={chain_id[:12]}…[/]"))

    async with httpx.AsyncClient(timeout=30.0) as http:
        if work_id is None:
            _console.print("  [dim]work_id 미지정 → CM 에서 lookup 중…[/]")
            work_id = await _find_invention_for_chain(http, cm_url, user_id, chain_id)
            if not work_id:
                _console.print(
                    f"  [red]✗ chain {chain_id} 의 invention 못 찾음 (user={user_id})[/]"
                )
                return 2
            _console.print(f"  ✓ work_id={work_id}")

        # chain manifest
        r = await http.get(
            f"{cm_url}/sessions/{user_id}/{work_id}/chains/{chain_id}",
            timeout=10,
        )
        if r.status_code != 200:
            _console.print(f"  [red]✗ chain manifest GET {r.status_code}[/]")
            return 2
        chain = r.json() or {}
        status = chain.get("status", "?")
        pipeline_id = chain.get("pipeline_id", "?")
        _console.print(f"  ✓ pipeline={pipeline_id}  status={status}")

        # trail 전체
        _console.print()
        _console.print(Rule("[bold]trail events[/]"))
        trail = await pipeline_mod._fetch_trail_raw(http, user_id, work_id, chain_id)
        if not trail:
            _console.print("  [yellow]trail 비어있음[/]")
        for e in trail:
            ts = (e.get("ts") or "")[11:19]
            evt = e.get("event") or "?"
            step_id = e.get("step_id") or ""
            tool = e.get("tool") or ""
            extra = ""
            if evt in ("tool_call_started", "tool_call_done", "tool_call_failed"):
                extra = f"  tool=[cyan]{tool}[/]  status={e.get('status', '')}"
            elif evt == "next_conditional_jump":
                extra = f"  {e.get('from')} → {e.get('to')}"
            elif evt == "parallel_done":
                extra = f"  keys={e.get('result_keys')}"
            elif evt == "branch_evaluated":
                extra = f"  expanded={e.get('expanded')}"
            _console.print(f"  [dim]{ts}[/]  {evt:<25}  [bold]{step_id}[/]{extra}")

        # RT 목록 + 핵심 출력
        _console.print()
        _console.print(Rule("[bold]RT outputs[/]"))
        # CM 의 rts list 가 별도 endpoint 없음 — trail 의 rt_enqueued/completed 에서 rt_id 추출
        rt_ids: list[str] = []
        for e in trail:
            rid = e.get("rt_id")
            if rid and rid not in rt_ids:
                rt_ids.append(rid)
        for idx, rt_id in enumerate(rt_ids, 1):
            rt = await pipeline_mod._fetch_rt(http, user_id, work_id, chain_id, rt_id)
            if not rt:
                continue
            sid = rt.get("step_id", "?")
            persona = rt.get("persona", "?")
            inp = rt.get("input") or {}
            out = rt.get("output") or {}
            structured = out.get("structured") if isinstance(out.get("structured"), dict) else None

            _console.print()
            _console.print(
                f"[bold cyan][RT {idx}][/] [bold]{sid}[/]  [dim]persona={persona} rt_id={rt_id[:8]}…[/]"
            )
            prompt = pipeline_mod._short(inp.get("prompt") or "", 180)
            if prompt:
                _console.print(f"  ▸ prompt:        {prompt}")
            if structured:
                keys = list(structured.keys())
                _console.print(f"  ▸ output keys:   {keys[:10]}")
                if verbose:
                    import json as _json

                    _console.print(
                        f"  ▸ output (full): {_json.dumps(structured, ensure_ascii=False)[:600]}"
                    )
            else:
                text = out.get("text") if isinstance(out, dict) else None
                if text:
                    _console.print(f"  ▸ text:          {pipeline_mod._short(text, 180)}")

        # 최종 artifacts (IOM/drawings/docx)
        _console.print()
        _console.print(Rule("[bold]artifacts[/]"))
        iom = await pipeline_mod._fetch_iom(http, user_id, work_id)
        manifest = await pipeline_mod._fetch_drawings_manifest(http, user_id, work_id)
        claims = (iom or {}).get("claims") or []
        drawings = (manifest or {}).get("drawings") or []
        _console.print(f"  IOM.claims:       {len(claims)}")
        _console.print(f"  drawings:         {len(drawings)}")
        for d in drawings:
            did = d.get("drawing_id") or "?"
            title = d.get("title", "")
            _console.print(f"      [{did}] {title}")

        return 0 if status == "done" else 1
