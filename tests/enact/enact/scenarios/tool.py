"""시나리오 tool (A1-iii) — DRO tool step 직접 호출 (POST /tool, RT 불요).

순수 tool(knowledge.load_rejections_section, CM-write 0)로 200 + 4종 에러 계약 검증.
503(풀 포화)은 concurrency 시나리오가 동일 503 계약을 커버하므로 여기선 생략 (중복 회피).
"""

from __future__ import annotations

from enact import _invariants as inv
from enact._harness import Harness
from enact.scenarios import ScenarioOutcome

PURE_TOOL = "knowledge.load_rejections_section"  # 순수 — CM-write 0, 인자 1개 optional


async def run(h: Harness, llm_mode: str, out: ScenarioOutcome) -> None:
    # tool 시나리오는 RT 불요(pure POST) — CM 네임스페이스 없음 (work_id 미사용)

    # 200 정상 — IPC 코드로 Section 가이드 로드
    ok = await h.tool(PURE_TOOL, {"ipc_codes": ["A01B"]})
    out.checks += inv.check_tool_response(ok, 200)

    # 404 — 미등록 tool
    nf = await h.tool("enact.nonexistent", {})
    out.checks += inv.check_tool_response(nf, 404)
    out.checks.append(inv.check_error_type(nf, "not_found"))

    # 400 — params 가 dict 아님 (router params 검증)
    bad_params = await h.tool(PURE_TOOL, "not-a-dict")  # type: ignore[arg-type]
    out.checks += inv.check_tool_response(bad_params, 400)
    out.checks.append(inv.check_error_type(bad_params, "validation_failed"))

    # 400 — handler 시그니처 불일치 (미지 kwarg → TypeError)
    bad_sig = await h.tool(PURE_TOOL, {"bogus_arg": 1})
    out.checks += inv.check_tool_response(bad_sig, 400)
    out.checks.append(inv.check_error_type(bad_sig, "validation_failed"))

    # 500 — handler 내부 예외 (maturity.compute 는 user_id/work_id 결손 시 raise, CM-write 전)
    exc = await h.tool("maturity.compute", {})
    out.checks += inv.check_tool_response(exc, 500)
    out.checks.append(inv.check_error_type(exc, "internal"))
