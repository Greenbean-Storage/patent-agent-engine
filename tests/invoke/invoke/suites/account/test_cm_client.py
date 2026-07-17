"""100.Nexus cm_client — CM HTTP 클라이언트 (invoke 단위).

대상: 100.Nexus/src/cm_client.py. httpx.MockTransport handler 로 모든 메서드 구동.

분기 전수:
  get_identity                      : 200 / 404→None
  put_identity                      : PUT (body {user_id})
  get_profile                       : 200 / 404→None
  put_profile                       : PUT
  patch_profile                     : PATCH → json
  create_session                    : user_id 있음 / 없음 body 분기
  list_sessions                     : GET
  get_context_manifest              : 200 / 404→None
  patch_context_manifest            : PATCH → json
  append_conversation               : POST
  request_presigned_put             : POST presign-put → {url,fields,key}
  request_presigned_get             : POST presign-get 200 / 404→None
  list_media                        : GET → items
  delete_media                      : DELETE
  _model_get                        : pointer 있음 / 없음 / 404→None
  get_iom / get_concept_maturity_model
  get_user_roadmap / get_conversation : _model_get 위임
  get_drawing_manifest              : 200 / 404→None
  upload_document                   : 204 / 빈content→fallback / json ctype / 비-json→{}
  download_document                 : 200 bytes / 404→None
  aclose                            : client 종료
  get_cm_client                     : 싱글톤 (첫 호출 생성 + 재호출 동일 객체)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

import src.cm_client as cm_client  # noqa: E402
from src.cm_client import CMClient, get_cm_client  # noqa: E402


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> CMClient:
    """MockTransport handler 로 구동되는 CMClient. base_url 은 http://cm 고정."""
    c = CMClient(base_url="http://cm/")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


# ── 생성자 base 정규화 (rstrip "/") ─────────────────────────────────────────


def test_init_strips_trailing_slash():
    c = CMClient(base_url="http://cm/")
    assert c.base == "http://cm"
    assert c.timeout == 60.0


# ── users/ identity ─────────────────────────────────────────────────────────


def test_get_identity_200():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert req.url.path == "/users/identities/google/sub-123"
        return httpx.Response(200, json={"user_id": "u-1"})

    c = _client(handler)
    out = asyncio.run(c.get_identity("google", "sub-123"))
    assert out == {"user_id": "u-1"}


def test_get_identity_404_returns_none():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no"})

    c = _client(handler)
    assert asyncio.run(c.get_identity("google", "missing")) is None


def test_put_identity():
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PUT"
        assert req.url.path == "/users/identities/naver/ns-9"
        import json

        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    c = _client(handler)
    assert asyncio.run(c.put_identity("naver", "ns-9", "u-2")) is None
    assert captured["body"] == {"user_id": "u-2"}


def test_delete_identity():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "DELETE"
        assert req.url.path == "/users/identities/kakao/ks-3"
        assert "user_id" not in req.url.params  # expected 미지정 → 무조건 삭제
        return httpx.Response(204)

    c = _client(handler)
    assert asyncio.run(c.delete_identity("kakao", "ks-3")) is None


def test_delete_identity_ownership_param():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "DELETE"
        assert req.url.params.get("user_id") == "owner"  # 소유권 확인 삭제
        return httpx.Response(204)

    c = _client(handler)
    assert asyncio.run(c.delete_identity("kakao", "ks-3", expected_user_id="owner")) is None


# ── users/ profile ──────────────────────────────────────────────────────────


def test_get_profile_200():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/users/profiles/u-1/profile"
        return httpx.Response(200, json={"alias": "kim"})

    c = _client(handler)
    assert asyncio.run(c.get_profile("u-1")) == {"alias": "kim"}


def test_get_profile_404_returns_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c.get_profile("u-x")) is None


def test_put_profile():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PUT"
        assert req.url.path == "/users/profiles/u-1/profile"
        return httpx.Response(200, json={})

    c = _client(handler)
    assert asyncio.run(c.put_profile("u-1", {"alias": "lee"})) is None


def test_patch_profile():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PATCH"
        return httpx.Response(200, json={"alias": "patched"})

    c = _client(handler)
    out = asyncio.run(c.patch_profile("u-1", [{"op": "add", "path": "/alias", "value": "patched"}]))
    assert out == {"alias": "patched"}


