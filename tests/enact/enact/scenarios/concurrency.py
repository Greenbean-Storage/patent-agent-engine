"""시나리오 concurrency (A1-iv) — persona cap 세마포어 503.

P2(Director, cap 2) chain 에 RT 3개 seed → dispatch_concurrent (gather 동시 진입) →
정확히 1개 503 busy+Retry-After, 2개 정상. router 의 release_persona 는 SSE body 소진
시점이라 gather 동시 진입이면 acquire 가 release 보다 먼저 몰려 cap+1 번째가 결정적 503.
"""

from __future__ import annotations

from enact import _invariants as inv
from enact._harness import Harness, new_chain_id, new_work_id, synthesize_rt
from enact.scenarios import ScenarioOutcome

PIPELINE = "P02.R00.CONCEPT_MATURITY"  # persona 2 — engine.config cap 2 (최소)
PERSONA = 2
CAP = 2


async def run(h: Harness, llm_mode: str, out: ScenarioOutcome) -> None:
    out.work_id = new_work_id()
    chain_id = new_chain_id("conc")

    # cap+1 개 RT seed (같은 chain·persona, step 0 = Agent step)
    rt_ids: list[str] = []
    created = False
    for _ in range(CAP + 1):
        rt, _step, pid = synthesize_rt(PIPELINE, "0", chain_id=chain_id)
        if not created:
            await h.create_chain(out.work_id, PERSONA, chain_id, pid)
            created = True
        await h.create_rt(out.work_id, PERSONA, chain_id, rt)
        rt_ids.append(rt["rt_id"])

    outcomes = await h.dispatch_concurrent(out.work_id, PERSONA, chain_id, rt_ids)

    busy = [o for o in outcomes if o.busy]
    served = [o for o in outcomes if not o.busy]
    out.checks.append(
        inv.inv_check(
            f"정확히 {CAP+1-CAP}개 503 busy (cap={CAP})",
            len(busy) == (CAP + 1 - CAP),
            f"busy={len(busy)} served={len(served)} codes={[o.status_code for o in outcomes]}",
        )
    )
    if busy:
        out.checks += inv.check_busy_retry_after(busy[0])
    # 처리된 것들은 정상 종결 (200 — error 0)
    out.checks.append(
        inv.inv_check(
            "served dispatch 정상 (error 0)",
            all(o.status_code == 200 and o.error is None for o in served),
            f"codes={[o.status_code for o in served]}",
        )
    )
    # slots 관측 — inflight ≤ cap (호출 후엔 보통 0 으로 회수)
    out.checks.append(inv.check_slots(await h.actor_health(), persona=PERSONA))

    if out.passed:
        await h.cleanup(out.work_id)
