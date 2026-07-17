"""Memory Manager REST API.

S3 layout 단일 source: shared/venezia_memory/scaffolding.yaml.
모든 path/key 는 venezia_memory 의 builder 함수가 결정.

Namespaces (P-A v3):
- manifest.context.yaml  (root, 세션 정체성)
- runtime/                모든 런타임 + 페르소나별 누적 + DRO 자료
    - manifest.runtime.yaml (chain 인덱스, 페르소나 무관 root)
    - 00.dro/             DRO 자체 자료 (페르소나 아님)
        - conversation.json
    - {persona}/          01.buddy ~ 06.inspector
        - queue.json      RT 큐 (chain_queue 폐기 — (session,persona) worker chain-at-a-time)
        - {dialog_name}.json   누적 dialog (allowlist)
        - {cid}/manifest.json + trail.jsonl + rts/{rt_id}.json + agent_state.json
- models/                 IOM / CMM / UR
- drawings/               (P-A 손 안 댐)
- outputs/                rename ← documents/
- media/                  사용자 업로드 (work 레벨, presigned S3 직접 — 메시지/chain 무관)
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import venezia_memory as vm
from fastapi import APIRouter, Body, HTTPException, Query, UploadFile
from fastapi.responses import Response

from . import chain_store, queue_store, store

router = APIRouter()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{resource} not found")


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _require_fields(body: dict[str, Any], *fields: str) -> None:
    """필수 본문 필드 누락/빈값 → 400 (직접 인덱싱의 KeyError→500 방지)."""
    missing = [f for f in fields if body.get(f) in (None, "")]
    if missing:
        raise _bad_request(f"missing required field(s): {', '.join(missing)}")


def _as_int(body: dict[str, Any], field: str) -> int:
    """정수 본문 필드 강제 — 누락/비정수 → 400 (int() ValueError→500 방지)."""
    try:
        return int(body[field])
    except (KeyError, TypeError, ValueError):
        raise _bad_request(f"field '{field}' must be an integer") from None


def _persona_dir_for(persona: str) -> str:
    """persona path param 검증. 'NN.name' 형식 (예: '01.buddy', '02.director')."""
    if persona not in set(vm.PERSONA_DIRS.values()):
        raise HTTPException(
            400,
            f"unknown persona dir {persona!r}. allowed: {sorted(vm.PERSONA_DIRS.values())}",
        )
    return persona


def _persona_int(persona: str | int) -> int:
    """'02.director' or 2 → 2"""
    if isinstance(persona, int):
        if 1 <= persona <= 6:
            return persona
        raise HTTPException(400, f"persona must be 1..6, got {persona}")
    for i, name in vm.PERSONA_DIRS.items():
        if name == persona:
            return i
    raise HTTPException(400, f"unknown persona dir {persona!r}")


async def _resolve_persona_by_chain(user_id: str, work_id: str, chain_id: str) -> int:
    """chain_id 만 알 때 manifest.runtime.yaml 에서 persona 찾기. probe / 외부 호환용."""
    manifest = await chain_store.get_chains_manifest(user_id, work_id)
    for entry in manifest.get("chains", []):
        if entry.get("chain_id") == chain_id:
            return int(entry.get("persona") or 0)
    raise HTTPException(404, f"chain {chain_id} not in manifest")


def _validate_dialog(persona: str, name: str) -> None:
    pdir = _persona_dir_for(persona)
    allowed = vm.DIALOG_NAMES.get(pdir, frozenset())
    if name not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"unknown dialog {name!r} for persona {pdir}. allowed: {sorted(allowed)}",
        )


def _dialog_resource(persona: str, name: str) -> str:
    """store relpath (session_root 제외). persona = dir name (예: 02.director)."""
    return f"{vm.NS_RUNTIME}/{persona}/{name}.json"


# ───────────────────────────────────────────────────────────────────────────
# Users (인증·식별 — sessions 와 별개 루트, PII 0)
#   identities/{provider}/{sub}.json = { user_id }   로그인 인덱스
#   profiles/{user_id}/profile.json  = { nickname, providers, created_at }
# ───────────────────────────────────────────────────────────────────────────


@router.get("/users/identities/{provider}/{provider_sub}")
async def get_identity(provider: str, provider_sub: str) -> dict[str, Any]:
    rec = store.read_identity(provider, provider_sub)
    if rec is None:
        raise _not_found(f"identity {provider}/{provider_sub}")
    return rec


@router.put("/users/identities/{provider}/{provider_sub}", status_code=204)
async def put_identity(
    provider: str, provider_sub: str, body: dict[str, Any] = Body(...)
) -> Response:
    user_id = body.get("user_id")
    if not user_id:
        raise _bad_request("user_id required")
    store.write_identity(provider, provider_sub, user_id)
    return Response(status_code=204)


@router.delete("/users/identities/{provider}/{provider_sub}", status_code=204)
async def delete_identity(
    provider: str, provider_sub: str, user_id: str | None = Query(default=None)
) -> Response:
    """disconnect — 로그인 인덱스 제거 (멱등). 이후 그 provider 재로그인 = 새 계정.
    user_id 주면 매핑이 그 user 를 가리킬 때만 삭제(재발급된 매핑 오삭제 방지)."""
    store.delete_identity(provider, provider_sub, expected_user_id=user_id)
    return Response(status_code=204)


@router.get("/users/profiles/{user_id}/profile")
async def get_profile(user_id: str) -> dict[str, Any]:
    rec = store.read_profile(user_id)
    if rec is None:
        raise _not_found(f"profile {user_id}")
    return rec


@router.put("/users/profiles/{user_id}/profile", status_code=204)
async def put_profile(user_id: str, body: dict[str, Any] = Body(...)) -> Response:
    store.write_profile(user_id, body)
    return Response(status_code=204)


@router.patch("/users/profiles/{user_id}/profile")
async def patch_profile(user_id: str, ops: list[dict[str, Any]] = Body(...)) -> dict[str, Any]:
    existing = store.read_profile(user_id) or {}
    patched = store.apply_json_patch(existing, ops)
    return store.write_profile(user_id, patched)


@router.get("/users/idempotency/{user_id}/{key_hash}")
async def get_idempotency(user_id: str, key_hash: str) -> dict[str, Any]:
    """users/idempotency/{user_id}/{key_hash}.json — Idempotency-Key record (D6). 없으면 404."""
    rec = store.read_idempotency(user_id, key_hash)
    if rec is None:
        raise _not_found(f"idempotency {user_id}/{key_hash}")
    return rec


@router.put("/users/idempotency/{user_id}/{key_hash}", status_code=204)
async def put_idempotency(
    user_id: str, key_hash: str, body: dict[str, Any] = Body(...)
) -> Response:
    """Idempotency-Key 완료 기록 저장 — body = {status, body, location?, created_at}."""
    store.write_idempotency(user_id, key_hash, body)
    return Response(status_code=204)


@router.post("/users/idempotency/{user_id}/{key_hash}/claim")
async def claim_idempotency(
    user_id: str, key_hash: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """원자적 선점 (D6) — state ∈ {done(+record), in_flight(+record), claimed}. CM 단일 인스턴스 = 원자.
    body.content_hash(선택)는 선점 마커에 보존 → in_flight/done 회신 시 같은 키·다른 내용 충돌 검출."""
    content_hash = (body or {}).get("content_hash")
    state, record = store.claim_idempotency(user_id, key_hash, content_hash)
    return {"state": state, "record": record}


@router.delete("/users/idempotency/{user_id}/{key_hash}", status_code=204)
async def delete_idempotency(user_id: str, key_hash: str) -> Response:
    """선점 해제 (부수효과 실패 시 — 재시도 즉시 재선점)."""
    store.delete_idempotency(user_id, key_hash)
    return Response(status_code=204)


# ── refresh token family (C1 인증 — 회전·재사용 탐지·logout revoke) ──


@router.put("/users/refresh-tokens/{user_id}/{family_id}", status_code=204)
async def put_refresh_family(
    user_id: str, family_id: str, body: dict[str, Any] = Body(...)
) -> Response:
    """최초 로그인 — 새 family 기록. body = {current_jti}."""
    jti = body.get("current_jti")
    if not jti:
        raise _bad_request("current_jti required")
    store.write_refresh_family(user_id, family_id, jti)
    return Response(status_code=204)


@router.post("/users/refresh-tokens/{user_id}/{family_id}/rotate")
async def rotate_refresh_family(
    user_id: str, family_id: str, body: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """회전 CAS — body = {expected_jti, new_jti}. result ∈ {rotated, reuse, revoked, missing}.
    CM 단일 인스턴스 = 원자. reuse 면 store 가 family revoke."""
    expected_jti = body.get("expected_jti")
    new_jti = body.get("new_jti")
    if not expected_jti or not new_jti:
        raise _bad_request("expected_jti & new_jti required")
    result = store.rotate_refresh_family(user_id, family_id, expected_jti, new_jti)
    return {"result": result}


@router.post("/users/refresh-tokens/{user_id}/{family_id}/revoke", status_code=204)
async def revoke_refresh_family(user_id: str, family_id: str) -> Response:
    """logout — family revoke (멱등)."""
    store.revoke_refresh_family(user_id, family_id)
    return Response(status_code=204)


# ───────────────────────────────────────────────────────────────────────────
# Session
# ───────────────────────────────────────────────────────────────────────────


@router.post("/sessions", status_code=201)
async def create_session(body: dict[str, Any] | None = None) -> dict[str, Any]:
    user_id = (body or {}).get("user_id") or str(uuid.uuid4())
    work_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    created_at = _now()

    # manifest.context.yaml 초기화 — mypage 표시용 메타 (title / title_source /
    # last_activity_at) 도 자리잡음. Nexus 의 PATCH /api/v1/works/{work_id}/meta 가 RFC 6902
    # ops 로 갱신. 자동 제목 placeholder 는 work_id 의 앞 8자.
    store.write(
        user_id,
        work_id,
        vm.ROOT_MANIFEST,
        {
            "user_id": user_id,
            "work_id": work_id,
            "session_id": session_id,
            "status": "draft",
            "current_phase": "discovery",
            "language": "ko",
            "title": f"발명 {work_id[:8]}",
            "title_source": "auto",
            "last_activity_at": created_at,
            "created_at": created_at,
            "updated_at": created_at,
        },
    )
    return {
        "user_id": user_id,
        "work_id": work_id,
        "session_id": session_id,
        "created_at": created_at,
    }


@router.get("/sessions/{user_id}")
async def list_sessions(user_id: str) -> dict[str, Any]:
    inventions = store.list_inventions(user_id)
    return {"user_id": user_id, "inventions": inventions}


@router.delete("/sessions/{user_id}/{work_id}", status_code=200)
async def delete_invention(user_id: str, work_id: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise _bad_request("DELETE 는 되돌릴 수 없음 — '?confirm=true' query 명시 필수")
    deleted = store.delete_invention(user_id, work_id)
    return {"user_id": user_id, "work_id": work_id, "deleted_objects": deleted}


@router.get("/sessions/{user_id}/{work_id}/tree")
async def get_session_tree(user_id: str, work_id: str) -> dict[str, Any]:
    """세션 prefix 의 실제 저장 키 전수 (session-relative). 구조검증(probe structure)용."""
    return {"keys": store.list_session_keys(user_id, work_id)}


# ───────────────────────────────────────────────────────────────────────────
# Context manifest (root)
# ───────────────────────────────────────────────────────────────────────────


@router.get("/sessions/{user_id}/{work_id}/manifest/context")
async def get_context_manifest(user_id: str, work_id: str) -> dict[str, Any]:
    data = store.read(user_id, work_id, vm.ROOT_MANIFEST)
    if data is None:
        raise _not_found("context manifest")
    return data


@router.put("/sessions/{user_id}/{work_id}/manifest/context", status_code=204)
async def put_context_manifest(user_id: str, work_id: str, body: dict[str, Any]) -> None:
    store.write(user_id, work_id, vm.ROOT_MANIFEST, body)


@router.patch("/sessions/{user_id}/{work_id}/manifest/context")
async def patch_context_manifest(
    user_id: str, work_id: str, body: list[dict[str, Any]]
) -> dict[str, Any]:
    """P-E: RFC 6902 JSON Patch ops array."""
    return store.patch(user_id, work_id, vm.ROOT_MANIFEST, body)


# ───────────────────────────────────────────────────────────────────────────
# Models — IOM + CMM + UR
# ───────────────────────────────────────────────────────────────────────────

_IOM_RESOURCE = f"{vm.NS_MODELS}/{vm.IOM_FILE}"
_CMM_RESOURCE = f"{vm.NS_MODELS}/{vm.CMM_FILE}"
_UR_RESOURCE = f"{vm.NS_MODELS}/{vm.USER_ROADMAP_FILE}"
_CDS_RESOURCE = f"{vm.NS_MODELS}/{vm.CONCEPT_DISCOVERY_STACK_FILE}"
_MODELS_MANIFEST_RESOURCE = f"{vm.NS_MODELS}/{vm.MANIFEST_MODELS}"


@router.get("/sessions/{user_id}/{work_id}/models/manifest")
async def get_models_manifest(user_id: str, work_id: str) -> dict[str, Any]:
    data = store.read(user_id, work_id, _MODELS_MANIFEST_RESOURCE)
    if data is None:
        raise _not_found("models manifest")
    return data


@router.put("/sessions/{user_id}/{work_id}/models/manifest", status_code=204)
async def put_models_manifest(user_id: str, work_id: str, body: dict[str, Any]) -> None:
    store.write(user_id, work_id, _MODELS_MANIFEST_RESOURCE, body)


@router.get("/sessions/{user_id}/{work_id}/models/invention-object-model")
async def get_iom(user_id: str, work_id: str, pointer: str | None = None) -> Any:
    """P-E: RFC 6901 JSON Pointer 부분 read. pointer 미지정 = 전체."""
    data = store.read(user_id, work_id, _IOM_RESOURCE)
    if data is None:
        raise _not_found("invention-object-model")
    if pointer:
        try:
            return store.read_pointer(data, pointer)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid pointer: {exc}") from exc
    return data


@router.put(
    "/sessions/{user_id}/{work_id}/models/invention-object-model",
    status_code=204,
)
async def put_iom(user_id: str, work_id: str, body: dict[str, Any]) -> None:
    store.write(user_id, work_id, _IOM_RESOURCE, body)


@router.patch("/sessions/{user_id}/{work_id}/models/invention-object-model")
async def patch_iom(user_id: str, work_id: str, body: list[dict[str, Any]]) -> Any:
    """P-E: RFC 6902 JSON Patch ops array."""
    return store.patch(user_id, work_id, _IOM_RESOURCE, body)


@router.get("/sessions/{user_id}/{work_id}/models/concept-maturity-model")
async def get_cmm(user_id: str, work_id: str, pointer: str | None = None) -> Any:
    """P-E: RFC 6901 JSON Pointer 부분 read."""
    data = store.read(user_id, work_id, _CMM_RESOURCE)
    if data is None:
        raise _not_found("concept-maturity-model")
    if pointer:
        try:
            return store.read_pointer(data, pointer)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid pointer: {exc}") from exc
    return data


@router.put(
    "/sessions/{user_id}/{work_id}/models/concept-maturity-model",
    status_code=204,
)
async def put_cmm(user_id: str, work_id: str, body: dict[str, Any]) -> None:
    store.write(user_id, work_id, _CMM_RESOURCE, body)


@router.patch("/sessions/{user_id}/{work_id}/models/concept-maturity-model")
async def patch_cmm(user_id: str, work_id: str, body: list[dict[str, Any]]) -> Any:
    """P-E: RFC 6902 JSON Patch ops array."""
    return store.patch(user_id, work_id, _CMM_RESOURCE, body)


@router.get("/sessions/{user_id}/{work_id}/models/user-roadmap")
async def get_user_roadmap(user_id: str, work_id: str, pointer: str | None = None) -> Any:
    """P-D: top-level JSON array. P-E: pointer 부분 read 가능."""
    data = store.read(user_id, work_id, _UR_RESOURCE)
    if data is None:
        raise _not_found("user-roadmap")
    if pointer:
        try:
            return store.read_pointer(data, pointer)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid pointer: {exc}") from exc
    return data


@router.put("/sessions/{user_id}/{work_id}/models/user-roadmap", status_code=204)
async def put_user_roadmap(user_id: str, work_id: str, body: list[dict[str, Any]]) -> None:
    """P-D: top-level JSON array — body 는 list of items."""
    store.write(user_id, work_id, _UR_RESOURCE, body)


@router.patch("/sessions/{user_id}/{work_id}/models/user-roadmap/items/{item_id}")
async def patch_user_roadmap_item(
    user_id: str, work_id: str, item_id: str, body: dict[str, Any]
) -> Any:
    """UR 항목(id 일치)에 body fields 를 **id 기준 atomic** 병합 — top-level array 의 index 경로는
    동시 전체-재작성에 어긋날 수 있어 쓰지 않는다. 못 찾으면 404."""
    item = store.set_array_item_by_id(user_id, work_id, _UR_RESOURCE, item_id, body)
    if item is None:
        raise _not_found(f"user-roadmap item '{item_id}'")
    return item


@router.get("/sessions/{user_id}/{work_id}/models/concept-discovery-stack")
async def get_concept_discovery_stack(
    user_id: str, work_id: str, pointer: str | None = None
) -> Any:
    """CDS — 사용자 말 7 필드 누적 (모델 아님, IOM precursor). P-E: pointer 부분 read."""
    data = store.read(user_id, work_id, _CDS_RESOURCE)
    if data is None:
        raise _not_found("concept-discovery-stack")
    if pointer:
        try:
            return store.read_pointer(data, pointer)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid pointer: {exc}") from exc
    return data


@router.put(
    "/sessions/{user_id}/{work_id}/models/concept-discovery-stack",
    status_code=204,
)
async def put_concept_discovery_stack(user_id: str, work_id: str, body: dict[str, Any]) -> None:
    store.write(user_id, work_id, _CDS_RESOURCE, body)


@router.patch("/sessions/{user_id}/{work_id}/models/concept-discovery-stack")
async def patch_concept_discovery_stack(
    user_id: str, work_id: str, body: list[dict[str, Any]]
) -> Any:
    """P-E: RFC 6902 JSON Patch ops array."""
    return store.patch(user_id, work_id, _CDS_RESOURCE, body)


# ───────────────────────────────────────────────────────────────────────────
# Drawings (P-A 손 안 댐)
# ───────────────────────────────────────────────────────────────────────────

_DRAWING_MANIFEST_RESOURCE = f"{vm.NS_DRAWINGS}/{vm.MANIFEST_DRAWINGS}"


@router.get("/sessions/{user_id}/{work_id}/drawings/manifest")
async def get_drawing_manifest(user_id: str, work_id: str) -> dict[str, Any]:
    data = store.read(user_id, work_id, _DRAWING_MANIFEST_RESOURCE)
    if data is None:
        raise _not_found("drawings manifest")
    return data


@router.put("/sessions/{user_id}/{work_id}/drawings/manifest", status_code=204)
async def put_drawing_manifest(user_id: str, work_id: str, body: dict[str, Any]) -> None:
    store.write(user_id, work_id, _DRAWING_MANIFEST_RESOURCE, body)


@router.patch("/sessions/{user_id}/{work_id}/drawings/manifest")
async def patch_drawing_manifest(user_id: str, work_id: str, body: list[dict[str, Any]]) -> Any:
    """P-E: RFC 6902 JSON Patch ops array."""
    return store.patch(user_id, work_id, _DRAWING_MANIFEST_RESOURCE, body)


@router.get("/sessions/{user_id}/{work_id}/drawings/{drawing_id}/numerals")
async def get_drawing_numerals(user_id: str, work_id: str, drawing_id: str) -> dict[str, Any]:
    data = store.read(user_id, work_id, f"{vm.NS_DRAWINGS}/{drawing_id}/numerals.json")
    if data is None:
        raise _not_found(f"numerals for {drawing_id}")
    return data


@router.put(
    "/sessions/{user_id}/{work_id}/drawings/{drawing_id}/numerals",
    status_code=204,
)
async def put_drawing_numerals(
    user_id: str, work_id: str, drawing_id: str, body: dict[str, Any]
) -> None:
    store.write(user_id, work_id, f"{vm.NS_DRAWINGS}/{drawing_id}/numerals.json", body)


@router.get("/sessions/{user_id}/{work_id}/drawings/{drawing_id}/dl")
async def get_drawing_dl(user_id: str, work_id: str, drawing_id: str) -> dict[str, Any]:
    data = store.read(user_id, work_id, f"{vm.NS_DRAWINGS}/{drawing_id}/dl.json")
    if data is None:
        raise _not_found(f"dl for {drawing_id}")
    return data


@router.put(
    "/sessions/{user_id}/{work_id}/drawings/{drawing_id}/dl",
    status_code=204,
)
async def put_drawing_dl(user_id: str, work_id: str, drawing_id: str, body: dict[str, Any]) -> None:
    store.write(user_id, work_id, f"{vm.NS_DRAWINGS}/{drawing_id}/dl.json", body)


@router.get("/sessions/{user_id}/{work_id}/drawings/{drawing_id}/figure")
async def get_drawing_figure(user_id: str, work_id: str, drawing_id: str) -> dict[str, Any]:
    data = store.read(user_id, work_id, f"{vm.NS_DRAWINGS}/{drawing_id}/figure.json")
    if data is None:
        raise _not_found(f"figure for {drawing_id}")
    return data


@router.put(
    "/sessions/{user_id}/{work_id}/drawings/{drawing_id}/figure",
    status_code=204,
)
async def put_drawing_figure(
    user_id: str, work_id: str, drawing_id: str, body: dict[str, Any]
) -> None:
    store.write(user_id, work_id, f"{vm.NS_DRAWINGS}/{drawing_id}/figure.json", body)


# ───────────────────────────────────────────────────────────────────────────
# Outputs (rename ← documents/)
# ───────────────────────────────────────────────────────────────────────────

_OUTPUTS_MANIFEST_RESOURCE = f"{vm.NS_OUTPUTS}/{vm.MANIFEST_OUTPUTS}"


@router.get("/sessions/{user_id}/{work_id}/outputs")
async def list_outputs(user_id: str, work_id: str) -> dict[str, Any]:
    files = store.list_outputs(user_id, work_id)
    return {"files": files}


@router.get("/sessions/{user_id}/{work_id}/outputs/manifest")
async def get_outputs_manifest(user_id: str, work_id: str) -> dict[str, Any]:
    data = store.read(user_id, work_id, _OUTPUTS_MANIFEST_RESOURCE)
    if data is None:
        raise _not_found("outputs manifest")
    return data


@router.put("/sessions/{user_id}/{work_id}/outputs/manifest", status_code=204)
async def put_outputs_manifest(user_id: str, work_id: str, body: dict[str, Any]) -> None:
    store.write(user_id, work_id, _OUTPUTS_MANIFEST_RESOURCE, body)


@router.put("/sessions/{user_id}/{work_id}/outputs/{filename}", status_code=204)
async def upload_output(user_id: str, work_id: str, filename: str, file: UploadFile) -> None:
    content = await file.read()
    store.write_output(user_id, work_id, filename, content)


@router.get("/sessions/{user_id}/{work_id}/outputs/{filename}")
async def download_output(user_id: str, work_id: str, filename: str) -> Response:
    content = store.read_output(user_id, work_id, filename)
    if content is None:
        raise _not_found(filename)
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if filename.endswith(".docx")
        else "application/octet-stream"
    )
    return Response(content=content, media_type=media_type)


# ═══════════════════════════════════════════════════════════════════════════
# RUNTIME — chain 인덱스 + DRO + persona sub-folder
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/sessions/{user_id}/{work_id}/runtime")
async def list_chains(user_id: str, work_id: str) -> dict[str, Any]:
    """invention 의 chain 인벤토리 (runtime/manifest.runtime.yaml).

    각 chain entry: chain_id / pipeline_id / persona / status / timestamps.
    """
    manifest = await chain_store.get_chains_manifest(user_id, work_id)
    return {
        "user_id": user_id,
        "work_id": work_id,
        "chains": manifest.get("chains", []),
        "last_updated": manifest.get("last_updated"),
    }


@router.get("/admin/active-chains")
async def admin_active_chains() -> dict[str, Any]:
    """전 세션 미완(pending/active) chain 열거 — DRO 재시작 자동복구용 (A-3).
    DRO startup 이 1회 호출 → 각 chain 을 재개(끊긴 작업 자동 완주). 외부 비노출(내부망)."""
    return {"chains": chain_store.list_active_chains()}


@router.post("/sessions/{user_id}/{work_id}/runtime", status_code=201)
async def create_chain_endpoint(
    user_id: str,
    work_id: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """chain manifest 생성 + manifest.runtime.yaml 인덱스 추가.

    chain_queue 폐기 — DRO orchestrator 가 직접 RT 들을 persona queue 에 push.

    body: {pipeline_id, persona (1~6), trigger, chain_id?}
    """
    chain_id = body.get("chain_id") or str(uuid.uuid4())
    pipeline_id = body.get("pipeline_id")
    persona = body.get("persona")
    trigger = body.get("trigger") or {"kind": "system"}
    if not pipeline_id:
        raise HTTPException(400, "pipeline_id required")
    if not isinstance(persona, int) or not 1 <= persona <= 6:
        raise HTTPException(400, "persona required (1~6)")

    manifest = await chain_store.create_chain(
        user_id, work_id, persona, chain_id, pipeline_id, trigger
    )
    return manifest


# ── 00.dro: conversation ──────────────────────────────────────────────────


_CONVERSATION_RESOURCE = f"{vm.NS_RUNTIME}/{vm.DRO_DIR}/conversation.json"


@router.get("/sessions/{user_id}/{work_id}/runtime/00.dro/conversation")
async def get_conversation(user_id: str, work_id: str, pointer: str | None = None) -> Any:
    data = store.read(user_id, work_id, _CONVERSATION_RESOURCE)
    if data is None:
        raise _not_found("conversation")
    if pointer:
        try:
            return store.read_pointer(data, pointer)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid pointer: {exc}") from exc
    return data


@router.post(
    "/sessions/{user_id}/{work_id}/runtime/00.dro/conversation/append",
    status_code=201,
)
async def append_conversation(user_id: str, work_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return store.append_conversation(user_id, work_id, body)


# ── media (work-level, presigned S3 direct) — 내부 발급. Nexus 가 인증·소유권 검증 후 위임 ──
# (private-network trust — 외부 비노출. 바이트는 브라우저/Actor ↔ S3 직접, CM 안 거침.)


@router.post("/sessions/{user_id}/{work_id}/media/presign-put")
async def presign_put_endpoint(
    user_id: str, work_id: str, body: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    # generate_presigned_post 는 로컬 서명 (S3 호출 없음) — to_thread 불요.
    _require_fields(body, "media_id", "ext", "mime")
    return store.presign_put(
        user_id,
        work_id,
        body["media_id"],
        body["ext"],
        body["mime"],
        _as_int(body, "max_bytes"),
        _as_int(body, "ttl"),
    )


@router.post("/sessions/{user_id}/{work_id}/media/presign-get")
async def presign_get_endpoint(
    user_id: str, work_id: str, body: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    _require_fields(body, "media_id")
    url = await asyncio.to_thread(
        store.presign_get, user_id, work_id, body["media_id"], _as_int(body, "ttl")
    )
    if url is None:
        raise _not_found("media")
    return {"url": url}


@router.get("/sessions/{user_id}/{work_id}/media")
async def list_media_endpoint(user_id: str, work_id: str) -> dict[str, Any]:
    items = await asyncio.to_thread(store.list_media, user_id, work_id)
    return {"items": items}


@router.delete("/sessions/{user_id}/{work_id}/media/{media_id}")
async def delete_media_endpoint(user_id: str, work_id: str, media_id: str) -> dict[str, Any]:
    deleted = await asyncio.to_thread(store.delete_media, user_id, work_id, media_id)
    return {"deleted": deleted}


# ── runtime/{persona}/queue.json (RT 큐) ──────────────────────────────────


@router.get("/sessions/{user_id}/{work_id}/runtime/{persona}/queue")
async def get_persona_queue_endpoint(user_id: str, work_id: str, persona: str) -> dict[str, Any]:
    _persona_dir_for(persona)
    return await queue_store.get_persona_queue(user_id, work_id, _persona_int(persona))


@router.post("/sessions/{user_id}/{work_id}/runtime/{persona}/queue/push")
async def persona_queue_push_endpoint(
    user_id: str,
    work_id: str,
    persona: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _persona_dir_for(persona)
    rt_id = body.get("rt_id")
    chain_id = body.get("chain_id")
    if not (rt_id and chain_id):
        raise HTTPException(400, "rt_id, chain_id required")
    return await queue_store.persona_queue_push(
        user_id, work_id, _persona_int(persona), rt_id, chain_id
    )


@router.post("/sessions/{user_id}/{work_id}/runtime/{persona}/queue/pop")
async def persona_queue_pop_endpoint(
    user_id: str,
    work_id: str,
    persona: str,
    body: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    _persona_dir_for(persona)
    actor_id = (body or {}).get("actor")
    chain_id = (body or {}).get("chain_id")
    lease_ttl_s = (body or {}).get("lease_ttl_s")
    head = await queue_store.persona_queue_pop(
        user_id,
        work_id,
        _persona_int(persona),
        actor_id=actor_id,
        chain_id=chain_id,
        lease_ttl_s=lease_ttl_s,
    )
    if head is None:
        return {"empty": True}
    return head


@router.post("/sessions/{user_id}/{work_id}/runtime/{persona}/queue/release")
async def persona_queue_release_endpoint(
    user_id: str,
    work_id: str,
    persona: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """본인 rt_id 의 lease 만 해제 (구 clear_inflight 폐기 — 동시 다건 lease 의 오인 삭제 방지)."""
    _persona_dir_for(persona)
    rt_id = (body or {}).get("rt_id")
    if not rt_id:
        raise HTTPException(400, "rt_id required")
    return await queue_store.persona_queue_release(user_id, work_id, _persona_int(persona), rt_id)


# ── runtime/{persona}/{dialog_name}.json (페르소나 누적 dialog) ───────────


@router.get("/sessions/{user_id}/{work_id}/runtime/{persona}/dialog/{name}")
async def get_dialog(user_id: str, work_id: str, persona: str, name: str) -> dict[str, Any]:
    _validate_dialog(persona, name)
    data = store.read(user_id, work_id, _dialog_resource(persona, name))
    if data is None:
        raise _not_found(f"dialog.{name}")
    return data


@router.put(
    "/sessions/{user_id}/{work_id}/runtime/{persona}/dialog/{name}",
    status_code=204,
)
async def put_dialog(
    user_id: str, work_id: str, persona: str, name: str, body: dict[str, Any]
) -> None:
    _validate_dialog(persona, name)
    store.write(user_id, work_id, _dialog_resource(persona, name), body)


@router.patch("/sessions/{user_id}/{work_id}/runtime/{persona}/dialog/{name}")
async def patch_dialog(
    user_id: str, work_id: str, persona: str, name: str, body: list[dict[str, Any]]
) -> Any:
    """P-E: RFC 6902 JSON Patch ops array."""
    _validate_dialog(persona, name)
    return store.patch(user_id, work_id, _dialog_resource(persona, name), body)


# ── runtime/{persona}/{chain_id}/ (chain 자료) ────────────────────────────


@router.get("/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}")
async def get_chain_endpoint(
    user_id: str, work_id: str, persona: str, chain_id: str
) -> dict[str, Any]:
    _persona_dir_for(persona)
    data = await chain_store.get_chain(user_id, work_id, _persona_int(persona), chain_id)
    if data is None:
        raise _not_found(f"chain {chain_id}")
    return data


@router.patch("/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}")
async def patch_chain_endpoint(
    user_id: str,
    work_id: str,
    persona: str,
    chain_id: str,
    body: list[dict[str, Any]] = Body(...),
) -> dict[str, Any]:
    """P-E: RFC 6902 JSON Patch ops array."""
    _persona_dir_for(persona)
    return await chain_store.patch_chain(user_id, work_id, _persona_int(persona), chain_id, body)


@router.post("/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}/trail")
async def append_trail_endpoint(
    user_id: str,
    work_id: str,
    persona: str,
    chain_id: str,
    event: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _persona_dir_for(persona)
    await chain_store.append_trail(user_id, work_id, _persona_int(persona), chain_id, event)
    return {"appended": True}


@router.get("/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}/trail")
async def get_trail_endpoint(user_id: str, work_id: str, persona: str, chain_id: str) -> Response:
    _persona_dir_for(persona)
    body = await chain_store.read_trail(user_id, work_id, _persona_int(persona), chain_id)
    return Response(content=body, media_type="application/x-ndjson")


@router.post(
    "/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}/rts",
    status_code=201,
)
async def create_rt_endpoint(
    user_id: str,
    work_id: str,
    persona: str,
    chain_id: str,
    rt: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _persona_dir_for(persona)
    if rt.get("chain_id") != chain_id:
        rt["chain_id"] = chain_id
    if not rt.get("rt_id"):
        rt["rt_id"] = str(uuid.uuid4())
    return await chain_store.create_rt(user_id, work_id, _persona_int(persona), chain_id, rt)


@router.get("/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}/rts/{rt_id}")
async def get_rt_endpoint(
    user_id: str, work_id: str, persona: str, chain_id: str, rt_id: str
) -> dict[str, Any]:
    _persona_dir_for(persona)
    data = await chain_store.get_rt(user_id, work_id, _persona_int(persona), chain_id, rt_id)
    if data is None:
        raise _not_found(f"rt {rt_id}")
    return data


@router.patch("/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}/rts/{rt_id}")
async def patch_rt_endpoint(
    user_id: str,
    work_id: str,
    persona: str,
    chain_id: str,
    rt_id: str,
    ops: list[dict[str, Any]] = Body(...),
) -> dict[str, Any]:
    """P-E: RFC 6902 JSON Patch ops array."""
    _persona_dir_for(persona)
    return await chain_store.patch_rt(user_id, work_id, _persona_int(persona), chain_id, rt_id, ops)


@router.get("/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}/agent_state")
async def get_agent_state_endpoint(
    user_id: str, work_id: str, persona: str, chain_id: str
) -> dict[str, Any]:
    _persona_dir_for(persona)
    return await chain_store.get_agent_state(user_id, work_id, _persona_int(persona), chain_id)


@router.put("/sessions/{user_id}/{work_id}/runtime/{persona}/{chain_id}/agent_state")
async def put_agent_state_endpoint(
    user_id: str,
    work_id: str,
    persona: str,
    chain_id: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _persona_dir_for(persona)
    # body = envelope pass-through (컨텍스트 ② — 내용은 Actor 소유, CM 은 opaque)
    return await chain_store.put_agent_state(
        user_id, work_id, _persona_int(persona), chain_id, body
    )


# ───────────────────────────────────────────────────────────────────────────
# Legacy by-chain endpoints — chain_id 만 알 때 (probe / 외부 호환)
# manifest.runtime.yaml 에서 persona resolve 후 chain_store 호출
# ───────────────────────────────────────────────────────────────────────────


@router.get("/sessions/{user_id}/{work_id}/chains/{chain_id}")
async def get_chain_by_id(user_id: str, work_id: str, chain_id: str) -> dict[str, Any]:
    persona = await _resolve_persona_by_chain(user_id, work_id, chain_id)
    data = await chain_store.get_chain(user_id, work_id, persona, chain_id)
    if data is None:
        raise _not_found(f"chain {chain_id}")
    return data


@router.get("/sessions/{user_id}/{work_id}/chains/{chain_id}/trail")
async def get_trail_by_id(user_id: str, work_id: str, chain_id: str) -> Response:
    persona = await _resolve_persona_by_chain(user_id, work_id, chain_id)
    body = await chain_store.read_trail(user_id, work_id, persona, chain_id)
    return Response(content=body, media_type="application/x-ndjson")


@router.get("/sessions/{user_id}/{work_id}/chains/{chain_id}/rts/{rt_id}")
async def get_rt_by_chain(user_id: str, work_id: str, chain_id: str, rt_id: str) -> dict[str, Any]:
    persona = await _resolve_persona_by_chain(user_id, work_id, chain_id)
    data = await chain_store.get_rt(user_id, work_id, persona, chain_id, rt_id)
    if data is None:
        raise _not_found(f"rt {rt_id}")
    return data
