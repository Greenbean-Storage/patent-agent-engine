"""enact 공통 불변식 (A4 — 자동 불변식 + 최소 expected).

시나리오 무관 공통 판정:
  - SSE 시퀀스 계약: started(rt_id 일치) → progress(llm_call_started) ≥1 → result (error 0)
  - RT state=done + RT.output 이 dispatch-result 계약 (@contracts/00.dro) 통과
  - structured 가 RT.input.response_schema 통과 (합성기 산출 재사용 — 별도 로드 없음)
  - agent_state 가 vendor 원형 envelope (schema_version 1 · llm:fake 면 vendor "fixture")
  - trail 에 llm_input_prepared 존재 (Actor 기록 이벤트만 — rt_enqueued 류는 DRO 소유라 부재 정상)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jsonschema

from enact._harness import ROOT


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def inv_check(name: str, ok: bool, detail: str = "") -> Check:
    """시나리오 인라인 Check 생성 헬퍼 (Check 직접 노출)."""
    return Check(name, ok, detail)


def print_checks(checks: list[Check]) -> None:
    for c in checks:
        mark = "✓" if c.ok else "✗"
        suffix = f": {c.detail}" if c.detail else ""
        print(f"  {mark} {c.name}{suffix}", flush=True)


@lru_cache(maxsize=1)
def _dispatch_result_schema() -> dict[str, Any]:
    path = ROOT / "@contracts" / "00.dro" / "dispatch-result.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_errors(data: Any, schema: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft7Validator(schema)
    return [
        f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator.iter_errors(data)
    ]


def check_sse_sequence(events: list[dict[str, Any]], rt_id: str) -> list[Check]:
    """순서까지 검증 — 첫 이벤트 = started, 중간 = progress 만, 마지막 = result.

    존재/개수만 보면 순서가 뒤집힌 스트림도 통과(false-pass)하므로 전체 형태를 강제.
    """
    types = [e["type"] for e in events]
    checks: list[Check] = []
    ordered = (
        len(types) >= 3
        and types[0] == "started"
        and types[-1] == "result"
        and all(t == "progress" for t in types[1:-1])
    )
    checks.append(Check("SSE 순서 (started → progress* → result)", ordered, f"types={types}"))
    started = [e for e in events if e["type"] == "started"]
    checks.append(
        Check(
            "SSE started (rt_id 일치)",
            len(started) == 1 and started[0].get("data", {}).get("rt_id") == rt_id,
            f"types={types}",
        )
    )
    progress = [
        e
        for e in events
        if e["type"] == "progress" and e.get("data", {}).get("phase") == "llm_call_started"
    ]
    checks.append(Check("SSE progress llm_call_started ≥1", len(progress) >= 1))
    checks.append(
        Check(
            "SSE result 종결 (error 0)",
            types.count("result") == 1 and types.count("error") == 0,
            f"types={types}",
        )
    )
    return checks


def check_rt_done(rt: dict[str, Any]) -> list[Check]:
    checks = [Check("RT state=done", rt.get("state") == "done", f"state={rt.get('state')}")]
    output = rt.get("output")
    errs = (
        _schema_errors(output, _dispatch_result_schema()) if output is not None else ["output 없음"]
    )
    checks.append(Check("RT.output = dispatch-result 계약", not errs, "; ".join(errs[:2])))
    return checks


def check_structured_contract(rt: dict[str, Any]) -> Check:
    """structured ↔ RT.input.response_schema (있을 때만 — 없으면 skip-pass)."""
    schema = (rt.get("input") or {}).get("response_schema")
    if not schema:
        return Check("structured = response_schema", True, "schema 없음 — skip")
    structured = (rt.get("output") or {}).get("structured")
    if structured is None:
        return Check("structured = response_schema", False, "structured 없음 (fixture-miss?)")
    errs = _schema_errors(structured, schema)
    return Check("structured = response_schema", not errs, "; ".join(errs[:2]))


def check_envelope(
    state: dict[str, Any], *, llm_mode: str, expect_items: int | None = None
) -> list[Check]:
    checks = [
        Check(
            "agent_state envelope (schema_version 1)",
            state.get("schema_version") == 1 and "items" in state,
            f"keys={sorted(state.keys())}",
        )
    ]
    if llm_mode == "FIXTURE":
        checks.append(
            Check(
                "envelope vendor=fixture",
                state.get("vendor") == "fixture",
                str(state.get("vendor")),
            )
        )
    items = state.get("items") or []
    if expect_items is not None:
        checks.append(
            Check(
                f"envelope items=={expect_items}", len(items) == expect_items, f"got {len(items)}"
            )
        )
    else:
        checks.append(Check("envelope items ≥1", len(items) >= 1, f"got {len(items)}"))
    return checks


def check_trail(trail: list[dict[str, Any]], *, expect_llm_input_prepared: int) -> Check:
    n = sum(1 for e in trail if e.get("event") == "llm_input_prepared")
    return Check(
        f"trail llm_input_prepared=={expect_llm_input_prepared}",
        n == expect_llm_input_prepared,
        f"got {n} (전체 {len(trail)}건 — rt_enqueued 류는 DRO 소유라 부재 정상)",
    )


# ─── tool · concurrency · errors 시나리오 불변식 ─────────────────────────────


def check_tool_response(outcome: Any, expected_status: int) -> list[Check]:
    """POST /tool 계약 — 200 {status:success, result} / 4xx·5xx ErrorEnvelope {error:{code,message}}."""
    checks = [
        Check(
            f"tool HTTP {expected_status}",
            outcome.status_code == expected_status,
            f"got {outcome.status_code}",
        )
    ]
    if expected_status == 200:
        r = outcome.result or {}
        checks.append(
            Check(
                "tool 200 {status:success, result}",
                r.get("status") == "success" and "result" in r,
                f"keys={sorted(r.keys())}",
            )
        )
    elif expected_status >= 400:
        body = outcome.error or {}
        err = body.get("error") if isinstance(body, dict) else None
        checks.append(
            Check(
                "tool error ErrorEnvelope {error:{code,message}}",
                isinstance(err, dict) and "code" in err and "message" in err,
                f"keys={sorted(body.keys())} code={(err or {}).get('code')}",
            )
        )
    return checks


def check_error_type(outcome: Any, expected_code: str) -> Check:
    code = ((outcome.error or {}).get("error") or {}).get("code")
    return Check(f"error code=={expected_code}", code == expected_code, f"got {code}")


def check_busy_retry_after(outcome: Any) -> list[Check]:
    """포화 503 — busy + Retry-After 헤더."""
    return [
        Check("status 503 busy", outcome.status_code == 503 and outcome.busy),
        Check("Retry-After 헤더 존재", bool(outcome.retry_after), f"got {outcome.retry_after!r}"),
    ]


def check_sse_error(
    events: list[dict[str, Any]], rt_id: str | None, msg_substr: str
) -> list[Check]:
    """error 경로 — started → error (result 0), error.message 에 msg_substr 포함.

    persona 미등재처럼 RT read 전 거부는 started 가 rt_id 를 담음 (dispatcher 가 먼저 emit).
    """
    types = [e["type"] for e in events]
    checks: list[Check] = []
    started = [e for e in events if e["type"] == "started"]
    errors = [e for e in events if e["type"] == "error"]
    checks.append(
        Check(
            "SSE started → error (result 0)",
            len(started) == 1 and len(errors) == 1 and types.count("result") == 0,
            f"types={types}",
        )
    )
    if rt_id is not None and started:
        checks.append(
            Check(
                "started rt_id 일치",
                started[0].get("data", {}).get("rt_id") == rt_id,
                f"got {started[0].get('data', {}).get('rt_id')}",
            )
        )
    msg = ((errors[0].get("data") or {}).get("error") or {}).get("message", "") if errors else ""
    checks.append(Check(f"error message ⊃ {msg_substr!r}", msg_substr in msg, f"got {msg[:90]!r}"))
    return checks


def check_slots(
    snapshot: dict[str, Any], *, persona: int | None = None, min_inflight: int = 0
) -> Check:
    """/health.slots 관측 — inflight ≤ cap (+ 선택 min_inflight). persona 키는 문자열."""
    slots = snapshot.get("slots") or {}
    if persona is not None:
        cell = (slots.get("personas") or {}).get(str(persona)) or {}
        label = f"persona {persona}"
    else:
        cell = slots.get("tool") or {}
        label = "tool 풀"
    cap, inflight = cell.get("cap"), cell.get("inflight", 0)
    ok = cap is not None and 0 <= inflight <= cap and inflight >= min_inflight
    return Check(f"slots {label} inflight≤cap", ok, f"cap={cap} inflight={inflight}")