# ── session ─────────────────────────────────────────────────────────────────


def test_create_session_with_user_id():
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/sessions"
        import json

        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"work_id": "i-1"})

    c = _client(handler)
    out = asyncio.run(c.create_session("u-1"))
    assert out == {"work_id": "i-1"}
    assert captured["body"] == {"user_id": "u-1"}


def test_create_session_without_user_id():
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"work_id": "i-2"})

    c = _client(handler)
    out = asyncio.run(c.create_session())
    assert out == {"work_id": "i-2"}
    assert captured["body"] == {}


def test_list_sessions():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/sessions/u-1"
        return httpx.Response(200, json={"sessions": []})

    c = _client(handler)
    assert asyncio.run(c.list_sessions("u-1")) == {"sessions": []}


# ── context manifest ────────────────────────────────────────────────────────


def test_get_context_manifest_200():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/sessions/u-1/i-1/manifest/context"
        return httpx.Response(200, json={"title": "T"})

    c = _client(handler)
    assert asyncio.run(c.get_context_manifest("u-1", "i-1")) == {"title": "T"}


def test_get_context_manifest_404_returns_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c.get_context_manifest("u-1", "i-1")) is None


def test_patch_context_manifest():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PATCH"
        assert req.url.path == "/sessions/u-1/i-1/manifest/context"
        return httpx.Response(200, json={"title": "new"})

    c = _client(handler)
    out = asyncio.run(
        c.patch_context_manifest("u-1", "i-1", [{"op": "add", "path": "/title", "value": "new"}])
    )
    assert out == {"title": "new"}


# ── conversation ────────────────────────────────────────────────────────────


def test_append_conversation():
    # 실제 CM append 는 갱신된 conversation(messages 포함)을 반환 — client 가 신규 turn 의
    # 메시지 id(= 0-based 위치)를 도출한다 (A-4).
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/sessions/u-1/i-1/runtime/00.dro/conversation/append"
        return httpx.Response(
            200,
            json={"messages": [{"role": "user"}], "total_user_turns": 1, "last_updated": "t"},
        )

    c = _client(handler)
    assert asyncio.run(c.append_conversation("u-1", "i-1", {"role": "user"})) == 0


def test_append_conversation_correlation_returns_existing_index():
    # correlation_id 가 meta 에 있으면 client 는 그 corr turn 의 위치를 찾아 반환(멱등 append 시
    # 기존 turn id 그대로 — 끝이 아닐 수 있음). A-4 W5 닫음.
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "messages": [
                    {"role": "user", "meta": {"correlation_id": "c-1"}},
                    {"role": "assistant"},
                ],
                "last_updated": "t",
            },
        )

    c = _client(handler)
    msg = {"role": "user", "content": "hi", "meta": {"correlation_id": "c-1"}}
    # corr turn 은 index 0 (마지막이 아님) — scan 으로 0 반환
    assert asyncio.run(c.append_conversation("u-1", "i-1", msg)) == 0


# ── media (presigned S3 direct) ──────────────────────────────────────────────


def test_request_presigned_put():
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/sessions/u-1/i-1/media/presign-put"
        import json

        captured["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "url": "https://s3/post",
                "fields": {"key": "k", "policy": "p"},
                "key": "sessions/u-1/i-1/media/m1.png",
            },
        )

    c = _client(handler)
    out = asyncio.run(c.request_presigned_put("u-1", "i-1", "m1", "png", "image/png", 1000, 300))
    assert out["url"] == "https://s3/post"
    assert out["fields"] == {"key": "k", "policy": "p"}
    assert out["key"] == "sessions/u-1/i-1/media/m1.png"
    assert captured["body"] == {
        "media_id": "m1",
        "ext": "png",
        "mime": "image/png",
        "max_bytes": 1000,
        "ttl": 300,
    }


def test_request_presigned_get_200():
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/sessions/u-1/i-1/media/presign-get"
        import json

        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"url": "https://s3/get"})

    c = _client(handler)
    out = asyncio.run(c.request_presigned_get("u-1", "i-1", "m1", 60))
    assert out == {"url": "https://s3/get"}
    assert captured["body"] == {"media_id": "m1", "ttl": 60}


def test_request_presigned_get_404_returns_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c.request_presigned_get("u-1", "i-1", "missing", 60)) is None


