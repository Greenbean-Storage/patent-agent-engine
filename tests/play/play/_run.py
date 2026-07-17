"""play track 의 pipeline 실행 **로직** — run_pipeline + chain follow loop + spawned BFS + 검증 주도.

probe 를 **CM-하네스**로 사용한다. setup(token/session/seed/trigger)·fetch·print·verify 의
primitive 는 probe(`probe._pipeline` + `probe.commands.check`)에서 import 하고, play 가 소유하는 것은
"로직": setup 시퀀스 · trail.jsonl follow loop · dispatch graph BFS · 검증 호출 · summary/판정.

(historical: 이 로직은 과거 `probe._pipeline.run_pipeline` 에 잘못 들어가 있었고 play 가 그걸
 import 했다. CHUNK 2 에서 로직만 play 로 이관 — probe 는 하네스로 유지.)
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

import httpx
from rich.rule import Rule

import probe._pipeline as _ph  # URL override 대상 (probe 의 fetch primitive 가 읽는 모듈 전역)
from venezia_contracts import ContractLoader

from play._sse import SseCapture, consume_raw_sse, drain_sse, report_sse

# raw_asserts ② — 완료된 RT 의 output(= Actor /dispatch SSE result) 을 계약에 고정 (5-1·5-2
# drift guard; ① 은 _sse.py 의 raw-sse-event). shape 는 FIXTURE/PRODUCTION/mock 불변 — mode 무관.
_contracts = ContractLoader()
_DISPATCH_RESULT = "dispatch-result"
from probe._pipeline import (
    _console,
    _create_session,
    _dev_token,
    _fetch_rt,
    _fetch_trail_raw,
    _print_rt_step,
    _print_tool_call_body,
    _print_tool_call_header,
    _print_tool_call_started,
    _render_final_artifacts,
    _seed_iom,
    _trigger_pipeline,
)


def detect_stack_mode() -> str:
    """현 stack 의 LLM 모드 — `@deployment/profile.stack.yaml`(DEPLOYMENT_FILE) 직접 read.

    profile `llm: fake` → FIXTURE, `real` → PRODUCTION. host 도구는 Makefile 이 DEPLOYMENT_FILE
    설정(스택이 그 profile 로 기동되므로 결과 동등). 파일 부재 시 venezia_deployment fallback=PRODUCTION.
    """
    from venezia_deployment.runtime import llm  # noqa: PLC0415

    return llm()  # "FIXTURE" | "PRODUCTION"


async def _stream_trail_with_step_printer(
    http: httpx.AsyncClient,
    user_id: str,
    work_id: str,
    chain_id: str,
    stop: asyncio.Event,
    timeout: float,
    counters: dict[str, int],
    violations: list[str],
) -> None:
    """trail.jsonl 폴링하면서 새 event 가 도착할 때마다 step block 출력.

    WS 의존 없음 — director 가 trigger 한 pipeline 도 그대로 stream 됨.
    """
    seen_rt_ids: set[str] = set()
    seen_tool_evts: set[str] = set()  # (step_id, tool, ts) 로 unique
    step_idx = 0
    # 같은 step_id 의 fan_out tool 호출은 하나의 step block 으로 묶음
    current_tool_step_id: str | None = None
    current_tool_sub_idx = 0
    deadline = asyncio.get_event_loop().time() + timeout

    while not stop.is_set():
        if asyncio.get_event_loop().time() > deadline:
            break
        trail = await _fetch_trail_raw(http, user_id, work_id, chain_id)

        for e in trail:
            evt = e.get("event") or ""
            # 1) LLM RT 완료
            if evt == "rt_completed":
                rt_id = e.get("rt_id")
                if not rt_id or rt_id in seen_rt_ids:
                    continue
                seen_rt_ids.add(rt_id)
                rt = await _fetch_rt(http, user_id, work_id, chain_id, rt_id)
                if rt:
                    if rt.get("step_type") == "tool_task":
                        # tool RT — tool_call_* 핸들러가 표시·검증 담당. output shape 은
                        # dispatch-result(LLM) 계약과 별개라 여기서 검사 안 함 (tool=RT 통일, N-7).
                        continue
                    step_idx += 1
                    counters["llm_steps"] = counters.get("llm_steps", 0) + 1
                    # raw_asserts ② — 완료된 RT.output 을 dispatch-result 계약으로 검사.
                    counters["dispatch_results"] = counters.get("dispatch_results", 0) + 1
                    result = _contracts.validate(_DISPATCH_RESULT, rt.get("output"))
                    if not result:
                        violations.append(
                            f"{chain_id[:8]}…/{rt_id[:8]}…: " + "; ".join(result.errors)[:200]
                        )
                    _print_rt_step(step_idx, rt, chain_id)
                    current_tool_step_id = None  # LLM step 사이에 끼면 묶음 끊기
            # 2a) Tool 호출 시작 — params (queries 등) 강조
            elif evt == "tool_call_started":
                key = f"start|{e.get('step_id')}|{e.get('tool')}|{e.get('ts')}"
                if key in seen_tool_evts:
                    continue
                seen_tool_evts.add(key)
                step_id = e.get("step_id") or "?"
                tool = e.get("tool", "?")
                if step_id != current_tool_step_id:
                    step_idx += 1
                    current_tool_step_id = step_id
                    current_tool_sub_idx = 0
                    _print_tool_call_header(step_idx, step_id, tool)
                _print_tool_call_started(e)
            # 2b) Tool 호출 완료 — 같은 step_id 면 같은 Step block 으로 묶음
            elif evt == "tool_call_done":
                key = f"{e.get('step_id')}|{e.get('tool')}|{e.get('ts')}"
                if key in seen_tool_evts:
                    continue
                seen_tool_evts.add(key)
                step_id = e.get("step_id") or "?"
                tool = e.get("tool", "?")
                counters["tool_steps"] = counters.get("tool_steps", 0) + 1
                if step_id != current_tool_step_id:
                    step_idx += 1
                    current_tool_step_id = step_id
                    current_tool_sub_idx = 0
                    _print_tool_call_header(step_idx, step_id, tool)
                else:
                    current_tool_sub_idx += 1
                _print_tool_call_body(e, current_tool_sub_idx)
            # 3) chain 종료
            elif evt == "chain_completed":
                _console.print()
                _console.print("[bold green]✓ chain_completed[/]")
                stop.set()
                return

        await asyncio.sleep(0.5)


async def _poll_chain_done(
    http: httpx.AsyncClient,
    user_id: str,
    work_id: str,
    chain_id: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = await http.get(
            f"{_ph.CM_URL}/sessions/{user_id}/{work_id}/chains/{chain_id}", timeout=10
        )
        if r.status_code == 200:
            ch = r.json()
            if ch.get("status") in ("done", "failed"):
                return ch
        await asyncio.sleep(1.0)
    return {"status": "timeout"}


async def run_pipeline(
    pipeline_id: str,
    dro_url: str | None = None,
    cm_url: str | None = None,
    fixture_mode: bool = True,
    ws_timeout: float = 180.0,
    seed_iom_path: Path | None = None,
    verbose: bool = False,
) -> int:
    """Pipeline e2e 실시간 viewer — cli.py 에서 호출."""
    if dro_url:
        _ph.DRO_URL = dro_url
    if cm_url:
        _ph.CM_URL = cm_url

    _console.print()
    _console.print(
        Rule(
            f"[bold cyan]SIMULATOR  pipeline={pipeline_id}  mode={'fixture' if fixture_mode else 'echo'}[/]"
        )
    )

    started = time.monotonic()

    async with httpx.AsyncClient(timeout=30.0) as http:
        _console.print()
        _console.print("[bold]setup[/]")
        try:
            token, user_id = await _dev_token(http)
            _console.print(f"  ✓ dev-token user={user_id}")
        except Exception as e:
            _console.print(f"  [red]✗ dev-token: {e}[/]")
            return 2
        try:
            work_id = await _create_session(http, token)
            _console.print(f"  ✓ session invention={work_id[:8]}…")
        except Exception as e:
            _console.print(f"  [red]✗ session: {e}[/]")
            return 2
        # DRO RAW SSE 구독 — replay buffer 없음 → trigger **전** 시작 (dual 관측 ②, 3i/3j).
        cap = SseCapture()
        sse_task = asyncio.create_task(consume_raw_sse(_ph.DRO_URL, user_id, work_id, cap))
        try:
            try:
                await asyncio.wait_for(cap.connected.wait(), timeout=10)
                await asyncio.sleep(0.3)  # settle — 구독 등록(generator 첫 iteration) 완충
                _console.print("  ✓ raw SSE subscribed (DRO /events)")
            except TimeoutError:
                _console.print(f"  [red]✗ raw SSE connect 실패: {cap.exc or 'timeout'}[/]")
                return 2

            if seed_iom_path:
                await _seed_iom(http, user_id, work_id, seed_iom_path)
                _console.print(f"  ✓ seed IOM from {seed_iom_path}")

            # trigger
            try:
                chain_id = await _trigger_pipeline(http, token, user_id, work_id, pipeline_id)
                _console.print(
                    f"  ✓ chain queued chain_id={chain_id[:8]}…  pipeline=[bold]{pipeline_id}[/]"
                )
            except Exception as e:
                _console.print(f"  [red]✗ trigger: {e}[/]")
                return 2

            _console.print()
            _console.print(Rule("[bold]progress[/]  [dim](trail.jsonl polling + raw SSE)[/]"))

            # trail polling 으로 stream (WS 의존 없음 — director-trigger chain 도 그대로 동작)
            stop = asyncio.Event()
            counters: dict[str, int] = {"llm_steps": 0, "tool_steps": 0}
            violations: list[str] = []  # raw_asserts ② — dispatch result 계약 위반 수집
            stream_task = asyncio.create_task(
                _stream_trail_with_step_printer(
                    http,
                    user_id,
                    work_id,
                    chain_id,
                    stop,
                    ws_timeout,
                    counters,
                    violations,
                )
            )

            # chain done 폴링 (root)
            chain = await _poll_chain_done(http, user_id, work_id, chain_id, ws_timeout)
            stop.set()
            try:
                await asyncio.wait_for(stream_task, timeout=3)
            except Exception:
                stream_task.cancel()

            # spawned chain BFS 추적 — chain_dispatched trail event 따라가 descendants 모두 watch.
            MAX_CHAINS = 30
            all_chains: list[tuple[str, dict]] = [(chain_id, chain)]
            seen = {chain_id}

            async def _discover_spawned(parent_chain_id: str) -> list[str]:
                """parent chain 의 trail 에서 chain_dispatched event 의 next_chain_id 수집."""
                spawned = []
                try:
                    trail = await _fetch_trail_raw(http, user_id, work_id, parent_chain_id)
                    for evt in trail:
                        if evt.get("event") == "chain_dispatched":
                            nid = evt.get("next_chain_id")
                            if nid and nid not in seen:
                                seen.add(nid)
                                spawned.append(nid)
                except Exception:
                    pass
                return spawned

            # BFS queue 시작
            queue: list[str] = await _discover_spawned(chain_id)
            while queue and len(all_chains) < MAX_CHAINS:
                next_id = queue.pop(0)
                _console.print()
                _console.print(Rule(f"[bold magenta]spawned chain  {next_id[:8]}…[/]"))

                sub_stop = asyncio.Event()
                sub_task = asyncio.create_task(
                    _stream_trail_with_step_printer(
                        http,
                        user_id,
                        work_id,
                        next_id,
                        sub_stop,
                        ws_timeout,
                        counters,
                        violations,
                    )
                )
                sub_chain = await _poll_chain_done(http, user_id, work_id, next_id, ws_timeout)
                sub_stop.set()
                try:
                    await asyncio.wait_for(sub_task, timeout=3)
                except Exception:
                    sub_task.cancel()
                all_chains.append((next_id, sub_chain))

                # 이 spawned chain 에서 또 spawn 됐는지 추가 발견
                further = await _discover_spawned(next_id)
                queue.extend(further)

            if len(all_chains) >= MAX_CHAINS:
                _console.print(
                    f"[yellow]⚠ MAX_CHAINS={MAX_CHAINS} 도달 — 더 spawn 된 chain 무시[/]"
                )

            # SSE drain — CM status:done patch 가 chain_completed emit 보다 선행하므로
            # 전 chain 의 종료 이벤트 도착을 잠시 기다린 뒤 구독 종료.
            await drain_sse(cap, len(all_chains))
        finally:
            if not sse_task.done():
                sse_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sse_task

        # 최종 출력 (root chain 기준)
        await _render_final_artifacts(
            http,
            user_id,
            work_id,
            chain_id,
            pipeline_id,
            chain,
            [],
            token,
        )

        # summary
        elapsed = int(time.monotonic() - started)
        _console.print()
        _console.print(Rule("[bold]summary[/]"))
        _console.print(f"  Total time      : [bold]{elapsed}s[/]")
        _console.print(f"  Chains traced   : {len(all_chains)}")
        _console.print(f"  LLM steps       : {counters.get('llm_steps', 0)}")
        _console.print(f"  Tool calls      : {counters.get('tool_steps', 0)}")

        # PASS/FAIL 판정 — 모든 chain 이 done 이어야
        ok = all(c.get("status") == "done" for _, c in all_chains)
        failed_chains = [cid for cid, c in all_chains if c.get("status") != "done"]
        if failed_chains:
            _console.print(f"  [red]failed chains : {failed_chains}[/]")

        # dual 관측 ② — raw SSE 자동 assert (schema 전건 + seq 단조 + ≥1건 + 무예외).
        # fixture_mode 게이트 없음 — full-real·actor:fake 동일 코드 (3j).
        _console.print()
        _console.print(Rule("[bold]raw SSE[/]  [dim](DRO /events, schema=raw-sse-event)[/]"))
        if not report_sse(cap, len(all_chains), _console):
            ok = False

        # raw_asserts ② — dispatch result (완료 RT.output) 계약 검사 결과 (5-1·5-2 drift guard).
        n_results = counters.get("dispatch_results", 0)
        if violations:
            _console.print(
                f"  [red]✗ dispatch result: 계약 위반 {len(violations)}건 (schema=dispatch-result)[/]"
            )
            for v in violations[:5]:
                _console.print(f"      [red]{v}[/]")
            ok = False
        else:
            _console.print(
                f"  [green]✓ dispatch result: {n_results}건 전건 schema 통과[/] [dim](schema=dispatch-result)[/]"
            )

        # C1 — deterministic invariants. 모든 chain 검증. (pipeline-specific 검증은 폐기 —
        # 검증은 verify_chain 의 일반 invariants 와 chain status 만 사용.)
        if fixture_mode:
            from probe.commands.check import print_report, verify_chain  # noqa: PLC0415

            for cid, _c in all_chains:
                report = await verify_chain(user_id, work_id, cid, cm_url=_ph.CM_URL)
                print_report(report)
                if report.has_failures:
                    ok = False

        result_color = "green" if ok else "red"
        result_text = "PASS" if ok else "FAIL"
        _console.print(f"  RESULT          : [{result_color} bold]{result_text}[/]")
        _console.print()

        return 0 if ok else 1
