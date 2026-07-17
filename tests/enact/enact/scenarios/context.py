"""시나리오 context (A1-ii) — 컨텍스트 ② 실왕복.

같은 chain 에 P01.R00 step 0 → step 1 연속 dispatch. 두 번째 RT 가 첫 RT 의
agent_state envelope 를 native 복원해 items 가 누적(2→4)되고, 앞 2개가 보존
(prefix 일치 — FixtureSession 평문 {role, content})되는 것을 실검증.
"""

from __future__ import annotations

from enact import _invariants as inv
from enact._harness import Harness, new_chain_id, new_work_id, synthesize_rt
from enact.scenarios import ScenarioOutcome

PIPELINE = "P01.R00.CHAT_CONVERSATION"


async def run(h: Harness, llm_mode: str, out: ScenarioOutcome) -> None:
    out.work_id = new_work_id()
    chain_id = new_chain_id("context")

    states: list[dict] = []
    for step_token, expect_items in (("0", 2), ("1", 4)):
        rt, step, pipeline_id = synthesize_rt(
            PIPELINE,
            step_token,
            chain_id=chain_id,
            inputs={"steps": {}} if step_token == "0" else {},
        )
        persona = int(rt["persona"])
        if step_token == "0":
            await h.create_chain(out.work_id, persona, chain_id, pipeline_id)
        await h.create_rt(out.work_id, persona, chain_id, rt)

        res = await h.dispatch(out.work_id, persona, chain_id, rt["rt_id"])
        if res.busy or res.status_code >= 400:
            out.fatal = f"step {step_token} dispatch HTTP {res.status_code} (busy={res.busy})"
            return

        out.checks += inv.check_sse_sequence(res.events, rt["rt_id"])
        final_rt = await h.get_rt(out.work_id, persona, chain_id, rt["rt_id"])
        out.checks += inv.check_rt_done(final_rt)
        out.checks.append(inv.check_structured_contract(final_rt))
        state = await h.get_agent_state(out.work_id, persona, chain_id)
        out.checks += inv.check_envelope(state, llm_mode=llm_mode, expect_items=expect_items)
        states.append(state)

    # 컨텍스트 ② 핵심 — step1 후 envelope 가 step0 의 items 를 prefix 로 보존
    if len(states) == 2:
        prefix_ok = states[1].get("items", [])[:2] == states[0].get("items", [])
        out.checks.append(inv.Check("envelope 누적 (items[:2] == step0 items)", prefix_ok))

    persona = 1  # P01
    trail = await h.get_trail(out.work_id, persona, chain_id)
    out.checks.append(inv.check_trail(trail, expect_llm_input_prepared=2))

    if out.passed:
        await h.cleanup(out.work_id)
