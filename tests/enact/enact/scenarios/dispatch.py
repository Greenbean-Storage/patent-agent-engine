"""시나리오 dispatch (A1-i) — 정상 경로 1 RT.

P01.R00.CHAT_CONVERSATION step 0 을 실 pipeline 합성으로 seed → POST /dispatch →
SSE 시퀀스 · RT done + 계약 · structured=response_schema · envelope(items==2) · trail 검증.
"""

from __future__ import annotations

from enact import _invariants as inv
from enact._harness import Harness, new_chain_id, new_work_id, synthesize_rt
from enact.scenarios import ScenarioOutcome

PIPELINE = "P01.R00.CHAT_CONVERSATION"
STEP = "0"


async def run(h: Harness, llm_mode: str, out: ScenarioOutcome) -> None:
    out.work_id = new_work_id()
    chain_id = new_chain_id("dispatch")
    rt, _step, pipeline_id = synthesize_rt(PIPELINE, STEP, chain_id=chain_id)
    persona = int(rt["persona"])

    await h.create_chain(out.work_id, persona, chain_id, pipeline_id)
    await h.create_rt(out.work_id, persona, chain_id, rt)

    res = await h.dispatch(out.work_id, persona, chain_id, rt["rt_id"])
    if res.busy or res.status_code >= 400:
        out.fatal = f"dispatch HTTP {res.status_code} (busy={res.busy}) {res.error or ''}"
        return

    out.checks += inv.check_sse_sequence(res.events, rt["rt_id"])
    final_rt = await h.get_rt(out.work_id, persona, chain_id, rt["rt_id"])
    out.checks += inv.check_rt_done(final_rt)
    out.checks.append(inv.check_structured_contract(final_rt))
    state = await h.get_agent_state(out.work_id, persona, chain_id)
    out.checks += inv.check_envelope(state, llm_mode=llm_mode, expect_items=2)
    trail = await h.get_trail(out.work_id, persona, chain_id)
    out.checks.append(inv.check_trail(trail, expect_llm_input_prepared=1))

    if out.passed:
        await h.cleanup(out.work_id)
