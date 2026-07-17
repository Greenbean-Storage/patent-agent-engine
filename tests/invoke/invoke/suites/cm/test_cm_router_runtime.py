"""CM router.py — runtime-side endpoints + persona/dialog/chain 헬퍼 전수 커버.

probe 트랙 cm_exercise. drawings / outputs / runtime(chain index + create) / conversation /
media / persona queue / dialog / chain / RT / agent_state / chains-by-id aliases.

router 의 나머지 절반(users / session / manifest / models)은 test_cm_router_models.py 가 담당 —
여기서는 위 runtime-side endpoint + 헬퍼(_persona_dir_for / _persona_int / _validate_dialog /
_dialog_resource / _resolve_persona_by_chain) 라인을 커버.

async 는 pytest-asyncio mark 미사용 — 동기 def 안에서 asyncio.run.
"""

from __future__ import annotations

import asyncio

import venezia_memory as vm

U = "u-rt"
INV = "i-rt"
SROOT = f"sessions/{U}/{INV}"


# ───────────────────────────────────────────────────────────────────────────
# 헬퍼 직접 단위 (_persona_int — int 분기는 router endpoint 가 str 만 넘겨 도달 불가)
# ───────────────────────────────────────────────────────────────────────────


def test_persona_int_helper():
    from fastapi import HTTPException

    from src import router

    # int 입력 in-range (line 60-61)
    assert router._persona_int(2) == 2
    # str 입력 정상 (line 63-65)
    assert router._persona_int("03.finder") == 3
    # int 범위 밖 → 400 (line 62)
    try:
        router._persona_int(0)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "persona must be 1..6" in exc.detail
    # str 미존재 → 400 (line 66)
    try:
        router._persona_int("99.nope")
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "unknown persona dir" in exc.detail


# ───────────────────────────────────────────────────────────────────────────
# drawings
# ───────────────────────────────────────────────────────────────────────────


