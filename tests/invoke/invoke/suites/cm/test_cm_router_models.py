"""CM router — models-side endpoints in-process exerciser (probe 트랙).

담당 (router.py):
- users/identities (GET/PUT), users/profiles (GET/PUT/PATCH)
- sessions (POST/GET list/DELETE)
- manifest/context (GET/PUT/PATCH)
- models/manifest (GET/PUT)
- IOM / CMM / UR / CDS (GET pointer 분기 + PUT + PATCH)

async 테스트는 동기 def 안에서 asyncio.run(...) (pytest-asyncio mark 미사용).
fixture 인자에 stub_s3 를 항상 포함 — 실 boto3 호출 방지.
"""

from __future__ import annotations

import asyncio


# ───────────────────────────────────────────────────────────────────────────
# users/identities
# ───────────────────────────────────────────────────────────────────────────


def test_identity_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/users/identities/google/sub-xyz")
            assert r.status_code == 404
            assert "identity google/sub-xyz not found" in r.json()["detail"]

    asyncio.run(_run())


def test_identity_put_then_get(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put("/users/identities/google/sub-xyz", json={"user_id": "u-99"})
            assert r.status_code == 204
            r2 = await c.get("/users/identities/google/sub-xyz")
            assert r2.status_code == 200
            assert r2.json()["user_id"] == "u-99"

    asyncio.run(_run())


def test_identity_put_missing_user_id_400(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put("/users/identities/google/sub-xyz", json={})
            assert r.status_code == 400
            assert "user_id required" in r.json()["detail"]

    asyncio.run(_run())


def test_identity_delete_then_get_404(stub_s3, cm_app, asgi_client):
    # disconnect — DELETE 후 인덱스 사라짐 (멱등)
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put("/users/identities/google/sub-d", json={"user_id": "u-d"})
            r = await c.delete("/users/identities/google/sub-d")
            assert r.status_code == 204
            assert (await c.get("/users/identities/google/sub-d")).status_code == 404
            assert (await c.delete("/users/identities/google/sub-d")).status_code == 204  # 멱등

    asyncio.run(_run())


def test_identity_delete_ownership_checked(stub_s3, cm_app, asgi_client):
    # ?user_id 불일치 → 보존(재발급 매핑 보호), 일치 → 삭제
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put("/users/identities/google/sub-o", json={"user_id": "owner"})
            r1 = await c.delete("/users/identities/google/sub-o?user_id=other")
            assert r1.status_code == 204
            assert (await c.get("/users/identities/google/sub-o")).status_code == 200  # 보존
            r2 = await c.delete("/users/identities/google/sub-o?user_id=owner")
            assert r2.status_code == 204
            assert (await c.get("/users/identities/google/sub-o")).status_code == 404  # 삭제됨

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# users/profiles
# ───────────────────────────────────────────────────────────────────────────


def test_profile_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/users/profiles/u-1/profile")
            assert r.status_code == 404
            assert "profile u-1 not found" in r.json()["detail"]

    asyncio.run(_run())


def test_profile_put_then_get(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put("/users/profiles/u-1/profile", json={"nickname": "nick"})
            assert r.status_code == 204
            r2 = await c.get("/users/profiles/u-1/profile")
            assert r2.status_code == 200
            assert r2.json()["nickname"] == "nick"
            assert "updated_at" in r2.json()  # write_profile 스탬프 (D7)

    asyncio.run(_run())


def test_profile_patch_existing(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put("/users/profiles/u-1/profile", json={"nickname": "old"})
            r = await c.patch(
                "/users/profiles/u-1/profile",
                json=[{"op": "replace", "path": "/nickname", "value": "new"}],
            )
            assert r.status_code == 200
            assert r.json()["nickname"] == "new"
            assert "updated_at" in r.json()  # patch 결과에 새 updated_at (alias ETag 기준)

    asyncio.run(_run())


def test_profile_patch_no_existing_defaults_empty(stub_s3, cm_app, asgi_client):
    """existing None → {} 분기. add op 로 신규 필드."""

    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.patch(
                "/users/profiles/u-new/profile",
                json=[{"op": "add", "path": "/nickname", "value": "fresh"}],
            )
            assert r.status_code == 200
            assert r.json()["nickname"] == "fresh"

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# users/idempotency (D6) — Idempotency-Key 영속 store
# ───────────────────────────────────────────────────────────────────────────


def test_idempotency_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/users/idempotency/u-1/keyhash-abc")
            assert r.status_code == 404

    asyncio.run(_run())


def test_idempotency_put_then_get(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            rec = {"status": 201, "body": {"work_id": "w-1"}, "location": "/api/v1/works/w-1"}
            r = await c.put("/users/idempotency/u-1/keyhash-abc", json=rec)
            assert r.status_code == 204
            r2 = await c.get("/users/idempotency/u-1/keyhash-abc")
            assert r2.status_code == 200
            assert r2.json()["body"]["work_id"] == "w-1"

    asyncio.run(_run())


def test_idempotency_claim_finalize_delete(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post("/users/idempotency/u-2/kh/claim")
            assert r.status_code == 200 and r.json()["state"] == "claimed"
            r = await c.post("/users/idempotency/u-2/kh/claim")
            assert r.json()["state"] == "in_flight"  # 미완료 선점
            await c.put("/users/idempotency/u-2/kh", json={"status": 201, "body": {"x": 1}})
            r = await c.post("/users/idempotency/u-2/kh/claim")
            assert r.json()["state"] == "done" and r.json()["record"]["body"]["x"] == 1
            d = await c.delete("/users/idempotency/u-2/kh")
            assert d.status_code == 204

    asyncio.run(_run())


# users/refresh-tokens (C1 인증 — 회전·재사용 탐지·logout revoke)


def test_refresh_family_put_rotate_revoke(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put("/users/refresh-tokens/u-9/fam", json={"current_jti": "j1"})
            assert r.status_code == 204
            r = await c.post(
                "/users/refresh-tokens/u-9/fam/rotate",
                json={"expected_jti": "j1", "new_jti": "j2"},
            )
            assert r.json()["result"] == "rotated"
            # 직전 jti 재시도 → concurrent grace (탈취 아님)
            r = await c.post(
                "/users/refresh-tokens/u-9/fam/rotate",
                json={"expected_jti": "j1", "new_jti": "j3"},
            )
            assert r.json()["result"] == "concurrent"
            r = await c.post("/users/refresh-tokens/u-9/fam/revoke")
            assert r.status_code == 204

    asyncio.run(_run())


def test_refresh_family_put_missing_jti_400(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put("/users/refresh-tokens/u-9/fam", json={})
            assert r.status_code == 400

    asyncio.run(_run())


def test_refresh_family_rotate_missing_field_400(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post("/users/refresh-tokens/u-9/fam/rotate", json={"expected_jti": "j1"})
            assert r.status_code == 400

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# sessions — POST / GET list / DELETE
# ───────────────────────────────────────────────────────────────────────────


def test_create_session_with_user_id(stub_s3, cm_app, asgi_client):
    mem = stub_s3

    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post("/sessions", json={"user_id": "u-create"})
            assert r.status_code == 201
            body = r.json()
            assert body["user_id"] == "u-create"
            assert body["work_id"]
            assert body["session_id"]
            assert body["created_at"]
            # manifest.context.yaml 작성됨 (YAML 직렬화)
            iid = body["work_id"]
            key = f"sessions/u-create/{iid}/manifest.context.yaml"
            assert key in mem

    asyncio.run(_run())


def test_create_session_no_body_generates_user_id(stub_s3, cm_app, asgi_client):
    """body=None → user_id uuid 생성 분기."""

    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post("/sessions")
            assert r.status_code == 201
            assert r.json()["user_id"]

    asyncio.run(_run())


def test_create_session_user_id_none_generates(stub_s3, cm_app, asgi_client):
    """body 있으나 user_id None → uuid 생성 분기 (`or str(uuid4())`)."""

    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post("/sessions", json={"user_id": None})
            assert r.status_code == 201
            assert r.json()["user_id"]

    asyncio.run(_run())


def test_list_sessions(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post("/sessions", json={"user_id": "u-list"})
            iid = r.json()["work_id"]
            r2 = await c.get("/sessions/u-list")
            assert r2.status_code == 200
            body = r2.json()
            assert body["user_id"] == "u-list"
            invs = body["inventions"]
            ids = [x["work_id"] for x in invs]
            assert iid in ids
            entry = next(x for x in invs if x["work_id"] == iid)
            assert entry["phase"] == "discovery"
            assert entry["status"] == "draft"

    asyncio.run(_run())


def test_list_sessions_empty(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/sessions/u-empty")
            assert r.status_code == 200
            assert r.json()["inventions"] == []

    asyncio.run(_run())


def test_delete_invention_requires_confirm(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.delete("/sessions/u-del/inv-1")
            assert r.status_code == 400
            assert "confirm" in r.json()["detail"]

    asyncio.run(_run())


def test_delete_invention_confirmed(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post("/sessions", json={"user_id": "u-del2"})
            iid = r.json()["work_id"]
            r2 = await c.delete(f"/sessions/u-del2/{iid}", params={"confirm": "true"})
            assert r2.status_code == 200
            body = r2.json()
            assert body["work_id"] == iid
            assert body["deleted_objects"] >= 1

    asyncio.run(_run())


def test_delete_invention_missing_returns_zero(stub_s3, cm_app, asgi_client):
    """존재하지 않는 invention → deleted 0 (delete_invention not keys 분기)."""

    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.delete("/sessions/u-none/inv-none", params={"confirm": "true"})
            assert r.status_code == 200
            assert r.json()["deleted_objects"] == 0

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# manifest/context
# ───────────────────────────────────────────────────────────────────────────


def test_context_manifest_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/sessions/u/i/manifest/context")
            assert r.status_code == 404
            assert "context manifest not found" in r.json()["detail"]

    asyncio.run(_run())


def test_context_manifest_put_then_get(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put("/sessions/u/i/manifest/context", json={"status": "draft"})
            assert r.status_code == 204
            r2 = await c.get("/sessions/u/i/manifest/context")
            assert r2.status_code == 200
            assert r2.json()["status"] == "draft"

    asyncio.run(_run())


def test_context_manifest_patch(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put("/sessions/u/i/manifest/context", json={"status": "draft"})
            r = await c.patch(
                "/sessions/u/i/manifest/context",
                json=[{"op": "replace", "path": "/status", "value": "active"}],
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "active"
            assert "last_updated" in body  # patch 가 dict 면 last_updated 추가

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# models/manifest
# ───────────────────────────────────────────────────────────────────────────


def test_models_manifest_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/sessions/u/i/models/manifest")
            assert r.status_code == 404
            assert "models manifest not found" in r.json()["detail"]

    asyncio.run(_run())


def test_models_manifest_put_then_get(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put("/sessions/u/i/models/manifest", json={"models": ["iom"]})
            assert r.status_code == 204
            r2 = await c.get("/sessions/u/i/models/manifest")
            assert r2.status_code == 200
            assert r2.json()["models"] == ["iom"]

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# IOM — GET (full / pointer / invalid pointer / 404) + PUT + PATCH
# ───────────────────────────────────────────────────────────────────────────


def test_iom_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/sessions/u/i/models/invention-object-model")
            assert r.status_code == 404
            assert "invention-object-model not found" in r.json()["detail"]

    asyncio.run(_run())


def test_iom_put_then_get_full(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put(
                "/sessions/u/i/models/invention-object-model",
                json={"title": "T", "nested": {"x": 1}},
            )
            assert r.status_code == 204
            r2 = await c.get("/sessions/u/i/models/invention-object-model")
            assert r2.status_code == 200
            assert r2.json()["title"] == "T"

    asyncio.run(_run())


def test_iom_get_pointer_partial(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put(
                "/sessions/u/i/models/invention-object-model",
                json={"title": "T", "nested": {"x": 1}},
            )
            r = await c.get(
                "/sessions/u/i/models/invention-object-model",
                params={"pointer": "/nested/x"},
            )
            assert r.status_code == 200
            assert r.json() == 1

    asyncio.run(_run())


def test_iom_get_pointer_invalid_400(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put(
                "/sessions/u/i/models/invention-object-model",
                json={"title": "T"},
            )
            r = await c.get(
                "/sessions/u/i/models/invention-object-model",
                params={"pointer": "/does/not/exist"},
            )
            assert r.status_code == 400
            assert "invalid pointer" in r.json()["detail"]

    asyncio.run(_run())


def test_iom_patch(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put("/sessions/u/i/models/invention-object-model", json={"title": "T"})
            r = await c.patch(
                "/sessions/u/i/models/invention-object-model",
                json=[{"op": "replace", "path": "/title", "value": "U"}],
            )
            assert r.status_code == 200
            assert r.json()["title"] == "U"

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# CMM — same pattern (GET full/pointer/invalid/404 + PUT + PATCH)
# ───────────────────────────────────────────────────────────────────────────


def test_cmm_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/sessions/u/i/models/concept-maturity-model")
            assert r.status_code == 404
            assert "concept-maturity-model not found" in r.json()["detail"]

    asyncio.run(_run())


def test_cmm_put_get_pointer_and_invalid(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put(
                "/sessions/u/i/models/concept-maturity-model",
                json={"overall": 0.5, "scores": {"clarity": 0.3}},
            )
            assert r.status_code == 204
            # full
            rf = await c.get("/sessions/u/i/models/concept-maturity-model")
            assert rf.json()["overall"] == 0.5
            # pointer partial
            rp = await c.get(
                "/sessions/u/i/models/concept-maturity-model",
                params={"pointer": "/scores/clarity"},
            )
            assert rp.json() == 0.3
            # invalid pointer
            ri = await c.get(
                "/sessions/u/i/models/concept-maturity-model",
                params={"pointer": "/nope"},
            )
            assert ri.status_code == 400

    asyncio.run(_run())


def test_cmm_patch(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put(
                "/sessions/u/i/models/concept-maturity-model",
                json={"overall": 0.5},
            )
            r = await c.patch(
                "/sessions/u/i/models/concept-maturity-model",
                json=[{"op": "replace", "path": "/overall", "value": 0.9}],
            )
            assert r.status_code == 200
            assert r.json()["overall"] == 0.9

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# user-roadmap — top-level JSON array (GET full/pointer/invalid/404 + PUT)
# ───────────────────────────────────────────────────────────────────────────


def test_user_roadmap_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/sessions/u/i/models/user-roadmap")
            assert r.status_code == 404
            assert "user-roadmap not found" in r.json()["detail"]

    asyncio.run(_run())


def test_user_roadmap_put_array_then_get_full(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put(
                "/sessions/u/i/models/user-roadmap",
                json=[{"id": "r1", "title": "first"}],
            )
            assert r.status_code == 204
            r2 = await c.get("/sessions/u/i/models/user-roadmap")
            assert r2.status_code == 200
            data = r2.json()
            assert isinstance(data, list)
            assert data[0]["id"] == "r1"

    asyncio.run(_run())


def test_user_roadmap_get_pointer_array_index(stub_s3, cm_app, asgi_client):
    """top-level array → pointer /0/title 부분 read."""

    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put(
                "/sessions/u/i/models/user-roadmap",
                json=[{"id": "r1", "title": "first"}],
            )
            r = await c.get(
                "/sessions/u/i/models/user-roadmap",
                params={"pointer": "/0/title"},
            )
            assert r.status_code == 200
            assert r.json() == "first"

    asyncio.run(_run())


def test_user_roadmap_get_pointer_invalid_400(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put(
                "/sessions/u/i/models/user-roadmap",
                json=[{"id": "r1"}],
            )
            r = await c.get(
                "/sessions/u/i/models/user-roadmap",
                params={"pointer": "/99/title"},
            )
            assert r.status_code == 400
            assert "invalid pointer" in r.json()["detail"]

    asyncio.run(_run())


def test_user_roadmap_patch_item_by_id(stub_s3, cm_app, asgi_client):
    """PATCH /items/{id} — id 로 찾아 fields 병합(atomic, index 아님). 다른 항목 불변."""

    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put(
                "/sessions/u/i/models/user-roadmap",
                json=[{"id": "r1", "status": "pending"}, {"id": "r2", "status": "pending"}],
            )
            r = await c.patch(
                "/sessions/u/i/models/user-roadmap/items/r2",
                json={"answer": {"value": "v"}, "status": "satisfied"},
            )
            assert r.status_code == 200
            assert r.json()["id"] == "r2"
            assert r.json()["status"] == "satisfied"
            assert r.json()["answer"] == {"value": "v"}
            full = (await c.get("/sessions/u/i/models/user-roadmap")).json()
            assert full[0] == {"id": "r1", "status": "pending"}  # 다른 항목 불변
            assert full[1]["status"] == "satisfied"

    asyncio.run(_run())


def test_user_roadmap_patch_item_not_found_404(stub_s3, cm_app, asgi_client):
    """존재하는 UR 에 없는 id → set_array_item_by_id None → 404."""

    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put("/sessions/u/i/models/user-roadmap", json=[{"id": "r1"}])
            r = await c.patch(
                "/sessions/u/i/models/user-roadmap/items/nope",
                json={"status": "satisfied"},
            )
            assert r.status_code == 404
            assert "user-roadmap item 'nope'" in r.json()["detail"]

    asyncio.run(_run())


def test_user_roadmap_patch_item_no_array_404(stub_s3, cm_app, asgi_client):
    """UR 미생성(read None → list 아님) → 404."""

    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.patch(
                "/sessions/u/i/models/user-roadmap/items/r1",
                json={"status": "satisfied"},
            )
            assert r.status_code == 404

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# CDS — GET (full/pointer/invalid/404) + PUT + PATCH
# ───────────────────────────────────────────────────────────────────────────


def test_cds_get_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get("/sessions/u/i/models/concept-discovery-stack")
            assert r.status_code == 404
            assert "concept-discovery-stack not found" in r.json()["detail"]

    asyncio.run(_run())


def test_cds_put_get_pointer_and_invalid(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.put(
                "/sessions/u/i/models/concept-discovery-stack",
                json={"problem": "p", "fields": {"a": "b"}},
            )
            assert r.status_code == 204
            rf = await c.get("/sessions/u/i/models/concept-discovery-stack")
            assert rf.json()["problem"] == "p"
            rp = await c.get(
                "/sessions/u/i/models/concept-discovery-stack",
                params={"pointer": "/fields/a"},
            )
            assert rp.json() == "b"
            ri = await c.get(
                "/sessions/u/i/models/concept-discovery-stack",
                params={"pointer": "/missing"},
            )
            assert ri.status_code == 400

    asyncio.run(_run())


def test_cds_patch(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            await c.put(
                "/sessions/u/i/models/concept-discovery-stack",
                json={"problem": "p"},
            )
            r = await c.patch(
                "/sessions/u/i/models/concept-discovery-stack",
                json=[{"op": "add", "path": "/solution", "value": "s"}],
            )
            assert r.status_code == 200
            assert r.json()["solution"] == "s"

    asyncio.run(_run())
