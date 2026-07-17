"""100.Nexus gateway router 핸들러 — invoke 단위테스트 (≥99% line).

대상: 100.Nexus/src/router.py 의 게이트웨이 핸들러 (C1 정규화 후 경로/메서드):
  roadmap_submit    : PATCH .../estimate/roadmap/{item_id} (본문 {value} → 200 RoadmapItem / 없는 id→404 / value 없음·빈→422)
  media_upload_url  : POST .../media (201 PresignUploadResponse / work 404 / 미허용 MIME 422 / 상한 409)
  media_list        : GET  .../media (200 MediaListResponse)
  media_download_url: GET  .../media/{id} (200 MediaDownloadResponse 메타+url / 없음→404)
  media_delete      : DELETE .../media/{id} (204, 멱등)
  thread_stream     : WS 인증·guard (token 거부 4401 / work-guard 4404 / JWT 만료·lifetime cap / happy·replay·inbound예외)

media 는 presigned S3 직접 — 바이트 서버 미경유. router 는 get_cm_client() 의 presign/list/delete
+ venezia_media_config 만 호출. CM 은 _FakeCM 으로, media config 는 harness 가 MEDIA_CONFIG_FILE
(@deployment/media.config.yaml) 로 주입 (allowed_mime 에 image/png 등, max_files_per_work=50).

app 조립·dependency_overrides·monkeypatch 패턴은 동일 suite 의 test_router.py 와 동일.
src.router.handle_message + src.router.get_cm_client 을 monkeypatch.
async 테스트는 suite 패턴대로 동기 def 안에서 asyncio.run(...) 로 호출.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI, WebSocketDisconnect  # noqa: E402
from src import errors  # noqa: E402
from src import event_consumer  # noqa: E402
from src import router as router_mod  # noqa: E402
from src.auth import get_current_user  # noqa: E402
from src.router import router, thread_stream  # noqa: E402

_UID = "u-1"
_WORK = "work-1"


# ── fakes ──────────────────────────────────────────────────────────────────


class _FakeCM:
    """get_cm_client() 대체 — media presign/list/delete + manifest(소유권 확인) 구현."""

    def __init__(
        self,
        *,
        manifest=None,
        presign_put=None,
        presign_get="UNSET",
        media_items=None,
        roadmap=None,
    ) -> None:
        # manifest: None → work 없음(404). dict → 존재.
        self._manifest = manifest
        self._presign_put = presign_put or {
            "url": "https://s3.example/post",
            "fields": {"key": "k", "policy": "p", "x-amz-signature": "sig"},
            "key": "sessions/u-1/work-1/media/m-new.png",
        }
        # presign_get: "UNSET" → 기본 url dict. None → 404. dict → 그 값.
        self._presign_get = presign_get
        self._media_items = media_items if media_items is not None else []
        # roadmap: UR(top-level array) — get_user_roadmap(읽기)/set_roadmap_item(id 기준 갱신) 용.
        self._roadmap = roadmap if roadmap is not None else []
        self.put_calls: list[tuple] = []
        self.get_calls: list[tuple] = []
        self.delete_calls: list[tuple] = []
        self.roadmap_patch_calls: list[tuple] = []
        self._idem: dict = {}  # Idempotency-Key 영속 store (C3) — in-memory round-trip

    async def get_context_manifest(self, user_id, work_id):
        return self._manifest

    async def get_user_roadmap(self, user_id, work_id):
        return self._roadmap

    async def set_roadmap_item(self, user_id, work_id, item_id, fields):
        # 실 CM 처럼 id 로 찾아 fields 병합 (index 아님) — 못 찾으면 None.
        self.roadmap_patch_calls.append((user_id, work_id, item_id, fields))
        for it in self._roadmap:
            if isinstance(it, dict) and it.get("id") == item_id:
                it.update(fields)
                return it
        return None

    async def request_presigned_put(self, user_id, work_id, media_id, ext, mime, max_bytes, ttl):
        self.put_calls.append((user_id, work_id, media_id, ext, mime, max_bytes, ttl))
        return self._presign_put

    async def request_presigned_get(self, user_id, work_id, media_id, ttl):
        self.get_calls.append((user_id, work_id, media_id, ttl))
        if self._presign_get == "UNSET":
            return {"url": "https://s3.example/get"}
        return self._presign_get

    async def list_media(self, user_id, work_id):
        return self._media_items

    async def delete_media(self, user_id, work_id, media_id):
        self.delete_calls.append((user_id, work_id, media_id))

    async def claim_idempotency(self, user_id, key):
        rec = self._idem.get((user_id, key))
        if rec is not None:
            if rec.get("body") is not None:
                return ("done", rec)
            return ("in_flight", None)
        self._idem[(user_id, key)] = {"claimed_at": "x"}
        return ("claimed", None)

    async def put_idempotency(self, user_id, key, record):
        self._idem[(user_id, key)] = record

    async def delete_idempotency(self, user_id, key):
        self._idem.pop((user_id, key), None)


class _FakeWebSocket:
    """thread_stream 용 최소 WebSocket. close/accept 기록 + receive_text 스크립트."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        inbound: list[str] | None = None,
        cookies: dict[str, str] | None = None,
        hang: bool = False,
    ) -> None:
        self.headers = headers or {}
        self.cookies = cookies or {}  # 쿠키 인증 (nx_access) — handshake 자동 첨부
        self.closed_with: int | None = None
        self.accepted = False
        self.accept_subprotocol: object = "UNSET"
        self._hang = hang  # True 면 receive_text 가 무한 대기 → deadline timeout 경로 테스트
        # 스크립트 소진 후 WebSocketDisconnect 로 루프 종료
        self._inbound = list(inbound or [])

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    async def accept(self, subprotocol=None) -> None:
        self.accepted = True
        self.accept_subprotocol = subprotocol

    async def receive_text(self) -> str:
        if self._hang:
            await asyncio.sleep(3600)
        if self._inbound:
            return self._inbound.pop(0)
        raise WebSocketDisconnect(code=1000)