def test_drawings_manifest_get_put_patch(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # GET 404 (없음)
            r = await c.get(f"/{SROOT}/drawings/manifest")
            assert r.status_code == 404
            assert r.json()["detail"] == "drawings manifest not found"
            # PUT 204
            r = await c.put(f"/{SROOT}/drawings/manifest", json={"drawings": []})
            assert r.status_code == 204
            # GET 200
            r = await c.get(f"/{SROOT}/drawings/manifest")
            assert r.status_code == 200
            assert r.json() == {"drawings": []}
            # PATCH (RFC6902 add)
            r = await c.patch(
                f"/{SROOT}/drawings/manifest",
                json=[{"op": "add", "path": "/count", "value": 1}],
            )
            assert r.status_code == 200
            assert r.json()["count"] == 1

    asyncio.run(_run())


def test_drawings_numerals_dl_figure(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            did = "fig-1"
            for kind, payload in (
                ("numerals", {"100": "frame"}),
                ("dl", {"parts": ["a"]}),
                ("figure", {"svg": "<svg/>"}),
            ):
                # GET 404 분기
                r = await c.get(f"/{SROOT}/drawings/{did}/{kind}")
                assert r.status_code == 404, kind
                # PUT 204
                r = await c.put(f"/{SROOT}/drawings/{did}/{kind}", json=payload)
                assert r.status_code == 204, kind
                # GET 200
                r = await c.get(f"/{SROOT}/drawings/{did}/{kind}")
                assert r.status_code == 200, kind
                assert r.json() == payload

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# outputs
# ───────────────────────────────────────────────────────────────────────────


def test_outputs_manifest_and_list(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # manifest GET 404
            r = await c.get(f"/{SROOT}/outputs/manifest")
            assert r.status_code == 404
            # manifest PUT 204 (manifest.* 는 list 에 제외돼야 함)
            r = await c.put(f"/{SROOT}/outputs/manifest", json={"files": []})
            assert r.status_code == 204
            # manifest GET 200
            r = await c.get(f"/{SROOT}/outputs/manifest")
            assert r.status_code == 200
            # 빈 list (manifest 파일은 store.list_outputs 가 manifest. 시작 제외)
            r = await c.get(f"/{SROOT}/outputs")
            assert r.status_code == 200
            assert r.json()["files"] == []

    asyncio.run(_run())


def test_outputs_upload_download(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # download 404 (없음)
            r = await c.get(f"/{SROOT}/outputs/draft.docx")
            assert r.status_code == 404
            assert r.json()["detail"] == "draft.docx not found"
            # upload (multipart UploadFile)
            r = await c.put(
                f"/{SROOT}/outputs/draft.docx",
                files={"file": ("draft.docx", b"DOCXBYTES", "application/octet-stream")},
            )
            assert r.status_code == 204
            # download .docx → docx media type
            r = await c.get(f"/{SROOT}/outputs/draft.docx")
            assert r.status_code == 200
            assert r.content == b"DOCXBYTES"
            assert "wordprocessingml" in r.headers["content-type"]
            # 비-docx → octet-stream branch
            r = await c.put(
                f"/{SROOT}/outputs/notes.txt",
                files={"file": ("notes.txt", b"hello", "text/plain")},
            )
            assert r.status_code == 204
            r = await c.get(f"/{SROOT}/outputs/notes.txt")
            assert r.status_code == 200
            assert r.content == b"hello"
            assert r.headers["content-type"].startswith("application/octet-stream")
            # 이제 list 가 두 파일 반환
            r = await c.get(f"/{SROOT}/outputs")
            assert sorted(r.json()["files"]) == ["draft.docx", "notes.txt"]

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# runtime — list_chains + create_chain_endpoint
# ───────────────────────────────────────────────────────────────────────────


def test_runtime_list_empty(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get(f"/{SROOT}/runtime")
            assert r.status_code == 200
            body = r.json()
            assert body["chains"] == []
            assert body["user_id"] == U
            assert body["work_id"] == INV
            assert "last_updated" in body

    asyncio.run(_run())


def test_runtime_create_chain_and_list(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # 명시 chain_id 로 생성
            r = await c.post(
                f"/{SROOT}/runtime",
                json={
                    "pipeline_id": "P02.R00.CONCEPT_MATURITY",
                    "persona": 2,
                    "chain_id": "chain-A",
                    "trigger": {"kind": "user"},
                },
            )
            assert r.status_code == 201
            m = r.json()
            assert m["chain_id"] == "chain-A"
            assert m["pipeline_id"] == "P02.R00.CONCEPT_MATURITY"
            assert m["persona"] == 2
            assert m["status"] == "pending"
            # chain_id 미지정 → uuid 자동 생성 + trigger default(system)
            r = await c.post(
                f"/{SROOT}/runtime",
                json={"pipeline_id": "P01.R00.RESPOND", "persona": 1},
            )
            assert r.status_code == 201
            assert r.json()["trigger"] == {"kind": "system"}
            assert r.json()["chain_id"]
            # 인덱스 반영
            r = await c.get(f"/{SROOT}/runtime")
            ids = [x["chain_id"] for x in r.json()["chains"]]
            assert "chain-A" in ids
            assert len(ids) == 2

    asyncio.run(_run())


def test_admin_active_chains_endpoint(stub_s3, cm_app, asgi_client):
    """GET /admin/active-chains — 전 세션 미완(pending/active) chain 열거 (DRO 재시작 복구, A-3)."""

    async def _run():
        async with asgi_client(cm_app) as c:
            await c.post(
                f"/{SROOT}/runtime",
                json={"pipeline_id": "P02.R00.X", "persona": 2, "chain_id": "chain-R"},
            )
            r = await c.get("/admin/active-chains")
            assert r.status_code == 200
            chains = r.json()["chains"]
            entry = next(ch for ch in chains if ch["chain_id"] == "chain-R")
            assert entry["user_id"] == U and entry["work_id"] == INV
            assert entry["status"] == "pending"

    asyncio.run(_run())


def test_runtime_create_chain_errors(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # pipeline_id 누락 → 400
            r = await c.post(f"/{SROOT}/runtime", json={"persona": 2})
            assert r.status_code == 400
            assert r.json()["detail"] == "pipeline_id required"
            # persona 누락 → 400
            r = await c.post(f"/{SROOT}/runtime", json={"pipeline_id": "P02.R00.X"})
            assert r.status_code == 400
            assert r.json()["detail"] == "persona required (1~6)"
            # persona 범위 밖 → 400
            r = await c.post(f"/{SROOT}/runtime", json={"pipeline_id": "P02.R00.X", "persona": 9})
            assert r.status_code == 400
            # persona non-int → 400
            r = await c.post(f"/{SROOT}/runtime", json={"pipeline_id": "P02.R00.X", "persona": "2"})
            assert r.status_code == 400

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# conversation
# ───────────────────────────────────────────────────────────────────────────


def test_conversation_get_append_pointer(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # 없음 → 404
            r = await c.get(f"/{SROOT}/runtime/00.dro/conversation")
            assert r.status_code == 404
            assert r.json()["detail"] == "conversation not found"
            # append (user turn → total_user_turns++)
            r = await c.post(
                f"/{SROOT}/runtime/00.dro/conversation/append",
                json={"role": "user", "content": "hi"},
            )
            assert r.status_code == 201
            assert r.json()["total_user_turns"] == 1
            # append assistant turn
            r = await c.post(
                f"/{SROOT}/runtime/00.dro/conversation/append",
                json={"role": "assistant", "content": "hello"},
            )
            assert r.status_code == 201
            # 전체 GET
            r = await c.get(f"/{SROOT}/runtime/00.dro/conversation")
            assert r.status_code == 200
            assert len(r.json()["messages"]) == 2
            # pointer 부분 read (정상)
            r = await c.get(
                f"/{SROOT}/runtime/00.dro/conversation",
                params={"pointer": "/messages/0/role"},
            )
            assert r.status_code == 200
            assert r.json() == "user"
            # pointer 잘못 → 400
            r = await c.get(
                f"/{SROOT}/runtime/00.dro/conversation",
                params={"pointer": "/messages/99/role"},
            )
            assert r.status_code == 400
            assert "invalid pointer" in r.json()["detail"]

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# media — work-level presigned S3 direct
# ───────────────────────────────────────────────────────────────────────────


def test_media_presign_put_endpoint(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post(
                f"/{SROOT}/media/presign-put",
                json={
                    "media_id": "m-1",
                    "ext": "png",
                    "mime": "image/png",
                    "max_bytes": 1024,
                    "ttl": 300,
                },
            )
            assert r.status_code == 200
            body = r.json()
            assert body["key"] == vm.media_key(U, INV, "m-1", "png")
            assert body["url"].startswith("https://")
            assert body["fields"]["Content-Type"] == "image/png"

    asyncio.run(_run())


def test_media_presign_get_endpoint_found(stub_s3, cm_app, asgi_client):
    mem = stub_s3

    async def _run():
        mem[vm.media_key(U, INV, "m-2", "jpg")] = b"img"
        async with asgi_client(cm_app) as c:
            r = await c.post(
                f"/{SROOT}/media/presign-get",
                json={"media_id": "m-2", "ttl": 120},
            )
            assert r.status_code == 200
            assert r.json()["url"].startswith("https://")

    asyncio.run(_run())


def test_media_presign_get_endpoint_missing_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post(
                f"/{SROOT}/media/presign-get",
                json={"media_id": "no-such", "ttl": 120},
            )
            assert r.status_code == 404
            assert r.json()["detail"] == "media not found"

    asyncio.run(_run())


def test_media_presign_put_missing_field_400(stub_s3, cm_app, asgi_client):
    # 필수 본문 필드 누락 → KeyError→500 아니라 400 (입력검증)
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post(f"/{SROOT}/media/presign-put", json={"ext": "png", "mime": "image/png"})
            assert r.status_code == 400
            assert "media_id" in r.json()["detail"]

    asyncio.run(_run())


def test_media_presign_put_bad_int_400(stub_s3, cm_app, asgi_client):
    # 정수 필드가 비정수 → int() ValueError→500 아니라 400
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post(
                f"/{SROOT}/media/presign-put",
                json={
                    "media_id": "m",
                    "ext": "png",
                    "mime": "image/png",
                    "max_bytes": "huge",
                    "ttl": 300,
                },
            )
            assert r.status_code == 400
            assert "max_bytes" in r.json()["detail"]

    asyncio.run(_run())


def test_media_presign_get_missing_field_400(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.post(f"/{SROOT}/media/presign-get", json={"ttl": 120})
            assert r.status_code == 400
            assert "media_id" in r.json()["detail"]

    asyncio.run(_run())


def test_media_list_endpoint(stub_s3, cm_app, asgi_client):
    mem = stub_s3

    async def _run():
        from src import store

        mem[vm.media_key(U, INV, "m-a", "png")] = b"aaa"
        store._s3_client.content_types[vm.media_key(U, INV, "m-a", "png")] = "image/png"
        mem[vm.media_key(U, INV, "m-b", "pdf")] = b"bbbb"
        async with asgi_client(cm_app) as c:
            r = await c.get(f"/{SROOT}/media")
            assert r.status_code == 200
            items = r.json()["items"]
            assert [it["media_id"] for it in items] == ["m-a", "m-b"]
            assert items[0]["mime"] == "image/png"
            assert items[1]["mime"] == "application/octet-stream"

    asyncio.run(_run())


def test_media_delete_endpoint(stub_s3, cm_app, asgi_client):
    mem = stub_s3

    async def _run():
        key = vm.media_key(U, INV, "m-del", "png")
        mem[key] = b"data"
        async with asgi_client(cm_app) as c:
            r = await c.request("DELETE", f"/{SROOT}/media/m-del")
            assert r.status_code == 200
            assert r.json()["deleted"] == 1
            assert key not in mem
            # 멱등 — 두 번째는 0
            r = await c.request("DELETE", f"/{SROOT}/media/m-del")
            assert r.status_code == 200
            assert r.json()["deleted"] == 0

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# persona queue
# ───────────────────────────────────────────────────────────────────────────


def test_persona_queue_lifecycle(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            p = "03.finder"
            base = f"/{SROOT}/runtime/{p}/queue"
            # empty queue GET
            r = await c.get(base)
            assert r.status_code == 200
            assert r.json()["pending"] == []
            assert r.json()["leases"] == {}
            # pop 빈 큐 → empty True
            r = await c.post(f"{base}/pop", json={})
            assert r.status_code == 200
            assert r.json() == {"empty": True}
            # push
            r = await c.post(f"{base}/push", json={"rt_id": "rt-1", "chain_id": "c-1"})
            assert r.status_code == 200
            assert r.json()["pending"][0]["rt_id"] == "rt-1"
            # push 두번째
            r = await c.post(f"{base}/push", json={"rt_id": "rt-2", "chain_id": "c-1"})
            assert r.status_code == 200
            # pop (head → lease) with actor + ttl
            r = await c.post(f"{base}/pop", json={"actor": "300.Actor", "lease_ttl_s": 60})
            assert r.status_code == 200
            assert r.json()["rt_id"] == "rt-1"
            r = await c.get(base)
            lease = r.json()["leases"]["rt-1"]
            assert lease["actor"] == "300.Actor"
            assert lease["expires_at"] > lease["started_at"]
            # release — 본인 rt_id 만 해제
            r = await c.post(f"{base}/release", json={"rt_id": "rt-1"})
            assert r.status_code == 200
            assert "rt-1" not in r.json()["leases"]

    asyncio.run(_run())


def test_persona_queue_errors(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # 잘못된 persona dir → 400 (_persona_dir_for)
            r = await c.get(f"/{SROOT}/runtime/99.bogus/queue")
            assert r.status_code == 400
            assert "unknown persona dir" in r.json()["detail"]
            # push 시 rt_id/chain_id 누락 → 400
            r = await c.post(f"/{SROOT}/runtime/01.buddy/queue/push", json={"rt_id": "only"})
            assert r.status_code == 400
            assert r.json()["detail"] == "rt_id, chain_id required"
            # pop 도 잘못된 persona → 400
            r = await c.post(f"/{SROOT}/runtime/bad/queue/pop", json={})
            assert r.status_code == 400
            # release 잘못된 persona → 400
            r = await c.post(f"/{SROOT}/runtime/bad/queue/release", json={"rt_id": "rt-1"})
            assert r.status_code == 400
            # release rt_id 누락 → 400
            r = await c.post(f"/{SROOT}/runtime/01.buddy/queue/release", json={})
            assert r.status_code == 400
            assert r.json()["detail"] == "rt_id required"

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# dialog — get/put/patch + _validate_dialog
# ───────────────────────────────────────────────────────────────────────────


def test_dialog_get_put_patch(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # 02.director / analysis 는 allowlist
            base = f"/{SROOT}/runtime/02.director/dialog/analysis"
            # 없음 → 404
            r = await c.get(base)
            assert r.status_code == 404
            assert r.json()["detail"] == "dialog.analysis not found"
            # PUT 204
            r = await c.put(base, json={"turns": []})
            assert r.status_code == 204
            # GET 200
            r = await c.get(base)
            assert r.status_code == 200
            assert r.json() == {"turns": []}
            # PATCH (RFC6902)
            r = await c.patch(base, json=[{"op": "add", "path": "/note", "value": "x"}])
            assert r.status_code == 200
            assert r.json()["note"] == "x"

    asyncio.run(_run())


def test_dialog_validation_errors(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # 잘못된 persona dir → 400 (_persona_dir_for inside _validate_dialog)
            r = await c.get(f"/{SROOT}/runtime/77.nope/dialog/analysis")
            assert r.status_code == 400
            assert "unknown persona dir" in r.json()["detail"]
            # valid persona, 비-allowlist name → 400
            r = await c.get(f"/{SROOT}/runtime/02.director/dialog/not_a_dialog")
            assert r.status_code == 400
            assert "unknown dialog" in r.json()["detail"]
            # 01.buddy 는 dialog allowlist 비어있음 → 어떤 name 도 400
            r = await c.get(f"/{SROOT}/runtime/01.buddy/dialog/anything")
            assert r.status_code == 400
            # PUT 도 동일 validation
            r = await c.put(f"/{SROOT}/runtime/02.director/dialog/bogus", json={"x": 1})
            assert r.status_code == 400
            # PATCH 도 동일 validation
            r = await c.patch(
                f"/{SROOT}/runtime/02.director/dialog/bogus",
                json=[{"op": "add", "path": "/x", "value": 1}],
            )
            assert r.status_code == 400

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# chain — get/patch + trail + RT + agent_state (persona-scoped)
# ───────────────────────────────────────────────────────────────────────────


def test_chain_get_patch_and_trail(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            p = "02.director"
            cid = "chain-X"
            # 먼저 chain 생성 (manifest 인덱스에도 등록)
            r = await c.post(
                f"/{SROOT}/runtime",
                json={"pipeline_id": "P02.R00.X", "persona": 2, "chain_id": cid},
            )
            assert r.status_code == 201
            # GET chain
            r = await c.get(f"/{SROOT}/runtime/{p}/{cid}")
            assert r.status_code == 200
            assert r.json()["chain_id"] == cid
            assert r.json()["status"] == "pending"
            # PATCH chain — /status mirror → runtime manifest 반영
            r = await c.patch(
                f"/{SROOT}/runtime/{p}/{cid}",
                json=[{"op": "replace", "path": "/status", "value": "running"}],
            )
            assert r.status_code == 200
            assert r.json()["status"] == "running"
            # runtime manifest 에 mirror 됐는지
            r = await c.get(f"/{SROOT}/runtime")
            entry = next(x for x in r.json()["chains"] if x["chain_id"] == cid)
            assert entry["status"] == "running"
            # trail — 비어있을 때 GET (빈 ndjson)
            r = await c.get(f"/{SROOT}/runtime/{p}/{cid}/trail")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("application/x-ndjson")
            assert r.content == b""
            # trail append
            r = await c.post(
                f"/{SROOT}/runtime/{p}/{cid}/trail",
                json={"event": "rt_started", "rt_id": "rt-1"},
            )
            assert r.status_code == 200
            assert r.json() == {"appended": True}
            # trail GET 후 1줄
            r = await c.get(f"/{SROOT}/runtime/{p}/{cid}/trail")
            assert r.content.decode().count("\n") == 1
            assert b"rt_started" in r.content

    asyncio.run(_run())


def test_chain_get_404(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # 미존재 chain → 404
            r = await c.get(f"/{SROOT}/runtime/02.director/no-such-chain")
            assert r.status_code == 404
            assert "no-such-chain" in r.json()["detail"]
            # 잘못된 persona dir → 400
            r = await c.get(f"/{SROOT}/runtime/zz.bad/some-chain")
            assert r.status_code == 400

    asyncio.run(_run())


def test_rt_create_get_patch(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            p = "04.thinker"
            cid = "chain-RT"
            # create RT (rt_id 명시)
            r = await c.post(
                f"/{SROOT}/runtime/{p}/{cid}/rts",
                json={"rt_id": "rt-A", "step_id": "s0"},
            )
            assert r.status_code == 201
            assert r.json()["rt_id"] == "rt-A"
            assert r.json()["state"] == "pending"
            assert r.json()["chain_id"] == cid
            # create RT (rt_id 없음 → 자동 uuid, chain_id 다름 → 교정)
            r = await c.post(
                f"/{SROOT}/runtime/{p}/{cid}/rts",
                json={"step_id": "s1", "chain_id": "WRONG"},
            )
            assert r.status_code == 201
            assert r.json()["rt_id"]
            assert r.json()["chain_id"] == cid
            # GET RT
            r = await c.get(f"/{SROOT}/runtime/{p}/{cid}/rts/rt-A")
            assert r.status_code == 200
            assert r.json()["step_id"] == "s0"
            # GET RT 404
            r = await c.get(f"/{SROOT}/runtime/{p}/{cid}/rts/nope")
            assert r.status_code == 404
            assert "nope" in r.json()["detail"]
            # PATCH RT (일반 op)
            r = await c.patch(
                f"/{SROOT}/runtime/{p}/{cid}/rts/rt-A",
                json=[{"op": "replace", "path": "/state", "value": "done"}],
            )
            assert r.status_code == 200
            assert r.json()["state"] == "done"
            # PATCH RT — sse_events_append 특수 path
            r = await c.patch(
                f"/{SROOT}/runtime/{p}/{cid}/rts/rt-A",
                json=[
                    {
                        "op": "add",
                        "path": "/sse_events_append",
                        "value": [{"type": "delta", "text": "a"}],
                    }
                ],
            )
            assert r.status_code == 200
            assert len(r.json()["sse_events"]) == 1
            assert r.json()["sse_events"][0]["text"] == "a"

    asyncio.run(_run())


def test_rt_errors_persona(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # create RT 잘못된 persona → 400
            r = await c.post(f"/{SROOT}/runtime/bad/c/rts", json={"rt_id": "x"})
            assert r.status_code == 400
            # GET RT 잘못된 persona → 400
            r = await c.get(f"/{SROOT}/runtime/bad/c/rts/x")
            assert r.status_code == 400
            # PATCH RT 잘못된 persona → 400
            r = await c.patch(
                f"/{SROOT}/runtime/bad/c/rts/x", json=[{"op": "add", "path": "/a", "value": 1}]
            )
            assert r.status_code == 400
            # trail append/get 잘못된 persona → 400
            r = await c.post(f"/{SROOT}/runtime/bad/c/trail", json={"event": "e"})
            assert r.status_code == 400
            r = await c.get(f"/{SROOT}/runtime/bad/c/trail")
            assert r.status_code == 400
            # patch_chain 잘못된 persona → 400
            r = await c.patch(
                f"/{SROOT}/runtime/bad/c", json=[{"op": "add", "path": "/a", "value": 1}]
            )
            assert r.status_code == 400

    asyncio.run(_run())


def test_agent_state_get_put(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            p = "05.crafter"
            cid = "chain-AS"
            # 없음 → default = 빈 envelope 동형 (404 아님, messages 키 없음)
            r = await c.get(f"/{SROOT}/runtime/{p}/{cid}/agent_state")
            assert r.status_code == 200
            assert r.json()["persona"] == 5
            assert r.json()["items"] == []
            assert r.json()["vendor"] is None
            assert "messages" not in r.json()
            # PUT — body(envelope) pass-through (내용은 CM 에 opaque)
            env = {
                "schema_version": 1,
                "vendor": "claude",
                "model": "claude-opus-4-7",
                "items": [{"type": "user", "uuid": "u1", "sessionId": "s"}],
            }
            r = await c.put(f"/{SROOT}/runtime/{p}/{cid}/agent_state", json=env)
            assert r.status_code == 200
            assert r.json()["items"] == env["items"]
            assert r.json()["vendor"] == "claude"
            assert r.json()["persona"] == 5  # CM 스탬프
            # GET 후 영속화 반영
            r = await c.get(f"/{SROOT}/runtime/{p}/{cid}/agent_state")
            assert r.status_code == 200
            assert r.json()["model"] == "claude-opus-4-7"
            # 잘못된 persona → 400
            r = await c.get(f"/{SROOT}/runtime/bad/{cid}/agent_state")
            assert r.status_code == 400
            r = await c.put(f"/{SROOT}/runtime/bad/{cid}/agent_state", json={})
            assert r.status_code == 400

    asyncio.run(_run())


# ───────────────────────────────────────────────────────────────────────────
# chains-by-id aliases — _resolve_persona_by_chain
# ───────────────────────────────────────────────────────────────────────────


def test_chains_by_id_aliases(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            p = "06.inspector"
            cid = "chain-BYID"
            # chain 생성 (persona 6) — manifest 인덱스 등록 → resolve 가능
            r = await c.post(
                f"/{SROOT}/runtime",
                json={"pipeline_id": "P06.R00.X", "persona": 6, "chain_id": cid},
            )
            assert r.status_code == 201
            # RT + trail 도 추가
            r = await c.post(
                f"/{SROOT}/runtime/{p}/{cid}/rts", json={"rt_id": "rt-Z", "step_id": "s"}
            )
            assert r.status_code == 201
            r = await c.post(f"/{SROOT}/runtime/{p}/{cid}/trail", json={"event": "started"})
            assert r.status_code == 200
            # GET /chains/{chain_id} — persona 자동탐색
            r = await c.get(f"/{SROOT}/chains/{cid}")
            assert r.status_code == 200
            assert r.json()["chain_id"] == cid
            assert r.json()["persona"] == 6
            # GET /chains/{chain_id}/trail
            r = await c.get(f"/{SROOT}/chains/{cid}/trail")
            assert r.status_code == 200
            assert b"started" in r.content
            assert r.headers["content-type"].startswith("application/x-ndjson")
            # GET /chains/{chain_id}/rts/{rt_id}
            r = await c.get(f"/{SROOT}/chains/{cid}/rts/rt-Z")
            assert r.status_code == 200
            assert r.json()["rt_id"] == "rt-Z"
            # rt_id 미존재 → 404
            r = await c.get(f"/{SROOT}/chains/{cid}/rts/no-rt")
            assert r.status_code == 404

    asyncio.run(_run())


def test_chains_by_id_unresolvable(stub_s3, cm_app, asgi_client):
    async def _run():
        async with asgi_client(cm_app) as c:
            # manifest 에 없는 chain → _resolve_persona_by_chain 404
            r = await c.get(f"/{SROOT}/chains/ghost-chain")
            assert r.status_code == 404
            assert "ghost-chain" in r.json()["detail"]
            r = await c.get(f"/{SROOT}/chains/ghost-chain/trail")
            assert r.status_code == 404
            r = await c.get(f"/{SROOT}/chains/ghost-chain/rts/rt-x")
            assert r.status_code == 404

    asyncio.run(_run())


def test_chain_by_id_resolved_but_body_missing(stub_s3, cm_app, asgi_client):
    """manifest 인덱스에는 (valid persona) chain entry 가 있는데 chain 본체(manifest.json)는
    없는 경우 → _resolve_persona_by_chain 이 persona 반환 + get_chain None → 404 (line 834)."""

    async def _run():
        from src import chain_store

        # manifest 인덱스에 persona=2 chain 추가 (chain 본체 manifest.json 은 안 만듦)
        await chain_store.add_chain_to_manifest(U, INV, "orphan", "P02.R00.X", 2)
        async with asgi_client(cm_app) as c:
            r = await c.get(f"/{SROOT}/chains/orphan")
            assert r.status_code == 404
            assert "orphan" in r.json()["detail"]

    asyncio.run(_run())
