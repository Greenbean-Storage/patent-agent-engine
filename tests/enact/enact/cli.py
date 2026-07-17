"""enact CLI — 모드 자동 판별 (B4 판별 체인).

  uv run python -m enact                          # 시나리오 전수 + 집계 (게이트)
  uv run python -m enact dispatch                 # 시나리오 단일
  uv run python -m enact P01.R00 0                # pipeline 단건 (positional: P정규식 → step)
  uv run python -m enact my-rt.yaml               # ad-hoc spec 파일
  uv run python -m enact --persona 2 --prompt "…" # ad-hoc 인라인 (spec 설탕)

exit 규약: 0 = green · 1 = 검증 FAIL · 2 = 사용법/환경.
시나리오 모드는 Actor /health 의 llm_mode==FIXTURE 가드 (단건 모드는 표기만).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from enact import _invariants as inv
from enact._harness import (
    Harness,
    load_spec,
    new_chain_id,
    new_work_id,
    synthesize_adhoc_rt,
    synthesize_rt,
)
from enact.scenarios import ALL_SCENARIOS, ScenarioOutcome
from enact.scenarios import concurrency as sc_concurrency
from enact.scenarios import context as sc_context
from enact.scenarios import dispatch as sc_dispatch
from enact.scenarios import errors as sc_errors
from enact.scenarios import tool as sc_tool

_P_RE = re.compile(r"^P\d{2}\.R\d{2}($|\.)")
_RUNNERS = {
    "dispatch": sc_dispatch.run,
    "context": sc_context.run,
    "tool": sc_tool.run,
    "concurrency": sc_concurrency.run,
    "errors": sc_errors.run,
}
_BAR = "=" * 60


def _print_header(title: str) -> None:
    print(f"\n{_BAR}\n  {title}\n{_BAR}", flush=True)


async def _health_or_exit(h: Harness) -> dict[str, Any]:
    try:
        return await h.actor_health()
    except (httpx.HTTPError, OSError) as exc:
        print(f"[enact] Actor /health 접근 실패 — 스택 부재? (`make up`) : {exc}", flush=True)
        raise SystemExit(2) from exc


# ─────────────────────────────────────────────────────────────────────────────
# 시나리오 모드 (게이트 — B2)
# ─────────────────────────────────────────────────────────────────────────────


async def _run_scenarios(names: list[str], timeout: float) -> int:
    h = Harness(timeout_s=timeout)
    try:
        health = await _health_or_exit(h)
        llm_mode = str(health.get("llm_mode", "?"))
        if llm_mode != "FIXTURE":
            print(
                f"[enact] llm_mode={llm_mode} — 시나리오는 llm:fake 스택 전제 "
                "(`make deploy set llm fake && make up`)",
                flush=True,
            )
            return 2

        print(f"[enact] llm_mode={llm_mode} — 시나리오 {len(names)} 실행", flush=True)

        outcomes: list[ScenarioOutcome] = []
        for name in names:
            _print_header(f"scenario: {name}")
            # out 을 cli 가 만들어 주입 — 시나리오가 work_id 를 세팅한 뒤 예외가 나도
            # 그 네임스페이스를 잃지 않음 (FAIL 보존 안내·후속 cleanup 가능).
            out = ScenarioOutcome(name=name)
            try:
                await _RUNNERS[name](h, llm_mode, out)
            except Exception as exc:  # noqa: BLE001 — 시나리오 예외 = crash 아닌 FATAL FAIL
                if not out.fatal:
                    out.fatal = f"{type(exc).__name__}: {exc}"
            if out.fatal:
                print(f"  ✗ FATAL: {out.fatal}", flush=True)
            inv.print_checks(out.checks)
            if not out.passed:
                ns = (
                    f"work={out.work_id} (probe view 로 조사)"
                    if out.work_id
                    else "(네임스페이스 없음)"
                )
                print(f"  → 보존: {ns}", flush=True)
            outcomes.append(out)

        _print_header(f"enact 집계 ({len(names)} 시나리오)")
        for out in outcomes:
            print(f"  {'PASS' if out.passed else 'FAIL'}  {out.name}", flush=True)
        print(_BAR, flush=True)

        failed = [o for o in outcomes if not o.passed]
        if failed:
            print(f"  RESULT : FAIL — {len(failed)}/{len(names)} 시나리오 실패", flush=True)
            return 1
        print(f"  RESULT : PASS — {len(names)} 시나리오 green", flush=True)
        return 0
    finally:
        await h.close()


# ─────────────────────────────────────────────────────────────────────────────
# 단건 수행 모드 (B4 — pipeline RT / ad-hoc. 관측 도구 — 게이트 무관)
# ─────────────────────────────────────────────────────────────────────────────


def _summarize(value: Any, limit: int = 200) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + f"… ({len(text)} chars)"


async def _run_single(rt: dict[str, Any], pipeline_id: str, timeout: float) -> int:
    h = Harness(timeout_s=timeout)
    try:
        health = await _health_or_exit(h)
        llm_mode = str(health.get("llm_mode", "?"))
        work_id = new_work_id()
        persona = int(rt["persona"])
        chain_id = str(rt["chain_id"])

        _print_header(f"enact 단건 — {pipeline_id} step={rt['step_id']} persona={persona}")
        print(f"  llm_mode={llm_mode}  work={work_id}  chain={chain_id}  rt={rt['rt_id']}")
        schema = (rt.get("input") or {}).get("response_schema")
        print(
            f"  response_schema={'있음' if schema else '없음'}  "
            f"tools={ (rt.get('input') or {}).get('available_tools') }",
            flush=True,
        )

        await h.create_chain(work_id, persona, chain_id, pipeline_id)
        await h.create_rt(work_id, persona, chain_id, rt)
        res = await h.dispatch(work_id, persona, chain_id, rt["rt_id"])

        if res.busy:
            print("  ✗ 503 busy (persona 슬롯 포화) — Retry-After 후 재시도 요망", flush=True)
            return 1
        if res.status_code >= 400:
            print(f"  ✗ dispatch HTTP {res.status_code}: {res.error}", flush=True)
            return 1

        print(f"\n  SSE events ({len(res.events)}):", flush=True)
        for evt in res.events:
            data = evt.get("data") or {}
            if evt["type"] == "result":
                print(f"    result  text={_summarize(data.get('text', ''))}")
                if data.get("structured") is not None:
                    print(f"            structured={_summarize(data.get('structured'))}")
            elif evt["type"] == "error":
                print(f"    error   {_summarize(data)}")
            else:
                print(f"    {evt['type']:<7} {_summarize(data, 120)}")

        checks = inv.check_sse_sequence(res.events, rt["rt_id"])
        final_rt = await h.get_rt(work_id, persona, chain_id, rt["rt_id"])
        checks += inv.check_rt_done(final_rt)
        checks.append(inv.check_structured_contract(final_rt))
        state = await h.get_agent_state(work_id, persona, chain_id)
        checks += inv.check_envelope(state, llm_mode=llm_mode)
        trail = await h.get_trail(work_id, persona, chain_id)
        checks.append(inv.check_trail(trail, expect_llm_input_prepared=1))

        print("\n  불변식:", flush=True)
        inv.print_checks(checks)

        ok = all(c.ok for c in checks)
        if ok:
            await h.cleanup(work_id)
            print("\n  RESULT : PASS (네임스페이스 정리됨)", flush=True)
            return 0
        print(
            f"\n  RESULT : FAIL — 네임스페이스 보존: work={work_id} (probe view 로 조사)",
            flush=True,
        )
        return 1
    finally:
        await h.close()


# ─────────────────────────────────────────────────────────────────────────────
# entry — 판별 체인 (P5: P 정규식이 경로 판별보다 먼저)
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="enact", add_help=True)
    parser.add_argument("positional", nargs="*", help="시나리오명 | P{NN}.R{NN} [step] | spec 경로")
    parser.add_argument("--persona", type=int, help="ad-hoc 인라인: persona (1~6)")
    parser.add_argument("--prompt", help="ad-hoc 인라인: 프롬프트 (instructions.inline 설탕)")
    parser.add_argument("--spec", help="ad-hoc spec 파일 (YAML/JSON)")
    parser.add_argument("--timeout", type=float, default=None, help="dispatch timeout 초")
    args = parser.parse_args(argv)
    pos = list(args.positional)

    # Makefile VAR 는 셸 인젝션 방지를 위해 ENACT_* env 로 전달됨 (export — 셸 재파싱 없음).
    # CLI 플래그가 우선, 없으면 env fallback.
    env = os.environ
    if args.prompt is None and env.get("ENACT_PROMPT"):
        args.prompt = env["ENACT_PROMPT"]
    if args.spec is None and env.get("ENACT_SPEC"):
        args.spec = env["ENACT_SPEC"]
    try:
        if args.persona is None and env.get("ENACT_PERSONA"):
            args.persona = int(env["ENACT_PERSONA"])
        if args.timeout is None:
            args.timeout = float(env["ENACT_TIMEOUT"]) if env.get("ENACT_TIMEOUT") else 120.0
    except ValueError:
        parser.error("PERSONA= 는 정수, TIMEOUT= 은 숫자여야 합니다")

    # ad-hoc 인라인 / --spec
    if args.spec or args.persona is not None or args.prompt:
        if pos:
            parser.error("ad-hoc 옵션(--spec/--persona/--prompt)과 positional 동시 지정 불가")
        if args.spec and (args.persona is not None or args.prompt):
            parser.error("--spec 과 --persona/--prompt 동시 지정 불가 (XOR)")
        if args.spec:
            spec = load_spec(args.spec)
        else:
            if args.persona is None or not args.prompt:
                parser.error("인라인 ad-hoc 은 --persona 와 --prompt 둘 다 필요")
            spec = {"persona": args.persona, "prompt": args.prompt}
        rt = synthesize_adhoc_rt(spec, chain_id=new_chain_id("adhoc"))
        return asyncio.run(_run_single(rt, str(rt["pipeline_id"]), args.timeout))

    # 시나리오 전수
    if not pos:
        return asyncio.run(_run_scenarios(list(ALL_SCENARIOS), args.timeout))

    head = pos[0]
    # 시나리오 단일
    if head in ALL_SCENARIOS:
        return asyncio.run(_run_scenarios([head], args.timeout))
    # pipeline 단건
    if _P_RE.match(head):
        step_token = pos[1] if len(pos) > 1 else None
        rt, _step, pipeline_id = synthesize_rt(head, step_token, chain_id=new_chain_id("single"))
        return asyncio.run(_run_single(rt, pipeline_id, args.timeout))
    # spec 경로 (cwd 기준 → repo 루트 기준 순 — make 가 cd tests/enact 후 실행하므로)
    from enact._harness import ROOT

    spec_path = Path(head) if Path(head).is_file() else ROOT / head
    if spec_path.is_file():
        rt = synthesize_adhoc_rt(load_spec(str(spec_path)), chain_id=new_chain_id("adhoc"))
        return asyncio.run(_run_single(rt, str(rt["pipeline_id"]), args.timeout))

    print(
        f"[enact] 인식 불가 인자: {head!r}\n"
        f"  사용법: enact [{'|'.join(ALL_SCENARIOS)}] | P{{NN}}.R{{NN}} [step] | <spec.yaml> "
        "| --persona N --prompt '…'",
        flush=True,
    )
    return 2
