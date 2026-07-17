"""Deterministic chain verification — AI 없이 검증 가능한 invariants.

CM 의 RT JSON + trail.jsonl 만 읽어서 fixture-mode 의 wiring 정합성을 점검.
fixture 가 지어내는 내용 자체는 평가하지 않는다 (의도된 정적 응답).

Invariants (`run_pipeline` 직후 + 단독 `verify-chain` subcommand 둘 다 사용):
  1. 모든 RT 가 state=done
  2. 각 LLM RT 의 system_prompt 에 charter prepended (trail llm_input_prepared.charter_prepended)
  3. RT.input.prompt 비어있지 않음 + RT.input.system_prompt 가 pipeline 의 step.system_prompt 포함
  4. context.steps 누적 — RT_n 의 ctx.steps 가 RT_1..RT_(n-1) 의 step_id 포함 (정적 병렬 묶음 형제 제외 — 동시 실행이라 서로 못 봄, D-6)
  5. response_schema wiring — pipeline step.output_schema 가 있으면 RT.input.response_schema 일치
  6. placeholder 미해소 — RT.input.prompt 에 '$.steps.X' 토큰이 남아있지 않음
  7. fixture output ⊂ tool_call result (warning 만) — search 단계 결과의 patent set 안에
     dedupe_rank.ranked_patents 의 application_number 가 모두 들어있는지
  8. tool_call params substitution — params_summary.query 가 query_plan.queries[*].text 와 일치
  9. search count sanity — max_results 가 명시된 tool_call 의 patents_count ≤ max_results
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from venezia_topology import service_url

from .._common import OPEN_USER_ID

CM_URL_DEFAULT = os.environ.get("CM_URL", service_url("cm"))
DEV_USER_DEFAULT = OPEN_USER_ID  # 단일원 (_common). 구 "dev-user-00000000" 폐기.


def _parallel_sibling_map(pipeline_id: str) -> dict[str, set[str]]:
    """pipeline_id → {step_id: 같은 정적 병렬 묶음 형제 step_id 집합}.

    병렬 묶음(nested list, D-6) sub 들은 **동시 실행**이라 서로의 step output 을 못 본다 →
    context.steps 누적(Invariant 4) 에서 형제는 expected_prior 에서 제외해야 한다. pipeline raw
    JSON 의 nested list 에서 형제를 도출. 파일 부재/파싱실패 = 빈 dict (병렬 없는 pipeline 은 무영향).
    """
    root = Path(__file__).resolve()
    for _ in range(8):
        if (root / "@pipelines").is_dir():
            break
        root = root.parent
    matches = list((root / "@pipelines").rglob(f"{pipeline_id}.pipeline.json"))
    if not matches:
        return {}
    try:
        raw = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    siblings: dict[str, set[str]] = {}
    for idx, step in enumerate(raw.get("steps") or []):
        if not isinstance(step, list):
            continue
        ids = [s.get("id") or str(idx) for s in step if isinstance(s, dict)]
        for sid in ids:
            siblings[sid] = set(ids) - {sid}
    return siblings


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    is_warning: bool = False  # warning 은 ok 와 별개로 PASS 가능


@dataclass
class VerifyReport:
    chain_id: str
    pipeline_id: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok or c.is_warning for c in self.checks)

    @property
    def has_failures(self) -> bool:
        return any((not c.ok) and (not c.is_warning) for c in self.checks)


# ---------------------------------------------------------------------------
# CM fetch helpers
# ---------------------------------------------------------------------------


async def _get_chain(http: httpx.AsyncClient, cm_url: str, u: str, i: str, c: str) -> dict:
    r = await http.get(f"{cm_url}/sessions/{u}/{i}/chains/{c}", timeout=10)
    return r.json() if r.status_code == 200 else {}


async def _get_trail(http: httpx.AsyncClient, cm_url: str, u: str, i: str, c: str) -> list[dict]:
    r = await http.get(f"{cm_url}/sessions/{u}/{i}/chains/{c}/trail", timeout=10)
    if r.status_code != 200:
        return []
    out: list[dict] = []
    for line in (r.text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


async def _get_rt(http: httpx.AsyncClient, cm_url: str, u: str, i: str, c: str, rt_id: str) -> dict:
    r = await http.get(f"{cm_url}/sessions/{u}/{i}/chains/{c}/rts/{rt_id}", timeout=10)
    return r.json() if r.status_code == 200 else {}


# ---------------------------------------------------------------------------
# pipeline JSON loader (host-side 검증 — production code 와 분리)
# ---------------------------------------------------------------------------


def _find_pipeline_path(pipeline_id: str) -> Path | None:
    root = Path(__file__).resolve().parents[3] / "@pipelines"
    for p in root.rglob("*.pipeline.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("pipeline_id") == pipeline_id:
            return p
    return None


def _load_pipeline(pipeline_id: str) -> dict:
    p = _find_pipeline_path(pipeline_id)
    if not p:
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def _looks_like_placeholder(s: str) -> bool:
    return isinstance(s, str) and "$." in s


async def verify_chain(
    user_id: str,
    work_id: str,
    chain_id: str,
    cm_url: str = CM_URL_DEFAULT,
) -> VerifyReport:
    """9개 invariant 를 평가하고 VerifyReport 반환."""
    async with httpx.AsyncClient() as http:
        chain = await _get_chain(http, cm_url, user_id, work_id, chain_id)
        trail = await _get_trail(http, cm_url, user_id, work_id, chain_id)
        pipeline_id = chain.get("pipeline_id", "")
        pipeline = _load_pipeline(pipeline_id) if pipeline_id else {}

        # trail 에서 rt_id 추출
        rt_ids: list[str] = []
        for e in trail:
            if e.get("event") in ("rt_enqueued", "rt_started", "rt_completed"):
                rid = e.get("rt_id")
                if rid and rid not in rt_ids:
                    rt_ids.append(rid)

        rts: list[dict] = []
        for rt_id in rt_ids:
            rt = await _get_rt(http, cm_url, user_id, work_id, chain_id, rt_id)
            if rt:
                rts.append(rt)

        # step_id → pipeline step JSON map
        pipeline_steps = {s.get("id"): s for s in pipeline.get("steps", [])}

        # trail llm_input_prepared per rt_id
        llm_input_evts: dict[str, dict] = {}
        for e in trail:
            if e.get("event") == "llm_input_prepared":
                rid = e.get("rt_id")
                if rid:
                    llm_input_evts[rid] = e

        # trail tool_call_started/done
        tool_started = [e for e in trail if e.get("event") == "tool_call_started"]
        tool_done = [e for e in trail if e.get("event") == "tool_call_done"]

        report = VerifyReport(chain_id=chain_id, pipeline_id=pipeline_id)

        # ── Invariant 1: RT 모두 done ─────────────────────────────────────
        not_done = [r.get("rt_id") for r in rts if r.get("state") != "done"]
        report.checks.append(
            CheckResult(
                name="1. RT state=done",
                ok=not not_done,
                detail=f"{len(rts)} RT, not_done={not_done}"
                if not_done
                else f"{len(rts)} RT all done",
            )
        )

        # ── Invariant 2: composer keys 존재 (P{NN} 포맷) ──────────────────
        # P{NN} 포맷에선 dispatcher 가 composer 로 prompt 합성. RT.input 에는
        # inject_context_spec / persona_prompt 가 있어야 함.
        missing_composer = []
        for r in rts:
            if r.get("step_type") == "tool_task":
                continue  # tool RT 는 composer 미경유 (tool=RT 통일, N-7) — composer 키 없음이 정상
            inp = r.get("input") or {}
            if "inject_context_spec" not in inp and "persona_prompt" not in inp:
                missing_composer.append(r.get("rt_id"))
        report.checks.append(
            CheckResult(
                name="2. composer keys (inject_context_spec/persona_prompt) 존재",
                ok=not missing_composer,
                detail=f"{len(rts)} RT, missing_composer={missing_composer}"
                if missing_composer
                else f"{len(rts)} RT all have composer keys (P{{NN}} 포맷)",
            )
        )

        # ── Invariant 3: composer 가 prompt_chars > 0 출력 ─────────────────
        # llm_input_prepared trail event 의 prompt_chars 가 양수여야 composer 가
        # 정상 합성. RT.input.prompt 는 composer 가 사용하지 않으므로 비어있는 게 정상.
        empty_composed = []
        for rid, e in llm_input_evts.items():
            if e.get("prompt_chars", 0) <= 0:
                empty_composed.append(rid)
        if llm_input_evts:
            report.checks.append(
                CheckResult(
                    name="3. composer prompt_chars > 0",
                    ok=not empty_composed,
                    detail=f"{len(llm_input_evts)} LLM RT, empty_composed={empty_composed}"
                    if empty_composed
                    else f"{len(llm_input_evts)} LLM RT composer prompt 합성 완료",
                )
            )
        else:
            report.checks.append(
                CheckResult(
                    name="3. composer prompt_chars > 0",
                    ok=False,
                    detail="no llm_input_prepared trail events found",
                    is_warning=True,
                )
            )

        # ── Invariant 4: context.steps 누적 (pipeline_id 별 group) ────────
        # sub_pipeline 으로 분기된 RT 는 자기 pipeline 의 sub_context.steps 만 가짐.
        # 부모 pipeline 의 step output 은 inputs_map 으로 sub.inputs 로 주입됨 (별도 경로).
        # 따라서 누적 검증은 같은 pipeline_id 안에서만 한다.
        rts_sorted = sorted(rts, key=lambda r: r.get("created_at", ""))
        by_pid: dict[str, list[dict]] = {}
        for r in rts_sorted:
            by_pid.setdefault(r.get("pipeline_id") or "", []).append(r)
        accum_fail = []
        for pid, group in by_pid.items():
            # Fan-out 의 같은 step_id 가 여러 RT 로 반복되므로 unique step_id 기준.
            # 자신의 step_id 는 expected_prior 에서 제외 (fan_out item 끼리는 independent
            # sub_context). 정적 병렬 묶음(D-6) 형제도 제외 — 동시 실행이라 서로 못 봄.
            sibling_map = _parallel_sibling_map(pid)
            for n, r in enumerate(group):
                if r.get("step_type") == "tool_task":
                    continue  # tool RT 는 input.context.steps 미보유 (params 직접) — 누적 검증 대상 아님
                inp = r.get("input") or {}
                ctx_steps = ((inp.get("context") or {}).get("steps")) or {}
                step_id = r.get("step_id")
                siblings = sibling_map.get(step_id, set()) if isinstance(step_id, str) else set()
                seen: list[str] = []
                for x in group[:n]:
                    sid = x.get("step_id")
                    if sid and sid not in seen:
                        seen.append(sid)
                expected_prior = [s for s in seen if s != step_id and s not in siblings]
                missing = [s for s in expected_prior if s not in ctx_steps]
                if missing:
                    accum_fail.append(f"[{pid}] {step_id}(missing: {missing[:5]})")
        report.checks.append(
            CheckResult(
                name="4. context.steps 누적",
                ok=not accum_fail,
                detail="; ".join(accum_fail[:6])
                if accum_fail
                else f"{len(rts_sorted)} RT 누적 OK across {len(by_pid)} pipeline",
            )
        )

        # ── Invariant 5: response_schema wiring ────────────────────────────
        schema_fail: list[str] = []
        for r in rts:
            step = pipeline_steps.get(r.get("step_id"))
            if step is None:
                continue
            pipeline_schema = step.get("output_schema")
            rt_schema = (r.get("input") or {}).get("response_schema")
            if pipeline_schema and rt_schema != pipeline_schema:
                schema_fail.append(str(r.get("step_id") or ""))
            if (not pipeline_schema) and rt_schema:
                schema_fail.append(f"{r.get('step_id')}(unexpected_schema)")
        report.checks.append(
            CheckResult(
                name="5. response_schema wiring",
                ok=not schema_fail,
                detail="; ".join(schema_fail) if schema_fail else f"{len(rts)} RT schema 일치",
            )
        )

        # ── Invariant 6: placeholder substitution 완전성 ──────────────────
        # RT.input.prompt 또는 system_prompt 에 '$.steps.' 토큰 남아 있으면 substitute 실패
        unresolved = []
        for r in rts:
            inp = r.get("input") or {}
            for fld in ("prompt", "system_prompt"):
                v = inp.get(fld) or ""
                if "$.steps." in v:
                    unresolved.append(f"{r.get('step_id')}.{fld}")
                    break
        report.checks.append(
            CheckResult(
                name="6. placeholder substitution",
                ok=not unresolved,
                detail="; ".join(unresolved)
                if unresolved
                else f"{len(rts)} RT placeholder 모두 해소",
            )
        )

        # ── Invariant 7: fixture output ⊂ tool_call result (warning) ─────
        # search_prior_art tool_call 의 patents_preview application_number 합집합 vs
        # dedupe_rank step output 의 ranked_patents application_number set
        real_app_numbers: set[str] = set()
        for e in tool_done:
            if e.get("tool", "").startswith("kipris.search"):
                preview = (e.get("summary") or {}).get("patents_preview") or []
                for p in preview:
                    an = p.get("application_number")
                    if an:
                        real_app_numbers.add(str(an))
        # dedupe_rank RT 의 output.structured.ranked_patents
        fixture_app_numbers: set[str] = set()
        for r in rts:
            if r.get("step_id") == "dedupe_rank":
                out = (r.get("output") or {}).get("structured") or {}
                for p in out.get("ranked_patents", []) or []:
                    an = p.get("application_number")
                    if an:
                        fixture_app_numbers.add(str(an))
        if fixture_app_numbers:
            extraneous = fixture_app_numbers - real_app_numbers
            report.checks.append(
                CheckResult(
                    name="7. fixture ⊂ real search",
                    ok=not extraneous,
                    detail=(
                        f"fixture references {len(extraneous)}/{len(fixture_app_numbers)} "
                        f"fabricated app_numbers not in search results — fixture refresh 필요. "
                        f"sample: {sorted(extraneous)[:3]}"
                    )
                    if extraneous
                    else f"all {len(fixture_app_numbers)} ⊂ real",
                    is_warning=True,  # fixture 가 본질상 정적이므로 warning
                )
            )

        # ── Invariant 8: tool_call params substitution ────────────────────
        # query_plan step output 의 queries[*].text vs tool_call_started.params_summary.query
        qp_queries: list[str] = []
        for r in rts:
            if r.get("step_id") == "query_plan":
                out = (r.get("output") or {}).get("structured") or {}
                for q in out.get("queries", []) or []:
                    if isinstance(q, dict) and q.get("text"):
                        qp_queries.append(str(q["text"]))
        tc_queries: list[str] = []
        for e in tool_started:
            if e.get("tool", "").startswith("kipris.search"):
                summ = e.get("params_summary") or {}
                q = summ.get("query")
                if isinstance(q, str):
                    tc_queries.append(q)
                elif e.get("params_keys") and "query" in e["params_keys"]:
                    # legacy trail (summary 없음) — skip with warning
                    pass
        if qp_queries:
            if tc_queries:
                missing_q = set(qp_queries) - set(tc_queries)
                extra = set(tc_queries) - set(qp_queries)
                report.checks.append(
                    CheckResult(
                        name="8. tool params substitution",
                        ok=not missing_q and not extra,
                        detail=(
                            f"qp={len(qp_queries)} tc={len(tc_queries)} "
                            f"missing_in_tool_call={sorted(missing_q)[:3]} "
                            f"unexpected_in_tool_call={sorted(extra)[:3]}"
                        )
                        if (missing_q or extra)
                        else f"{len(qp_queries)} queries 정확 매칭",
                    )
                )
            else:
                report.checks.append(
                    CheckResult(
                        name="8. tool params substitution",
                        ok=False,
                        detail="tool_call_started.params_summary missing (B3 hook 누락?)",
                        is_warning=True,
                    )
                )

        # ── Invariant 9: search count ≤ max_results ──────────────────────
        # pipeline step 의 params_map.max_results (search 단계) — fan_out 의 task.params_map
        search_max = None
        for s in pipeline.get("steps", []):
            if s.get("type") == "parallel_task":
                task = s.get("task") or {}
                pm = task.get("params_map") or {}
                if "max_results" in pm:
                    v = pm["max_results"]
                    if isinstance(v, int):
                        search_max = v
                        break
        if search_max is not None:
            over_max = []
            for e in tool_done:
                if e.get("tool", "").startswith("kipris.search"):
                    cnt = (e.get("summary") or {}).get("patents_count")
                    if isinstance(cnt, int) and cnt > search_max:
                        over_max.append((e.get("step_id"), cnt))
            report.checks.append(
                CheckResult(
                    name="9. search count ≤ max_results",
                    ok=not over_max,
                    detail=(f"max_results={search_max} over={over_max[:5]}")
                    if over_max
                    else f"max_results={search_max} 모두 ≤",
                )
            )

        return report


def print_report(report: VerifyReport) -> None:
    print(f"\n=== verify-chain: {report.chain_id} pipeline={report.pipeline_id} ===")
    for c in report.checks:
        if c.ok:
            mark = "[green]✓"
        elif c.is_warning:
            mark = "[yellow]⚠"
        else:
            mark = "[red]✗"
        # rich 없으면 plain
        try:
            from rich.console import Console

            Console().print(f"  {mark}[/] {c.name}: {c.detail}")
        except Exception:
            sym = "✓" if c.ok else ("⚠" if c.is_warning else "✗")
            print(f"  {sym} {c.name}: {c.detail}")
