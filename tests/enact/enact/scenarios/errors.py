"""시나리오 errors (A1-v) — dispatcher 의 SSE error 경로 4종.

각 경로를 독립 chain 으로 유도, started → error (result 0) + message 패턴 검증.
"""

from __future__ import annotations

from enact import _invariants as inv
from enact._harness import Harness, new_chain_id, new_work_id, synthesize_rt
from enact.scenarios import ScenarioOutcome

PIPELINE = "P01.R00.CHAT_CONVERSATION"


async def run(h: Harness, llm_mode: str, out: ScenarioOutcome) -> None:
    out.work_id = new_work_id()

    # (a) persona 미등재 — engine.config 에 없는 persona 9 dispatch (RT 불요)
    rt_id_a = "00000000-0000-0000-0000-0000000000aa"
    res_a = await h.dispatch(out.work_id, 9, new_chain_id("err-a"), rt_id_a)
    out.checks += inv.check_sse_error(res_a.events, rt_id_a, "not handled")

    # (b) RT 부재 — chain 만 만들고 RT 미생성, 임의 rt_id dispatch.
    # NOTE(스코프 외): Actor cm_client.get_rt 는 raise_for_status() 라 CM 404 를 예외로
    # 던진다 → dispatcher 의 `if rt is None: "RT not found for persona"` 분기는 dead code,
    # 실제 RT 부재 메시지는 httpx "404 Not Found". enact 는 현재 동작을 검증 (미구현/실제
    # 동작 통과 원칙) — dead-branch 는 스코프 외 발견으로 기록.
    chain_b = new_chain_id("err-b")
    await h.create_chain(out.work_id, 1, chain_b, PIPELINE)
    rt_id_b = "00000000-0000-0000-0000-0000000000bb"
    res_b = await h.dispatch(out.work_id, 1, chain_b, rt_id_b)
    out.checks += inv.check_sse_error(res_b.events, rt_id_b, "404 Not Found")

    # (c) composer 키 결손 — persona_prompt·inject_context_spec 뺀 RT
    chain_c = new_chain_id("err-c")
    rt_c, _step, pid_c = synthesize_rt(PIPELINE, "0", chain_id=chain_c, drop_composer_keys=True)
    await h.create_chain(out.work_id, int(rt_c["persona"]), chain_c, pid_c)
    await h.create_rt(out.work_id, int(rt_c["persona"]), chain_c, rt_c)
    res_c = await h.dispatch(out.work_id, int(rt_c["persona"]), chain_c, rt_c["rt_id"])
    out.checks += inv.check_sse_error(res_c.events, rt_c["rt_id"], "composer keys")

    # (d) legacy 평문 agent_state — dispatch 전 평문 messages PUT → parse fail-loud
    chain_d = new_chain_id("err-d")
    rt_d, _step_d, pid_d = synthesize_rt(PIPELINE, "0", chain_id=chain_d)
    persona_d = int(rt_d["persona"])
    await h.create_chain(out.work_id, persona_d, chain_d, pid_d)
    await h.create_rt(out.work_id, persona_d, chain_d, rt_d)
    await h.put_raw_agent_state(
        out.work_id, persona_d, chain_d, {"messages": [{"role": "user", "content": "old"}]}
    )
    res_d = await h.dispatch(out.work_id, persona_d, chain_d, rt_d["rt_id"])
    out.checks += inv.check_sse_error(res_d.events, rt_d["rt_id"], "legacy agent_state")

    if out.passed:
        await h.cleanup(out.work_id)
