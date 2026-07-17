"""AWS S3 backed storage.

레이아웃 단일 source: shared/venezia_memory/scaffolding.yaml.
모든 path 는 venezia_memory 의 key builder 를 거친다 — literal 금지.

호환을 위해 `_key(uid, iid, resource)` helper 는 유지 (resource = `<namespace>/<file>` 형식의
relative path). 신규 코드는 venezia_memory.* 의 함수 직접 호출 권장.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import boto3
import venezia_memory as vm
import yaml  # type: ignore[import-untyped]
from botocore.exceptions import ClientError

from .config import settings

log = logging.getLogger(__name__)
_s3_client: Any = None

ROOT_PREFIX = vm.ROOT_PREFIX


def _s3() -> Any:
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=settings.AWS_REGION)
    return _s3_client


def _key(user_id: str, work_id: str, resource: str) -> str:
    return f"{vm.session_root(user_id, work_id)}/{resource}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_yaml(resource: str) -> bool:
    return resource.endswith((".yaml", ".yml"))


def _serialize(resource: str, data: dict[str, Any] | list[Any]) -> tuple[bytes, str]:
    """직렬화 + ContentType 결정."""
    if _is_yaml(resource):
        body = yaml.safe_dump(
            data, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).encode("utf-8")
        return body, "application/yaml"
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    return body, "application/json"


def _deserialize(resource: str, raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8")
    if _is_yaml(resource):
        return yaml.safe_load(text) or {}
    return json.loads(text)


def apply_json_patch(doc: Any, ops: list[dict[str, Any]]) -> Any:
    """RFC 6902 JSON Patch 적용. operations: add / remove / replace / move / copy / test.
    path 는 RFC 6901 JSON Pointer (`/path/to/field`, array index, `/items/-` append marker).

    P-E: 기존 _deep_merge (dict-only) 폐기. array 도 지원.
    """
    import jsonpatch  # noqa: PLC0415

    patch = jsonpatch.JsonPatch(ops)
    return patch.apply(doc, in_place=False)


def read_pointer(doc: Any, pointer: str) -> Any:
    """RFC 6901 JSON Pointer 로 부분 read. 빈 string = root (전체)."""
    import jsonpointer  # noqa: PLC0415

    if not pointer or pointer == "/":
        return doc
    return jsonpointer.resolve_pointer(doc, pointer)


def read(user_id: str, work_id: str, resource: str) -> dict[str, Any] | None:
    try:
        obj = _s3().get_object(
            Bucket=settings.S3_BUCKET,
            Key=_key(user_id, work_id, resource),
        )
        return _deserialize(resource, obj["Body"].read())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def write(user_id: str, work_id: str, resource: str, data: dict[str, Any] | list[Any]) -> None:
    try:
        body, content_type = _serialize(resource, data)
        _s3().put_object(
            Bucket=settings.S3_BUCKET,
            Key=_key(user_id, work_id, resource),
            Body=body,
            ContentType=content_type,
        )
        log.info(
            "store.write uid=%s inv=%s resource=%s bytes=%d",
            user_id[:8],
            work_id[:8],
            resource,
            len(body),
        )
    except ClientError as exc:
        log.error(
            "store.write.failed key=%s/%s/%s error=%s",
            user_id,
            work_id,
            resource,
            exc,
        )
        raise


def read_by_key(key: str) -> dict[str, Any] | None:
    """Single-arg variant for callers that already built the full S3 key (e.g. chain_store)."""
    try:
        obj = _s3().get_object(Bucket=settings.S3_BUCKET, Key=key)
        return _deserialize(key, obj["Body"].read())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def write_by_key(key: str, data: dict[str, Any]) -> None:
    """Single-arg variant for callers that already built the full S3 key."""
    try:
        body, content_type = _serialize(key, data)
        _s3().put_object(
            Bucket=settings.S3_BUCKET,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        log.info("store.write_by_key key=%s bytes=%d", key, len(body))
    except ClientError as exc:
        log.error("store.write_by_key.failed key=%s error=%s", key, exc)
        raise


def patch(user_id: str, work_id: str, resource: str, ops: list[dict[str, Any]]) -> Any:
    """RFC 6902 JSON Patch 적용 후 write. ops = operations array.

    P-E: 기존 deep_merge dict-only 폐기.
    """
    existing = read(user_id, work_id, resource)
    if existing is None:
        existing = {}
    patched = apply_json_patch(existing, ops)
    if isinstance(patched, dict):
        patched["last_updated"] = _now()
    write(user_id, work_id, resource, patched)
    return patched


def set_array_item_by_id(
    user_id: str, work_id: str, resource: str, item_id: str, fields: dict[str, Any]
) -> dict[str, Any] | None:
    """top-level array resource 에서 `id` 일치 item 에 fields 를 병합 후 write — **id 기준 atomic**.

    sync(no await) 라 asyncio 단일 스레드에서 read→find→merge→write 가 무간섭으로 실행 →
    인덱스가 아니라 id 로 찾으므로, 동시 전체-재작성(예: P02 가 UR list 새로 PUT)이 끼어도
    엉뚱한 item 을 건드리지 않는다 (못 찾으면 None → 호출측 404)."""
    existing = read(user_id, work_id, resource)
    if not isinstance(existing, list):
        return None
    for item in existing:
        if isinstance(item, dict) and item.get("id") == item_id:
            item.update(fields)
            write(user_id, work_id, resource, existing)
            return item
    return None


# -- conversation (구 messages) ----------------------------------------------


def append_conversation(user_id: str, work_id: str, message: dict[str, Any]) -> dict[str, Any]:
    # conversation 은 runtime/00.dro/conversation.json. writer = DRO.
    full_key = vm.conversation_key(user_id, work_id)
    # store.read 가 _key 로 다시 prefix 붙이므로 relpath 만 추출
    prefix = vm.session_root(user_id, work_id) + "/"
    resource = full_key[len(prefix) :]
    existing = read(user_id, work_id, resource) or {
        "messages": [],
        "total_user_turns": 0,
        "last_updated": _now(),
    }
    msgs = existing.setdefault("messages", [])
    # 멱등 append (A-4) — user turn 의 meta.correlation_id 가 이미 기록됐으면 재-append 안 함.
    # message.send 가 put_idempotency 실패+TTL 재선점 등으로 재처리돼도 turn 중복 0 (CM 단일
    # 인스턴스 sync = read→write 원자). correlation_id 없으면(REST roadmap 등) 항상 append.
    corr = (message.get("meta") or {}).get("correlation_id")
    if corr is not None and any(
        isinstance(t, dict) and (t.get("meta") or {}).get("correlation_id") == corr for t in msgs
    ):
        return existing  # 이미 기록됨 — idempotent no-op
    msgs.append(message)
    if message.get("role") == "user":
        existing["total_user_turns"] = existing.get("total_user_turns", 0) + 1
    existing["last_updated"] = _now()
    write(user_id, work_id, resource, existing)
    log.info(
        "store.conversation_appended uid=%s inv=%s role=%s total_turns=%d",
        user_id[:8],
        work_id[:8],
        message.get("role"),
        existing.get("total_user_turns", 0),
    )
    return existing


# -- users/ (인증·식별 — sessions 와 별개 루트, PII 0) ------------------------


def read_identity(provider: str, provider_sub: str) -> dict[str, Any] | None:
    """users/identities/{provider}/{sub}.json = { user_id }. 로그인 인덱스."""
    return read_by_key(vm.identity_key(provider, provider_sub))


def write_identity(provider: str, provider_sub: str, user_id: str) -> None:
    """(provider, sub) → user_id 매핑 기록."""
    write_by_key(vm.identity_key(provider, provider_sub), {"user_id": user_id, "linked_at": _now()})


def delete_identity(
    provider: str, provider_sub: str, expected_user_id: str | None = None
) -> bool:
    """disconnect — (provider, sub) 로그인 인덱스 제거 (멱등). 반환 = 실제 삭제 여부.

    expected_user_id 주면 매핑이 그 user 를 가리킬 때만 삭제(소유권 확인 CAS). sync 함수라
    read→delete 사이 yield 없음 → CM 단일 인스턴스에서 원자. 부분실패 후 재시도가, 그 사이
    같은 (provider,sub) 로 재로그인해 **다른 user 로 재발급된** 매핑을 stale profile 기준으로
    지우는 cross-account 삭제를 차단. None 이면 무조건 삭제(레거시/admin)."""
    if expected_user_id is not None:
        rec = read_by_key(vm.identity_key(provider, provider_sub))
        if rec is None or rec.get("user_id") != expected_user_id:
            return False  # 없음 or 다른 user 로 재발급 → 건드리지 않음
    _s3().delete_object(Bucket=settings.S3_BUCKET, Key=vm.identity_key(provider, provider_sub))
    return True


def read_profile(user_id: str) -> dict[str, Any] | None:
    """users/profiles/{user_id}/profile.json = { nickname, providers, created_at }."""
    return read_by_key(vm.profile_key(user_id))


def write_profile(user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    # updated_at 스탬프 — alias If-Match/ETag 의 버전 기준 (D7). create·patch 모두 이 경로.
    stamped = {**data, "updated_at": _now()}
    write_by_key(vm.profile_key(user_id), stamped)
    return stamped


def read_idempotency(user_id: str, key_hash: str) -> dict[str, Any] | None:
    """users/idempotency/{user_id}/{key_hash}.json — Idempotency-Key record (D6). 없으면 None."""
    return read_by_key(vm.idempotency_key(user_id, key_hash))


def write_idempotency(user_id: str, key_hash: str, record: dict[str, Any]) -> None:
    """Idempotency-Key 완료 기록 (user-level). record = {status, body, location?, created_at}."""
    write_by_key(vm.idempotency_key(user_id, key_hash), record)


# 미완료 선점(in-flight) 만료(초) — 초과 시 죽은 요청으로 보고 재선점 (works/media 는 1s 내 완료)
_IDEM_TTL_S = 30


def _idem_stale(claimed_at: str | None) -> bool:
    if not claimed_at:
        return True
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(claimed_at)).total_seconds()
    except ValueError:
        return True
    return age > _IDEM_TTL_S


def claim_idempotency(
    user_id: str, key_hash: str, content_hash: str | None = None
) -> tuple[str, dict[str, Any] | None]:
    """원자적 선점 (D6). CM 단일 인스턴스 + sync boto3 = read→write 사이 yield 없음 → 원자.

    반환: ('done', record) 완료 기록 존재 · ('in_flight', record) 다른 요청 처리 중(신선) ·
    ('claimed', None) 선점 성공(또는 죽은 선점 재선점) → 호출자가 작업 후 write_idempotency 로 확정.
    content_hash 를 주면 선점 마커에 보존 → in_flight/done 회신 시 호출자가 같은 키·다른 내용
    충돌(메시지 멱등)을 검출할 수 있다.
    """
    rec = read_by_key(vm.idempotency_key(user_id, key_hash))
    if rec is not None:
        if rec.get("body") is not None:
            return ("done", rec)
        if not _idem_stale(rec.get("claimed_at")):
            return ("in_flight", rec)
    marker: dict[str, Any] = {"claimed_at": _now()}
    if content_hash is not None:
        marker["content_hash"] = content_hash
    write_by_key(vm.idempotency_key(user_id, key_hash), marker)
    return ("claimed", None)


def delete_idempotency(user_id: str, key_hash: str) -> None:
    """선점 해제 — 부수효과 실패 시 호출(재시도가 TTL 안 기다리고 즉시 재선점하도록)."""
    try:
        _s3().delete_object(Bucket=settings.S3_BUCKET, Key=vm.idempotency_key(user_id, key_hash))
    except ClientError as exc:
        log.warning("store.delete_idempotency.failed user=%s err=%s", user_id, exc)


# -- refresh token family (C1 인증 — 회전·재사용 탐지·logout revoke) ----------

# 회전 grace 창(초) — 직전(prev) jti 재사용을 '동시/재시도'로 봐주는 시간 한도.
# 정상 동시 갱신/네트워크 재시도는 초 단위라 이 창으로 충분히 포용하고, 창 밖의 prev 재사용
# (탈취된 직전 토큰의 지연 replay)은 reuse 로 처리해 family 를 폐기한다.
_REFRESH_GRACE_SECONDS = 30


def _within_refresh_grace(rotated_at: str | None) -> bool:
    if not rotated_at:
        return False
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(rotated_at)).total_seconds()
    except ValueError:
        return False
    return 0 <= age <= _REFRESH_GRACE_SECONDS


def read_refresh_family(user_id: str, family_id: str) -> dict[str, Any] | None:
    return read_by_key(vm.refresh_token_key(user_id, family_id))


def write_refresh_family(user_id: str, family_id: str, current_jti: str) -> dict[str, Any]:
    """최초 로그인 — 새 refresh family 기록 (current_jti)."""
    rec = {
        "family_id": family_id,
        "user_id": user_id,
        "current_jti": current_jti,
        "prev_jti": None,
        "issued_at": _now(),
        "rotated_at": None,
        "revoked": False,
    }
    write_by_key(vm.refresh_token_key(user_id, family_id), rec)
    return rec


def rotate_refresh_family(user_id: str, family_id: str, expected_jti: str, new_jti: str) -> str:
    """회전 CAS (CM 단일 인스턴스 + sync = read→write 원자). 반환 result ∈
    {rotated, concurrent, reuse, revoked, missing}.

    - missing    : family 없음.
    - revoked    : 이미 revoke (logout/이전 reuse).
    - rotated    : current_jti 일치 → prev_jti=current, current_jti=new_jti.
    - concurrent : 직전(prev) jti + 회전 후 grace 창 내 → 동시/재시도(이미 회전됨, 탈취 아님).
    - reuse      : current 불일치 + (prev 아님 OR grace 창 밖) → 탈취 의심 → family revoke.
    """
    rec = read_by_key(vm.refresh_token_key(user_id, family_id))
    if rec is None:
        return "missing"
    if rec.get("revoked"):
        return "revoked"
    if rec.get("current_jti") == expected_jti:
        rec["prev_jti"] = expected_jti
        rec["current_jti"] = new_jti
        rec["rotated_at"] = _now()
        write_by_key(vm.refresh_token_key(user_id, family_id), rec)
        return "rotated"
    if expected_jti == rec.get("prev_jti") and _within_refresh_grace(rec.get("rotated_at")):
        return "concurrent"  # 직전 jti + grace 창 내 — 동시 갱신/재시도, 이미 회전됨
    rec["revoked"] = True
    rec["revoked_at"] = _now()
    write_by_key(vm.refresh_token_key(user_id, family_id), rec)
    return "reuse"


def revoke_refresh_family(user_id: str, family_id: str) -> None:
    """logout — family revoke (멱등; 없으면 no-op)."""
    rec = read_by_key(vm.refresh_token_key(user_id, family_id))
    if rec is None:
        return
    rec["revoked"] = True
    rec["revoked_at"] = _now()
    write_by_key(vm.refresh_token_key(user_id, family_id), rec)


# -- session listing ----------------------------------------------------------


def list_inventions(user_id: str) -> list[dict[str, Any]]:
    paginator = _s3().get_paginator("list_objects_v2")
    work_ids: set[str] = set()
    prefix = f"{ROOT_PREFIX}/{user_id}/"
    for page in paginator.paginate(
        Bucket=settings.S3_BUCKET,
        Prefix=prefix,
        Delimiter="/",
    ):
        for cp in page.get("CommonPrefixes", []):
            # cp["Prefix"] = "sessions/{user_id}/{work_id}/"
            parts = cp["Prefix"].rstrip("/").split("/")
            if len(parts) >= 3:
                work_ids.add(parts[-1])

    result = []
    for inv_id in sorted(work_ids):
        manifest = read(user_id, inv_id, vm.ROOT_MANIFEST) or {}
        result.append(
            {
                "work_id": inv_id,
                "phase": manifest.get("current_phase", "discovery"),
                "status": manifest.get("status", "draft"),
                "created_at": manifest.get("created_at", _now()),
                "updated_at": manifest.get("updated_at", _now()),
            }
        )
    return result


# -- documents (binary) -------------------------------------------------------


def write_output(user_id: str, work_id: str, filename: str, content: bytes) -> None:
    """outputs/{filename} 에 binary 산출물 저장 (rename ← write_document)."""
    try:
        _s3().put_object(
            Bucket=settings.S3_BUCKET,
            Key=vm.output_key(user_id, work_id, filename),
            Body=content,
            ContentType="application/octet-stream",
        )
    except ClientError as exc:
        log.error(
            "store.write_output.failed key=%s/%s/%s error=%s",
            user_id,
            work_id,
            filename,
            exc,
        )
        raise


def read_output(user_id: str, work_id: str, filename: str) -> bytes | None:
    try:
        obj = _s3().get_object(
            Bucket=settings.S3_BUCKET,
            Key=vm.output_key(user_id, work_id, filename),
        )
        return obj["Body"].read()
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def list_outputs(user_id: str, work_id: str) -> list[str]:
    prefix = f"{vm.outputs_root(user_id, work_id)}/"
    paginator = _s3().get_paginator("list_objects_v2")
    names: list[str] = []
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            name = obj["Key"][len(prefix) :]
            if name and "/" not in name and not name.startswith("manifest."):
                names.append(name)
    return sorted(names)


# -- invention cleanup (S3 prefix delete) -------------------------------------


def delete_invention(user_id: str, work_id: str) -> int:
    """sessions/{user_id}/{work_id}/ S3 prefix 의 모든 object 삭제.

    반환: 삭제된 object 수. invention 자체가 없으면 0.
    위험: 되돌릴 수 없음. 호출자가 confirm 책임.
    """
    prefix = f"{ROOT_PREFIX}/{user_id}/{work_id}/"
    paginator = _s3().get_paginator("list_objects_v2")
    keys: list[dict[str, str]] = []
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append({"Key": obj["Key"]})

    if not keys:
        return 0

    deleted = 0
    # S3 delete_objects 는 한 번에 최대 1000 — batch 분할
    for i in range(0, len(keys), 1000):
        batch = keys[i : i + 1000]
        _s3().delete_objects(
            Bucket=settings.S3_BUCKET,
            Delete={"Objects": batch, "Quiet": True},
        )
        deleted += len(batch)
    return deleted


# -- structure (실제 S3 tree — 구조검증용) -------------------------------------


def list_session_keys(user_id: str, work_id: str) -> list[str]:
    """sessions/{uid}/{iid}/ 아래 모든 object 키를 session-relative 로 전수 반환.

    probe structure 가 scaffolding(venezia_memory) 과 대조할 실제 tree. (정렬 반환)
    """
    prefix = f"{vm.session_root(user_id, work_id)}/"
    paginator = _s3().get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix) :]
            if rel:
                keys.append(rel)
    return sorted(keys)


# -- media (work-level, presigned S3 direct — 바이트는 클라/Actor ↔ S3 직접) -----
#
# 키 = sessions/{user}/{work}/media/{media_id}.{ext}. 장부 없음 — S3 prefix 가 진실.
# CM 이 유일한 S3 자격 보유자라 presigned URL 서명도 CM 이 발급 (Nexus 는 인증 후 위임).


def presign_put(
    user_id: str, work_id: str, media_id: str, ext: str, mime: str, max_bytes: int, ttl: int
) -> dict[str, Any]:
    """업로드용 presigned POST 발급. S3 가 content-length-range·Content-Type 을 강제.

    반환: {url, fields, key} — 브라우저가 url 로 multipart POST(fields + file)로 직접 업로드.
    generate_presigned_post 는 로컬 서명 (S3 네트워크 호출 없음).
    """
    key = vm.media_key(user_id, work_id, media_id, ext)
    presigned = _s3().generate_presigned_post(
        Bucket=settings.S3_BUCKET,
        Key=key,
        Fields={"Content-Type": mime},
        Conditions=[
            ["content-length-range", 0, max_bytes],
            {"Content-Type": mime},
        ],
        ExpiresIn=ttl,
    )
    return {"url": presigned["url"], "fields": presigned["fields"], "key": key}


def resolve_media_key(user_id: str, work_id: str, media_id: str) -> str | None:
    """media_id → 실제 S3 키(media/{media_id}.{ext}). prefix 조회 (uuid 라 단일). 없으면 None."""
    prefix = f"{vm.media_root(user_id, work_id)}/{media_id}."
    resp = _s3().list_objects_v2(Bucket=settings.S3_BUCKET, Prefix=prefix, MaxKeys=2)
    contents = resp.get("Contents", [])
    if not contents:
        return None
    return str(contents[0]["Key"])


def presign_get(user_id: str, work_id: str, media_id: str, ttl: int) -> str | None:
    """다운로드용 presigned GET 발급. 객체 없으면 None (→ 404)."""
    key = resolve_media_key(user_id, work_id, media_id)
    if key is None:
        return None
    return str(
        _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET, "Key": key},
            ExpiresIn=ttl,
        )
    )


def list_media(user_id: str, work_id: str) -> list[dict[str, Any]]:
    """work 의 media/ prefix 전수. 각 item = {media_id, ext, key, size_bytes, mime, last_modified}.

    mime 은 S3 가 보유한 Content-Type (head_object) — 종류의 단일 진실은 S3 (장부 없음).
    """
    root = vm.media_root(user_id, work_id)
    prefix = f"{root}/"
    paginator = _s3().get_paginator("list_objects_v2")
    items: list[dict[str, Any]] = []
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            name = obj["Key"][len(prefix) :]
            if not name or "/" in name:
                continue
            media_id, _, ext = name.partition(".")
            head = _s3().head_object(Bucket=settings.S3_BUCKET, Key=obj["Key"])
            last_modified = obj.get("LastModified")
            items.append(
                {
                    "media_id": media_id,
                    "ext": ext,
                    "key": obj["Key"],
                    "size_bytes": obj["Size"],
                    "mime": head.get("ContentType", "application/octet-stream"),
                    "last_modified": last_modified.isoformat()
                    if hasattr(last_modified, "isoformat")
                    else last_modified,
                }
            )
    return sorted(items, key=lambda x: x["media_id"])


def delete_media(user_id: str, work_id: str, media_id: str) -> int:
    """media_id 의 S3 객체 삭제 (prefix media/{media_id}.). 반환: 삭제 수 (없으면 0). 멱등."""
    prefix = f"{vm.media_root(user_id, work_id)}/{media_id}."
    resp = _s3().list_objects_v2(Bucket=settings.S3_BUCKET, Prefix=prefix)
    keys = [{"Key": obj["Key"]} for obj in resp.get("Contents", [])]
    if not keys:
        return 0
    _s3().delete_objects(Bucket=settings.S3_BUCKET, Delete={"Objects": keys, "Quiet": True})
    return len(keys)
