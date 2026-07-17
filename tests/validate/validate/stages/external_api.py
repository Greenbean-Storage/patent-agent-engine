"""Stage 9 — 외부 API spec(OpenAPI) 위생 검증 (pipeline 무관 1회).

frontend 핸드오프 계약 `external_api/openapi.nexus.json` (Nexus 단일 게이트웨이) 이 D6/D9/A3/A4 결정대로인지 정적 검증. DRO 는 외부 표면 0 — spec 없음.
A5 체크포인트의 일회성 `python - <<PY` spec 파싱을 트랙 stage 로 일반화.

검증:
- **풀 OpenAPI 3.x 메타검증** (openapi-spec-validator) — 부분 hygiene 이 아닌 spec 전 구조 정합
- success(2xx) body typed (generic object 는 `/health` 만 허용) — D6
- 4xx/5xx 응답이 `ErrorEnvelope` 참조 — D6 (주요 에러 typed)
- `ErrorCode` enum 에 내부 명사(invention/iom/chain) 0 — D9
- `PresignUploadResponse.media_id` (upload_id 없음) — media presigned 재설계
- `RoadmapSubmitResponse` 에 chains 없음 — A4

WS(asyncapi.yaml) 풀 메타검증은 stage_13_asyncapi 가, event 이름과 channel label
cross-consistency 는 stage_10_ws_consistency 가 담당. 두 명세의 payload field-set 정적 대조는
현재 수행하지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from .._common import ROOT, ValidationReport

STAGE_NAME = "external_api spec"
_SPEC_DIR = ROOT / ".docs" / "Architectures" / "external_api"
_REST_METHODS = ("get", "post", "put", "delete", "patch")


def _load(svc: str) -> dict[str, Any] | None:
    p = _SPEC_DIR / f"openapi.{svc}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _json_schema(resp: dict[str, Any]) -> dict[str, Any]:
    return ((resp.get("content") or {}).get("application/json") or {}).get("schema") or {}


def _validate_openapi_full(svc: str, spec: dict[str, Any], rep: ValidationReport) -> bool:
    """openapi-spec-validator 로 OpenAPI 3.x 전 구조 메타검증 (부분 hygiene 아닌 전체)."""
    try:
        from openapi_spec_validator import validate as _v
    except ImportError:
        try:
            from openapi_spec_validator import validate_spec as _v  # 구버전 API
        except ImportError:
            rep.err("[external_api] openapi-spec-validator 미설치 — tests/validate dep 확인")
            return False
    try:
        _v(spec)
    except Exception as e:
        first = str(e).splitlines()[0] if str(e) else type(e).__name__
        rep.err(f"[external_api/{svc}] OpenAPI 스펙 위반: {first[:200]}")
        return False
    return True


def validate_external_api_spec(rep: ValidationReport) -> bool:
    ok = True
    specs = {svc: _load(svc) for svc in ("nexus",)}

    for svc, spec in specs.items():
        if spec is None:
            rep.err(
                f"[external_api/{svc}] openapi.{svc}.json 없음/파싱 실패 — `make export-openapi` 필요"
            )
            ok = False
            continue
        # 풀 OpenAPI 메타검증 (전 구조) — 부분 hygiene 아래 검사들과 별개.
        if not _validate_openapi_full(svc, spec, rep):
            ok = False
        paths = spec.get("paths") or {}
        err_ref_seen = False
        for path, ops in paths.items():
            for method, op in (ops or {}).items():
                if method not in _REST_METHODS or not isinstance(op, dict):
                    continue
                for code, resp in (op.get("responses") or {}).items():
                    sch = _json_schema(resp)
                    code_s = str(code)
                    # success body typed (health 제외)
                    if code_s.startswith("2") and path != "/health":
                        typed = (
                            "$ref" in sch
                            or "properties" in sch
                            or sch.get("type") != "object"
                            or sch.get("additionalProperties") is not True
                        )
                        if not typed:
                            rep.err(
                                f"[external_api/{svc}] {method.upper()} {path} [{code}] "
                                f"success body 미타이핑(generic object) — D6"
                            )
                            ok = False
                    # 에러 응답 ErrorEnvelope 참조
                    if code_s.startswith(("4", "5")) and "ErrorEnvelope" in json.dumps(sch):
                        err_ref_seen = True
        if not err_ref_seen:
            rep.err(
                f"[external_api/{svc}] 4xx/5xx 응답이 ErrorEnvelope 미참조 — D6 주요 에러 typed"
            )
            ok = False

    # 공유 schema hygiene (Nexus components 에 ErrorCode/PresignUploadResponse/RoadmapSubmitResponse 존재)
    nexus = specs.get("nexus")
    if nexus:
        schemas = (nexus.get("components") or {}).get("schemas") or {}
        enum = (schemas.get("ErrorCode") or {}).get("enum") or []
        leaks = [
            v
            for v in enum
            if "invention" in str(v) or str(v).startswith("iom") or "chain" in str(v)
        ]
        if leaks:
            rep.err(f"[external_api] ErrorCode 내부 명사 누수: {leaks} — D9")
            ok = False
        up = (schemas.get("PresignUploadResponse") or {}).get("properties") or {}
        if up and ("media_id" not in up or "upload_id" in up):
            rep.err(f"[external_api] PresignUploadResponse 필드 {list(up)} — media_id 통일 위배")
            ok = False
        rsub = (schemas.get("RoadmapSubmitResponse") or {}).get("properties") or {}
        if "chains" in rsub:
            rep.err("[external_api] RoadmapSubmitResponse.chains 노출 — 내부 id 누수(A4)")
            ok = False

    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