class _FakeRegistry:
    """thread_stream 이 호출하는 registry 메서드만 기록."""

    def __init__(self) -> None:
        self.added: list[tuple] = []
        self.removed: list[tuple] = []
        self.replayed: list[tuple] = []

    async def add(self, user_id, work_id, ws) -> int:
        self.added.append((user_id, work_id, ws))
        return 1

    async def remove(self, user_id, work_id, ws) -> int:
        self.removed.append((user_id, work_id, ws))
        return 0

    async def replay_since(self, user_id, work_id, ws, since_seq) -> None:
        self.replayed.append((user_id, work_id, since_seq))


def _patch_ws_runtime(monkeypatch, *, registry, inbound_handler, work_exists=True):
    """thread_stream happy-path 의 외부 의존(work-guard CM·registry·consumer·inbound) monkeypatch.
    기본 OPEN 모드 강제 — SECURE JWT decode 분기는 별도 테스트에서 커버."""
    monkeypatch.setattr(router_mod.settings, "AUTH_MODE", "OPEN")

    class _GuardCM:
        async def get_context_manifest(self, user_id, work_id):
            return {"title": "x"} if work_exists else None

    monkeypatch.setattr(router_mod, "get_cm_client", lambda: _GuardCM())
    monkeypatch.setattr(router_mod, "get_production_ws_registry", lambda: registry)
    acquired: list[tuple] = []
    released: list[tuple] = []

    async def _acquire(user_id, work_id):
        acquired.append((user_id, work_id))

    async def _release(user_id, work_id):
        released.append((user_id, work_id))

    monkeypatch.setattr(event_consumer, "acquire", _acquire)
    monkeypatch.setattr(event_consumer, "release", _release)
    monkeypatch.setattr(router_mod.ws_inbound, "handle_inbound", inbound_handler)
    return acquired, released


# ── app assembly ─────────────────────────────────────────────────────────────