def test_list_media():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert req.url.path == "/sessions/u-1/i-1/media"
        return httpx.Response(
            200, json={"items": [{"media_id": "m1", "key": "k", "size_bytes": 4}]}
        )

    c = _client(handler)
    out = asyncio.run(c.list_media("u-1", "i-1"))
    assert out == [{"media_id": "m1", "key": "k", "size_bytes": 4}]


def test_delete_media():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "DELETE"
        assert req.url.path == "/sessions/u-1/i-1/media/m1"
        return httpx.Response(204)

    c = _client(handler)
    assert asyncio.run(c.delete_media("u-1", "i-1", "m1")) is None


# ── _model_get + model GET wrappers ─────────────────────────────────────────


def test_model_get_with_pointer():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params.get("pointer") == "/a/b"
        return httpx.Response(200, json={"v": 1})

    c = _client(handler)
    out = asyncio.run(c._model_get("http://cm/models/x", "/a/b"))
    assert out == {"v": 1}


def test_model_get_without_pointer():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "pointer" not in req.url.params
        return httpx.Response(200, json={"root": True})

    c = _client(handler)
    out = asyncio.run(c._model_get("http://cm/models/x"))
    assert out == {"root": True}


def test_model_get_404_returns_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c._model_get("http://cm/models/x")) is None


def test_get_iom():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/sessions/u-1/i-1/models/invention-object-model"
        return httpx.Response(200, json={"iom": 1})

    c = _client(handler)
    assert asyncio.run(c.get_iom("u-1", "i-1")) == {"iom": 1}


def test_get_concept_maturity_model():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/sessions/u-1/i-1/models/concept-maturity-model"
        return httpx.Response(200, json={"overall": 0.5})

    c = _client(handler)
    assert asyncio.run(c.get_concept_maturity_model("u-1", "i-1")) == {"overall": 0.5}


def test_get_user_roadmap():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/sessions/u-1/i-1/models/user-roadmap"
        return httpx.Response(200, json=[{"id": "r-1"}])

    c = _client(handler)
    assert asyncio.run(c.get_user_roadmap("u-1", "i-1")) == [{"id": "r-1"}]


def test_set_roadmap_item_ok():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PATCH"
        assert req.url.path == "/sessions/u-1/i-1/models/user-roadmap/items/r-1"
        return httpx.Response(200, json={"id": "r-1", "status": "satisfied"})

    c = _client(handler)
    out = asyncio.run(
        c.set_roadmap_item("u-1", "i-1", "r-1", {"answer": {"value": "v"}, "status": "satisfied"})
    )
    assert out == {"id": "r-1", "status": "satisfied"}


def test_set_roadmap_item_not_found_none():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "user-roadmap item 'nope' not found"})

    c = _client(handler)
    assert asyncio.run(c.set_roadmap_item("u-1", "i-1", "nope", {"status": "satisfied"})) is None


def test_get_conversation():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/sessions/u-1/i-1/runtime/00.dro/conversation"
        return httpx.Response(200, json={"messages": []})

    c = _client(handler)
    assert asyncio.run(c.get_conversation("u-1", "i-1")) == {"messages": []}


# ── drawing manifest ────────────────────────────────────────────────────────


def test_get_drawing_manifest_200():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/sessions/u-1/i-1/drawings/manifest"
        return httpx.Response(200, json={"drawings": []})

    c = _client(handler)
    assert asyncio.run(c.get_drawing_manifest("u-1", "i-1")) == {"drawings": []}


def test_get_drawing_manifest_404_returns_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c.get_drawing_manifest("u-1", "i-1")) is None


# ── upload_document (4 분기) ────────────────────────────────────────────────


def test_upload_document_204_fallback():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PUT"
        assert req.url.path == "/sessions/u-1/i-1/outputs/draft.docx"
        return httpx.Response(204)

    c = _client(handler)
    out = asyncio.run(c.upload_document("u-1", "i-1", "draft.docx", b"abcd"))
    assert out == {"filename": "draft.docx", "size": 4}


def test_upload_document_empty_content_fallback():
    # 200 이지만 content 비어있음 → fallback dict.
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    c = _client(handler)
    out = asyncio.run(c.upload_document("u-1", "i-1", "draft.docx", b"xyz"))
    assert out == {"filename": "draft.docx", "size": 3}


