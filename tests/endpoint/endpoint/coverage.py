"""endpoint coverage registry — 외부 표면 44(REST 33 + WS 11) 전수 대비 커버 상태.

목표: **자동화 가능한 표면 100% 커버** + 실 provider 대화형 consent 수동 smoke.
status:
  covered     — phase 가 어서션 실행 (현재 동작 통과 포함: 404/placeholder 도 '현재 계약' 검증)
  placeholder — 501 proposal (현재 동작 = 501 검증)
  future      — 미구현 백엔드/chain 타이밍이라 현재 미발생이 정상 (검증 실패 아님)
  irreducible — 실 provider 대화형 로그인·동의 e2e (release 수동 smoke)

`cross_check_spec()` 가 registry ↔ 실제 spec(openapi/asyncapi) parity 를 검사 → drift = 실패(완주).
유일한 spec reader. (사용자 정정: 일회성 검증 금지 → 트랙에 일반화.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

_SPEC_DIR = Path(__file__).resolve().parents[3] / ".docs" / "Architectures" / "external_api"


class Row(NamedTuple):
    kind: str  # "rest" | "ws_out" | "ws_in"
    key: str  # REST: "METHOD /path"  ·  WS: event/action 명
    status: str  # covered | placeholder | future | irreducible
    note: str = ""


# ── REST (33) — Nexus 단일 게이트웨이. key 는 openapi path 템플릿과 정확히 일치(cross_check 강제) ──
# output/docx는 Nexus 라우트가 DRO /control/output에 IOM→DOCX 변환을 위임한다.
_W = "/api/v1/works/{work_id}"
REGISTRY: list[Row] = [
    # health (Nexus 게이트웨이)
    Row("rest", "GET /health", "covered"),
    # work runtime (DRO→Nexus 이관 — phase/thread/estimate/media/roadmap-submit)
    Row("rest", f"GET {_W}/phase", "covered"),
    Row("rest", f"PATCH {_W}/phase", "covered", "state-flip; 작성 백엔드 별도 마일스톤"),
    Row("rest", f"GET {_W}/thread/messages", "covered"),
    Row("rest", f"GET {_W}/estimate/roadmap", "covered"),
    Row("rest", f"PATCH {_W}/estimate/roadmap/{{item_id}}", "covered"),
    Row("rest", f"GET {_W}/estimate/maturity", "covered"),
    Row("rest", f"POST {_W}/media", "covered"),
    Row("rest", f"GET {_W}/media", "covered"),
    Row("rest", f"GET {_W}/media/{{media_id}}", "covered"),
    Row("rest", f"DELETE {_W}/media/{{media_id}}", "covered"),
    # output/docx — draft = Nexus→DRO /control/output, proposal = 501 placeholder
    Row(
        "rest",
        f"POST {_W}/output/draft",
        "covered",
        "Nexus→DRO IOM→DOCX 동기 변환(200)",
    ),
    Row(
        "rest", f"GET {_W}/output/draft/preview", "covered", "마스킹 JSON; IOM 미준비=404 현재동작"
    ),
    Row("rest", f"GET {_W}/output/draft", "covered", "docx; 미빌드/미영속=404 현재동작"),
    Row("rest", f"POST {_W}/output/proposal/build", "placeholder", "501 — 라우트 OPEN·로직 미구현"),
    Row("rest", f"GET {_W}/output/proposal/preview", "placeholder", "501"),
    Row("rest", f"GET {_W}/output/proposal/download", "placeholder", "501"),
    # Nexus mypage (info/user/works)
    Row("rest", "GET /api/v1/info/providers", "covered"),
    Row("rest", "GET /api/v1/info/attributions", "covered"),
    Row("rest", "GET /api/v1/user/auth/{provider}/authorize", "covered"),
    Row(
        "rest",
        "GET /api/v1/user/auth/{provider}/callback",
        "irreducible",
        "실 provider exchange — 수동 smoke",
    ),
    Row(
        "rest",
        "POST /api/v1/user/auth/{provider}/connect",
        "irreducible",
        "실 provider exchange — 수동 smoke",
    ),
    Row(
        "rest",
        "DELETE /api/v1/user/auth/{provider}",
        "irreducible",
        "204 멱등; 연결 상태 의존 — 수동 smoke",
    ),
    Row("rest", "POST /api/v1/user/auth/refresh", "covered", "무쿠키→401(현재동작); 회전 e2e=수동"),
    Row("rest", "POST /api/v1/user/auth/logout", "covered", "무쿠키→멱등 204(현재동작)"),
    Row("rest", "GET /api/v1/user/account", "covered"),
    Row("rest", "GET /api/v1/user/account/alias", "covered"),
    Row("rest", "PUT /api/v1/user/account/alias", "covered"),
    Row("rest", "POST /api/v1/user/works", "covered"),
    Row("rest", "GET /api/v1/user/works", "covered"),
    Row("rest", "GET /api/v1/works/{work_id}", "covered", "진입 인덱스 ({work_id, title})"),
    Row("rest", "GET /api/v1/works/{work_id}/meta", "covered"),
    Row("rest", "PATCH /api/v1/works/{work_id}/meta", "covered"),
    # ── WS outbound (9) — message.*/work.*/model.*/output.*/system.* ──
    Row(
        "ws_out",
        "message.received",
        "covered",
        "message.send acceptance ack (unicast, data={correlation_id, id})",
    ),
    Row(
        "ws_out",
        "work.progress",
        "covered",
        "현 P01/P02 = support/analysis 채널 (나머지 4 채널 = future)",
    ),
    Row("ws_out", "message.reply", "future", "chain 타이밍 — dro:fake 에서 covered 승격"),
    Row(
        "ws_out",
        "work.failed",
        "future",
        "rt_error/error 매핑 — dro:fake 에러 tape 에서 covered 승격 (invoke 도 커버)",
    ),
    Row(
        "ws_out",
        "model.maturity",
        "future",
        "Nexus CM fetch 생성 — dro:fake CM 빈값이라 미발생(invoke 가 매핑 커버)",
    ),
    Row(
        "ws_out",
        "model.roadmap",
        "future",
        "Nexus CM fetch 생성 — dro:fake CM 빈값이라 미발생(invoke 가 매핑 커버)",
    ),
    Row(
        "ws_out",
        "output.ready",
        "future",
        "dro:fake는 mock /control/output으로 covered; dro:real은 IOM seeding(play SEED=) 필요",
    ),
    Row("ws_out", "system.resync_required", "future", "ring buffer evict 시만"),
    Row("ws_out", "system.error", "future", "strict inbound 위반 시 (invoke 단위 커버)"),
    # ── WS inbound (1) — strict {action, data:{content, correlation_id}} ──
    Row("ws_in", "message.send", "covered", "멱등 — 재시도는 같은 correlation_id 재send"),
]

_GREEN, _RED, _YEL, _RST = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def _spec_rest_set() -> tuple[set[str], list[str]]:
    """openapi.nexus.json (Nexus 단일) → {"METHOD /path"} set. 둘째 = 에러(파일 없음 등)."""
    errs: list[str] = []
    out: set[str] = set()
    for svc in ("nexus",):
        p = _SPEC_DIR / f"openapi.{svc}.json"
        if not p.exists():
            errs.append(f"openapi.{svc}.json 없음 — make export-openapi 필요")
            continue
        spec = json.loads(p.read_text(encoding="utf-8"))
        for path, ops in (spec.get("paths") or {}).items():
            for m in ops:
                if m in ("get", "post", "put", "delete", "patch"):
                    out.add(f"{m.upper()} {path}")
    return out, errs


def cross_check_spec() -> list[str]:
    """registry ↔ spec parity. 반환 = drift/에러 메시지 리스트 (빈 = OK)."""
    problems: list[str] = []
    spec_rest, errs = _spec_rest_set()
    problems += errs
    reg_rest = {r.key for r in REGISTRY if r.kind == "rest"}
    missing_in_reg = spec_rest - reg_rest
    missing_in_spec = reg_rest - spec_rest
    for k in sorted(missing_in_reg):
        problems.append(f"registry 누락 (spec 에만): {k}")
    for k in sorted(missing_in_spec):
        problems.append(f"spec 누락 (registry 에만): {k}")
    # WS: asyncapi.yaml 텍스트에 각 event/action 명이 존재하는지 (yaml dep 회피, substring)
    ap = _SPEC_DIR / "asyncapi.yaml"
    if not ap.exists():
        problems.append("asyncapi.yaml 없음")
    else:
        text = ap.read_text(encoding="utf-8")
        for r in REGISTRY:
            if r.kind in ("ws_out", "ws_in") and r.key not in text:
                problems.append(f"asyncapi 에 WS '{r.key}' 부재 (registry drift)")
    return problems


# scope 별 status 승격 — REGISTRY 불변, summary 출력 시에만 재계산 (DUALSCOPE §3.6).
# "fake"(dro:fake) = mock-dro tape 가 chain_completed/error 를 결정적 발생 → message.reply(text=null) + work.failed(에러 tape) covered.
# output.ready도 승격 — mock /control/output이 RAW output_ready emit → event_mapper → WS.
# model.maturity/model.roadmap 은 **제외** — Nexus 가 CM fetch 로 생성하는데 dro:fake 는 CM r/w 0
# 이라 빈값→미발생(매핑 검증은 invoke·dro:real).
_SCOPE_PROMOTIONS: dict[str, dict[tuple[str, str], str]] = {
    "fake": {
        ("ws_out", "message.reply"): "covered",
        ("ws_out", "work.failed"): "covered",
        ("ws_out", "output.ready"): "covered",
    }
}


def summary(phase_results: dict[str, bool], scope: str = "real") -> None:
    """커버 매트릭스 + 자동화 가능 표면 비율 출력."""
    promos = _SCOPE_PROMOTIONS.get(scope, {})
    rows = [r._replace(status=promos.get((r.kind, r.key), r.status)) for r in REGISTRY]
    by = {
        s: [r for r in rows if r.status == s]
        for s in ("covered", "placeholder", "future", "irreducible")
    }
    total = len(rows)
    achievable = len(by["covered"]) + len(by["placeholder"])
    covered_achievable = achievable  # 현재 모두 어서션됨 (covered=실행, placeholder=501 검증)
    pct = 100.0 * covered_achievable / achievable if achievable else 0.0
    bar = "━" * 76
    print(bar)
    print("  coverage — 외부 표면 44 (REST 33 + WS 11)")
    print(bar)
    print(f"  covered      : {len(by['covered']):>2}  (어서션 실행 — 404/501 '현재 계약' 포함)")
    print(f"  placeholder  : {len(by['placeholder']):>2}  (proposal 501 — 현재 동작 검증)")
    print(
        f"  future       : {len(by['future']):>2}  (미구현 백엔드/chain 타이밍 — 현재 미발생이 정상)"
    )
    print(
        f"  irreducible  : {len(by['irreducible']):>2}  (실 provider 대화형 consent — 수동 smoke)"
    )
    print(bar)
    print(
        f"  가능분(covered+placeholder) = {achievable}/{total - len(by['future']) - len(by['irreducible'])} "
        f"커버율 {pct:.0f}%  ·  future {len(by['future'])} · irreducible {len(by['irreducible'])} = 핸드오프 후/수동"
    )
    print(bar)
    if by["future"]:
        print("  [future]      " + ", ".join(r.key for r in by["future"]))
    if by["irreducible"]:
        print("  [irreducible] " + ", ".join(r.key for r in by["irreducible"]))
    print(bar)