def _build_app(monkeypatch, *, user=None, cm=None, handle=None):
    app = FastAPI()
    errors.install(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: (user or {"user_id": _UID})
    if cm is not None:
        monkeypatch.setattr(router_mod, "get_cm_client", lambda: cm)
    if handle is not None:
        monkeypatch.setattr(router_mod, "handle_message", handle)
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _run(coro):
    return asyncio.run(coro)


def _post(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.post(url, **kw)

    return _run(go())


def _get(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.get(url, **kw)

    return _run(go())


def _delete(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.delete(url, **kw)

    return _run(go())


def _patch(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.patch(url, **kw)

    return _run(go())


# ── roadmap 답변 PATCH /estimate/roadmap/{item_id} ───────────────────────────


def _roadmap_item(item_id="r1", input_type="chat", options=None):
    return {
        "id": item_id,
        "title": "제목",
        "description": "설명",
        "status": "pending",
        "priority": 1,
        "input_type": input_type,
        "options": options,
        "answer": None,
    }


def test_roadmap_submit_ok(monkeypatch):
    # PATCH .../roadmap/{item_id}, 본문 {value} 만 → Nexus 가 항목 answer+status 즉시 기록 →
    # 갱신된 RoadmapItem 반환. input_type 은 저장 항목에서 도출(본문에 없음).
    seen: list[dict] = []

    async def _handle(*, user_id, work_id, content, user_turn_meta):
        seen.append(
            {
                "user_id": user_id,
                "work_id": work_id,
                "content": content,
                "meta": user_turn_meta,
            }
        )

    cm = _FakeCM(manifest={"title": "T"}, roadmap=[_roadmap_item("r1", "chat")])
    app = _build_app(monkeypatch, cm=cm, handle=_handle)
    r = _patch(app, f"/api/v1/works/{_WORK}/estimate/roadmap/r1", json={"value": "내 답변"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "r1"
    assert body["status"] == "satisfied"
    assert body["answer"]["value"] == "내 답변"
    assert len(cm.roadmap_patch_calls) == 1
    assert len(seen) == 1
    call = seen[0]
    assert call["user_id"] == _UID
    assert call["work_id"] == _WORK
    assert call["content"] == "내 답변"
    assert call["meta"] == {
        "kind": "roadmap.answer",
        "roadmap_item_id": "r1",
        "input_type": "chat",  # 서버가 항목에서 도출
    }


def test_roadmap_submit_list_value_joined(monkeypatch):
    # value 가 list → ", ".join 으로 content 합성 (selection/keyword 다중)
    seen: list[str] = []

    async def _handle(*, user_id, work_id, content, user_turn_meta):
        seen.append(content)

    cm = _FakeCM(roadmap=[_roadmap_item("r2", "selection", options=["a", "b"])])
    app = _build_app(monkeypatch, cm=cm, handle=_handle)
    r = _patch(app, f"/api/v1/works/{_WORK}/estimate/roadmap/r2", json={"value": ["a", "b"]})
    assert r.status_code == 200
    assert seen == ["a, b"]
    assert r.json()["answer"]["value"] == ["a", "b"]


def test_roadmap_submit_item_not_found_404(monkeypatch):
    # item_id 는 URI 인데 로드맵에 없는 id → 404 (handle_message 미호출)
    called: list[int] = []

    async def _handle(**kw):
        called.append(1)

    cm = _FakeCM(roadmap=[_roadmap_item("r1", "chat")])
    app = _build_app(monkeypatch, cm=cm, handle=_handle)
    r = _patch(app, f"/api/v1/works/{_WORK}/estimate/roadmap/nope", json={"value": "x"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert called == []


def test_roadmap_submit_value_none_422(monkeypatch):
    # value 검증은 로드맵 fetch 전 — cm 불필요
    async def _handle(**kw):  # pragma: no cover - 호출되면 안 됨
        raise AssertionError("handle_message should not run")

    app = _build_app(monkeypatch, handle=_handle)
    r = _patch(app, f"/api/v1/works/{_WORK}/estimate/roadmap/r1", json={"value": None})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_roadmap_submit_empty_content_422(monkeypatch):
    # value 가 공백 문자열 → content.strip() 비어 두 번째 422 분기 (cm 도달 전)
    async def _handle(**kw):  # pragma: no cover - 호출되면 안 됨
        raise AssertionError("handle_message should not run")

    app = _build_app(monkeypatch, handle=_handle)
    r = _patch(app, f"/api/v1/works/{_WORK}/estimate/roadmap/r1", json={"value": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_roadmap_submit_invalid_value_type_422(monkeypatch):
    # value 가 str/list[str] 아님(숫자·dict·혼합리스트) → RoadmapAnswer 계약 위반 차단 422,
    # UR 미오염 (검증이 cm 도달 전 — handle_message·set_roadmap_item 미호출)
    async def _handle(**kw):  # pragma: no cover - 호출되면 안 됨
        raise AssertionError("handle_message should not run")

    app = _build_app(monkeypatch, handle=_handle)
    for bad in (123, {"x": 1}, [1, 2], ["ok", 2]):
        r = _patch(app, f"/api/v1/works/{_WORK}/estimate/roadmap/r1", json={"value": bad})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation_failed"


# ── POST /media (presigned 업로드 티켓 발급) ─────────────────────────────────


def test_media_upload_url_ok(monkeypatch):
    cm = _FakeCM(manifest={"title": "T"})
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"filename": "pic.png", "mime": "image/png"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["media_id"]  # uuid hex
    assert (
        r.headers["location"] == f"/api/v1/works/{_WORK}/media/{body['media_id']}"
    )  # 201+Location
    assert body["url"] == "https://s3.example/post"
    assert body["fields"] == {"key": "k", "policy": "p", "x-amz-signature": "sig"}
    assert body["key"] == "sessions/u-1/work-1/media/m-new.png"
    assert body["max_file_bytes"] == 20971520
    assert body["ttl"] == 600
    # request_presigned_put 호출 인자: ext='png' (filename 도출), mime, max_bytes, ttl
    assert len(cm.put_calls) == 1
    uid, wid, media_id, ext, mime, max_bytes, ttl = cm.put_calls[0]
    assert uid == _UID and wid == _WORK
    assert media_id == body["media_id"]
    assert ext == "png"
    assert mime == "image/png"
    assert max_bytes == 20971520
    assert ttl == 600


def test_media_upload_url_idempotency_replay(monkeypatch):
    # 같은 Idempotency-Key 재시도 → 같은 media_id + Location 재생, presigned 1회만 (D6)
    cm = _FakeCM(manifest={"title": "T"})
    app = _build_app(monkeypatch, cm=cm)
    hdr = {"Idempotency-Key": "media-key-1"}
    body = {"filename": "pic.png", "mime": "image/png"}
    r1 = _post(app, f"/api/v1/works/{_WORK}/media", json=body, headers=hdr)
    r2 = _post(app, f"/api/v1/works/{_WORK}/media", json=body, headers=hdr)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["media_id"] == r2.json()["media_id"]  # 같은 media_id 재생
    assert r1.headers["location"] == r2.headers["location"]
    assert len(cm.put_calls) == 1  # 2번째는 replay — presigned 재발급 안 함


def test_media_upload_url_idempotency_busy_409(monkeypatch):
    # 동일 키를 다른 요청이 처리 중(미완료 선점) → 409, presign 안 함
    cm = _FakeCM(manifest={"title": "T"})
    cm._idem[(_UID, "media:busy-k")] = {"claimed_at": "x"}  # in-flight 선점
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"filename": "p.png", "mime": "image/png"},
        headers={"Idempotency-Key": "busy-k"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"
    assert len(cm.put_calls) == 0


def test_media_upload_url_idempotency_release_on_4xx(monkeypatch):
    # 처리 중 4xx(미허용 MIME 422) → 선점 해제(보정 후 즉시 재시도 가능)
    cm = _FakeCM(manifest={"title": "T"})
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"filename": "a.zip", "mime": "application/zip"},
        headers={"Idempotency-Key": "rel-k"},
    )
    assert r.status_code == 422
    assert (_UID, "media:rel-k") not in cm._idem  # 선점 해제됨


def test_media_upload_url_idempotency_scope_isolated(monkeypatch):
    # works 가 같은 raw 키를 썼어도(works:K done) media 는 별 스코프 → 교차 replay 아님(정상 처리)
    cm = _FakeCM(manifest={"title": "T"})
    cm._idem[(_UID, "works:K")] = {
        "status": 201,
        "body": {"work_id": "w-other"},
        "location": "/api/v1/works/w-other",
    }
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"filename": "p.png", "mime": "image/png"},
        headers={"Idempotency-Key": "K"},
    )
    assert r.status_code == 201
    assert r.json()["media_id"]  # media 응답
    assert "work_id" not in r.json()  # works 응답 교차 replay 아님
    assert (_UID, "media:K") in cm._idem  # media 스코프로 별도 저장


def test_media_upload_url_safe_filename_ext_preserved(monkeypatch):
    # 안전한 filename 확장자는 보존 (mime 표준과 달라도) — jpeg ≠ jpg
    cm = _FakeCM(manifest={})
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"filename": "photo.jpeg", "mime": "image/jpeg"},
    )
    assert r.status_code == 201
    assert cm.put_calls[0][3] == "jpeg"


def test_media_upload_url_unsafe_filename_ext_falls_back_to_mime(monkeypatch):
    # filename 확장자에 '/'·공백·과길이·빈값 → 거부 후 mime 표준 ext
    # (nested 키 차단 → list_media/quota 우회 방지)
    cm = _FakeCM(manifest={})
    app = _build_app(monkeypatch, cm=cm)
    for bad in ("evil.a/b", "x..", "y.verylongext", "z.JP G"):
        cm.put_calls.clear()
        r = _post(
            app,
            f"/api/v1/works/{_WORK}/media",
            json={"filename": bad, "mime": "image/png"},
        )
        assert r.status_code == 201
        ext = cm.put_calls[0][3]
        assert "/" not in ext and ext == "png"


def test_media_upload_url_ext_from_mime_when_no_filename(monkeypatch):
    # filename 없음 → MIME → ext 도출 (application/pdf → pdf)
    cm = _FakeCM(manifest={})
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"mime": "application/pdf"},
    )
    assert r.status_code == 201
    assert cm.put_calls[0][3] == "pdf"


def test_media_upload_url_work_not_found_404(monkeypatch):
    # get_context_manifest None → _require_work 404
    cm = _FakeCM(manifest=None)
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"filename": "pic.png", "mime": "image/png"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert cm.put_calls == []


def test_media_upload_url_disallowed_mime_422(monkeypatch):
    # mime 이 allowed_mime 밖 → 422 validation_failed
    cm = _FakeCM(manifest={})
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"filename": "a.zip", "mime": "application/zip"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"
    assert cm.put_calls == []


def test_media_upload_url_count_cap_409(monkeypatch):
    # list_media 길이 ≥ max_files_per_work(50) → 409 conflict
    cm = _FakeCM(manifest={}, media_items=[{"media_id": f"m{i}"} for i in range(50)])
    app = _build_app(monkeypatch, cm=cm)
    r = _post(
        app,
        f"/api/v1/works/{_WORK}/media",
        json={"filename": "pic.png", "mime": "image/png"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"
    assert cm.put_calls == []


# ── media (list) ─────────────────────────────────────────────────────────────


def test_media_list_ok(monkeypatch):
    items = [
        {
            "media_id": "m1",
            "ext": "png",
            "key": "sessions/u-1/work-1/media/m1.png",
            "size_bytes": 10,
            "mime": "image/png",
        }
    ]
    cm = _FakeCM(manifest={}, media_items=items)
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/media")
    assert r.status_code == 200
    got = r.json()["items"]
    assert len(got) == 1
    item = got[0]
    assert item["media_id"] == "m1"
    assert item["ext"] == "png"
    assert item["key"] == "sessions/u-1/work-1/media/m1.png"
    assert item["size_bytes"] == 10
    assert item["mime"] == "image/png"
    assert item["last_modified"] is None


def test_media_list_work_not_found_404(monkeypatch):
    cm = _FakeCM(manifest=None)
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/media")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ── GET /media/{id} (메타 + presigned 다운로드 URL) ──────────────────────────


def test_media_download_url_ok(monkeypatch):
    # GET .../media/{id} → MediaItem 메타 + presigned url + ttl (자원 표현, redirect 아님)
    item = {
        "media_id": "m-1",
        "ext": "png",
        "key": "sessions/u-1/work-1/media/m-1.png",
        "size_bytes": 42,
        "mime": "image/png",
    }
    cm = _FakeCM(
        manifest={},
        media_items=[item],
        presign_get={"url": "https://s3.example/get?sig=abc"},
    )
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/media/m-1")
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "https://s3.example/get?sig=abc"
    assert body["ttl"] == 300
    assert body["media_id"] == "m-1"
    assert body["mime"] == "image/png"
    assert body["size_bytes"] == 42
    assert cm.get_calls == [(_UID, _WORK, "m-1", 300)]


def test_media_download_url_absent_404(monkeypatch):
    # 목록에 없는 media_id → 404 (presign 도달 전)
    cm = _FakeCM(manifest={}, media_items=[])
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/media/missing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert cm.get_calls == []  # presign 미도달


def test_media_download_url_presign_none_404(monkeypatch):
    # 목록엔 있으나 presigned-get None(불일치) → 404
    item = {
        "media_id": "m-1",
        "ext": "png",
        "key": "sessions/u-1/work-1/media/m-1.png",
        "size_bytes": 42,
        "mime": "image/png",
    }
    cm = _FakeCM(manifest={}, media_items=[item], presign_get=None)
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/media/m-1")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ── media/{id} (delete) ──────────────────────────────────────────────────────


def test_media_delete_204(monkeypatch):
    cm = _FakeCM()
    app = _build_app(monkeypatch, cm=cm)
    r = _delete(app, f"/api/v1/works/{_WORK}/media/m-1")
    assert r.status_code == 204
    assert not r.content
    assert cm.delete_calls == [(_UID, _WORK, "m-1")]


# ── thread/stream (WS) — 토큰 거부 경로만 (나머지는 endpoint 트랙) ──────────────


def test_thread_stream_no_token_closes_4401(monkeypatch):
    # 쿠키 없음 → token None → accept → user_id None → close(4401) + return (실 close code)
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: None)
    ws = _FakeWebSocket(cookies={})
    _run(thread_stream(ws, _WORK, since_seq=0))
    assert ws.closed_with == 4401
    assert ws.accepted is True  # accept-then-close → 실 WS close code 전달 (F1=A)


def test_thread_stream_bad_token_closes_4401(monkeypatch):
    # bearer + 잘못된 토큰 → user_id_from_token None → close(4401)
    seen: list[str | None] = []

    def _from_token(tok):
        seen.append(tok)
        return None

    monkeypatch.setattr(router_mod, "user_id_from_token", _from_token)
    ws = _FakeWebSocket(cookies={"nx_access": "badjwt"})
    _run(thread_stream(ws, _WORK, since_seq=0))
    assert ws.closed_with == 4401
    assert ws.accepted is True  # accept-then-close → 실 WS close code 전달 (F1=A)
    # nx_access 쿠키 → token = "badjwt"
    assert seen == ["badjwt"]


def test_thread_stream_accept_has_no_subprotocol(monkeypatch):
    # 쿠키 인증 — accept() 는 subprotocol echo 없이 호출 (subprotocol bearer 폐지).
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: None)
    ws = _FakeWebSocket(cookies={})
    _run(thread_stream(ws, _WORK, since_seq=0))
    assert ws.accepted is True  # accept-then-close
    assert ws.accept_subprotocol is None  # subprotocol echo 금지 (쿠키 인증)
    assert ws.closed_with == 4401  # 무쿠키 → token None


def test_thread_stream_happy_path_with_inbound_and_disconnect(monkeypatch):
    # 유효 쿠키 → accept() → add → acquire → 메시지 1건 inbound 처리
    # → WebSocketDisconnect → finally remove + release
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: _UID)
    registry = _FakeRegistry()
    handled: list[tuple] = []

    async def _inbound(websocket, raw, user_id, work_id):
        handled.append((raw, user_id, work_id))

    acquired, released = _patch_ws_runtime(monkeypatch, registry=registry, inbound_handler=_inbound)
    ws = _FakeWebSocket(
        cookies={"nx_access": "goodjwt"},
        inbound=['{"type":"ping"}'],
    )
    _run(thread_stream(ws, _WORK, since_seq=0))

    assert ws.accepted is True
    assert ws.accept_subprotocol is None
    assert registry.added == [(_UID, _WORK, ws)]
    assert acquired == [(_UID, _WORK)]
    assert handled == [('{"type":"ping"}', _UID, _WORK)]
    assert registry.replayed == []  # since_seq=0 → replay 안 함
    assert registry.removed == [(_UID, _WORK, ws)]
    assert released == [(_UID, _WORK)]
    assert ws.closed_with is None  # 정상 disconnect — 명시 close 없음


def test_thread_stream_replay_when_since_seq_positive(monkeypatch):
    # since_seq>0 → replay_since 호출. protocols 비어있으면 accept(subprotocol=None)
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: _UID)
    registry = _FakeRegistry()

    async def _inbound(websocket, raw, user_id, work_id):  # pragma: no cover - 미사용
        raise AssertionError("no inbound expected")

    _patch_ws_runtime(monkeypatch, registry=registry, inbound_handler=_inbound)
    # 쿠키 없어도 user_id_from_token monkeypatch 가 _UID 반환 → accept 진입.
    ws = _FakeWebSocket(cookies={})
    _run(thread_stream(ws, _WORK, since_seq=5))

    assert ws.accepted is True
    assert ws.accept_subprotocol is None
    assert registry.replayed == [(_UID, _WORK, 5)]
    assert registry.removed == [(_UID, _WORK, ws)]


def test_thread_stream_inbound_exception_is_logged_not_fatal(monkeypatch):
    # handle_inbound 가 raise → except 분기(log.exception) 로 흡수, 루프 계속.
    # 두 번째 receive_text 에서 WebSocketDisconnect → finally 정리.
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: _UID)
    registry = _FakeRegistry()
    calls: list[str] = []

    async def _inbound(websocket, raw, user_id, work_id):
        calls.append(raw)
        raise RuntimeError("boom in inbound")

    _, released = _patch_ws_runtime(monkeypatch, registry=registry, inbound_handler=_inbound)
    ws = _FakeWebSocket(
        cookies={"nx_access": "goodjwt"},
        inbound=["bad-msg"],
    )
    _run(thread_stream(ws, _WORK, since_seq=0))

    assert calls == ["bad-msg"]  # inbound 시도됨
    assert registry.removed == [(_UID, _WORK, ws)]  # 예외에도 finally 정리
    assert released == [(_UID, _WORK)]