def test_upload_document_json_ctype():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"key": "s3://k"})

    c = _client(handler)
    out = asyncio.run(c.upload_document("u-1", "i-1", "draft.docx", b"xyz"))
    assert out == {"key": "s3://k"}


def test_upload_document_non_json_ctype_returns_empty():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"plain text", headers={"content-type": "text/plain"})

    c = _client(handler)
    out = asyncio.run(c.upload_document("u-1", "i-1", "draft.docx", b"xyz"))
    assert out == {}


# ── download_document ───────────────────────────────────────────────────────


def test_download_document_200_bytes():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/sessions/u-1/i-1/outputs/draft.docx"
        return httpx.Response(200, content=b"\x50\x4b\x03\x04")

    c = _client(handler)
    assert asyncio.run(c.download_document("u-1", "i-1", "draft.docx")) == b"\x50\x4b\x03\x04"


def test_download_document_404_returns_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c.download_document("u-1", "i-1", "draft.docx")) is None


# ── aclose ──────────────────────────────────────────────────────────────────


def test_aclose():
    c = _client(lambda req: httpx.Response(200, json={}))

    async def _run() -> None:
        await c.aclose()
        assert c._client.is_closed

    asyncio.run(_run())


# ── get_cm_client (싱글톤) ──────────────────────────────────────────────────


def test_get_cm_client_singleton(monkeypatch):
    # global _default 오염 방지 — 현재 값을 보존 후 None 으로 리셋, 끝나면 복구.
    saved = cm_client._default
    monkeypatch.setattr(cm_client, "_default", None)
    try:
        first = get_cm_client()
        assert isinstance(first, CMClient)
        second = get_cm_client()
        assert first is second
    finally:
        cm_client._default = saved


# ── users/ idempotency (D6) ──────────────────────────────────────────────────


def test_get_idempotency_200():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert req.url.path.startswith("/users/idempotency/u-1/")
        return httpx.Response(200, json={"status": 201, "body": {"work_id": "w"}})

    c = _client(handler)
    out = asyncio.run(c.get_idempotency("u-1", "K"))
    assert out["body"]["work_id"] == "w"


def test_get_idempotency_404_returns_none():
    c = _client(lambda req: httpx.Response(404))
    assert asyncio.run(c.get_idempotency("u-1", "K")) is None


def test_put_idempotency():
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        assert req.method == "PUT"
        assert req.url.path.startswith("/users/idempotency/u-1/")
        captured["body"] = json.loads(req.content)
        return httpx.Response(204)

    c = _client(handler)
    assert asyncio.run(c.put_idempotency("u-1", "K", {"body": {"x": 1}})) is None
    assert captured["body"] == {"body": {"x": 1}}


def test_claim_idempotency_done():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path.endswith("/claim")
        return httpx.Response(200, json={"state": "done", "record": {"body": {"work_id": "w"}}})

    c = _client(handler)
    state, rec = asyncio.run(c.claim_idempotency("u-1", "K"))
    assert state == "done"
    assert rec["body"]["work_id"] == "w"


def test_claim_idempotency_claimed_no_record():
    c = _client(lambda req: httpx.Response(200, json={"state": "claimed", "record": None}))
    state, rec = asyncio.run(c.claim_idempotency("u-1", "K"))
    assert state == "claimed" and rec is None


def test_delete_idempotency():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "DELETE"
        assert req.url.path.startswith("/users/idempotency/u-1/")
        return httpx.Response(204)

    c = _client(handler)
    assert asyncio.run(c.delete_idempotency("u-1", "K")) is None


# -- refresh token family wrappers (C1 인증) ----------------------------------


def test_put_refresh_family():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PUT"
        assert req.url.path == "/users/refresh-tokens/u-1/fam"
        return httpx.Response(204)

    c = _client(handler)
    assert asyncio.run(c.put_refresh_family("u-1", "fam", "j1")) is None


def test_rotate_refresh_family():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path.endswith("/fam/rotate")
        return httpx.Response(200, json={"result": "rotated"})

    c = _client(handler)
    assert asyncio.run(c.rotate_refresh_family("u-1", "fam", "j1", "j2")) == "rotated"


def test_revoke_refresh_family():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path.endswith("/fam/revoke")
        return httpx.Response(204)

    c = _client(handler)
    assert asyncio.run(c.revoke_refresh_family("u-1", "fam")) is None