def test_thread_stream_work_not_found_closes_4404(monkeypatch):
    # 유효 user_id 지만 work 미존재 → accept 후 work-guard 가 close(4404) (실 WS close code 전달).
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: _UID)
    registry = _FakeRegistry()

    async def _inbound(websocket, raw, user_id, work_id):  # pragma: no cover - 미도달
        raise AssertionError("guard 통과 안 돼야")

    _patch_ws_runtime(monkeypatch, registry=registry, inbound_handler=_inbound, work_exists=False)
    ws = _FakeWebSocket(cookies={"nx_access": "t"})
    _run(thread_stream(ws, _WORK, since_seq=0))
    assert ws.closed_with == 4404
    assert ws.accepted is True  # accept-then-close → 실 WS close code 전달 (F1=A)
    assert registry.added == []


def test_thread_stream_secure_valid_cookie_normal(monkeypatch):
    # SECURE + 유효 nx_access 쿠키 → 정상 흐름. deadline=12h 캡 단독(access exp 클램프 없음, C1f).
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: _UID)
    registry = _FakeRegistry()

    async def _inbound(websocket, raw, user_id, work_id):
        pass

    _patch_ws_runtime(monkeypatch, registry=registry, inbound_handler=_inbound)
    monkeypatch.setattr(router_mod.settings, "AUTH_MODE", "SECURE")
    ws = _FakeWebSocket(cookies={"nx_access": "goodjwt"}, inbound=['{"x":1}'])
    _run(thread_stream(ws, _WORK, since_seq=0))
    assert ws.accepted is True
    assert registry.removed == [(_UID, _WORK, ws)]


def test_thread_stream_expired_cookie_closes_4401(monkeypatch):
    # 만료/위조 nx_access 쿠키 → user_id_from_token None(decode 내부 HTTPException 흡수) → 4401.
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: None)
    registry = _FakeRegistry()

    async def _inbound(websocket, raw, user_id, work_id):  # pragma: no cover - 미도달
        raise AssertionError

    _patch_ws_runtime(monkeypatch, registry=registry, inbound_handler=_inbound)
    monkeypatch.setattr(router_mod.settings, "AUTH_MODE", "SECURE")
    ws = _FakeWebSocket(cookies={"nx_access": "expiredjwt"})
    _run(thread_stream(ws, _WORK, since_seq=0))
    assert ws.closed_with == 4401
    assert ws.accepted is True  # accept-then-close → 실 WS close code 전달 (F1=A)


def test_thread_stream_deadline_exceeded_closes_1001(monkeypatch):
    # 최대 lifetime cap=0 → accept 직후 deadline 초과 → wait_for timeout → close(1001 going-away, A-5).
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: _UID)
    registry = _FakeRegistry()

    async def _inbound(websocket, raw, user_id, work_id):  # pragma: no cover - 미도달
        raise AssertionError("deadline 전에 처리되면 안 돼")

    _patch_ws_runtime(monkeypatch, registry=registry, inbound_handler=_inbound)
    monkeypatch.setattr(router_mod.settings, "WS_MAX_LIFETIME_MINUTES", 0)
    ws = _FakeWebSocket(cookies={}, hang=True)
    _run(thread_stream(ws, _WORK, since_seq=0))
    assert ws.accepted is True  # accept 후 deadline 도달
    assert ws.closed_with == 1001  # 정기 수명 cap = going-away (인증 실패 4401 과 구분)
    assert registry.removed == [(_UID, _WORK, ws)]  # finally 정리


def test_thread_stream_acquire_failure_skips_release(monkeypatch):
    # acquire 실패 시 finally: remove(ws-identity 키 → 안전) 는 돌되 release 는 SKIP.
    # release 는 (user,work) 공유 refcount 를 깎으므로, 미-acquire 시 호출하면 같은 키의
    # 다른 활성 연결 SSE consumer 를 잘못 cancel 한다 → acquired=True 일 때만 release.
    monkeypatch.setattr(router_mod, "user_id_from_token", lambda tok: _UID)
    registry = _FakeRegistry()

    async def _inbound(websocket, raw, user_id, work_id):  # pragma: no cover - 미도달
        raise AssertionError

    _, released = _patch_ws_runtime(monkeypatch, registry=registry, inbound_handler=_inbound)

    async def _boom_acquire(user_id, work_id):
        raise RuntimeError("consumer start failed")

    monkeypatch.setattr(event_consumer, "acquire", _boom_acquire)
    ws = _FakeWebSocket(cookies={})
    with pytest.raises(RuntimeError):
        _run(thread_stream(ws, _WORK, since_seq=0))
    assert registry.removed == [(_UID, _WORK, ws)]  # remove 는 안전하게 실행
    assert released == []  # release 는 skip — 같은 키 다른 연결 보호
