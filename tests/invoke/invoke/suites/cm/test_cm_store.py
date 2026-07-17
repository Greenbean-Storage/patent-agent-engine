"""src.store 단위 커버리지 (probe 트랙, in-process exerciser).

stub_s3(mem) 를 받아 store 함수를 직접 호출. mem 으로 S3 키 직접 검사.
async 없음 — store 함수는 전부 동기. ClientError 분기는 stub get_object 의
NoSuchKey + 비-NoSuchKey ClientError 던지는 임시 client 교체로 커버.
"""

from __future__ import annotations

import json

import pytest
import venezia_memory as vm
import yaml
from botocore.exceptions import ClientError

from src import store

UID = "u-1234567890"
IID = "i-0987654321"


# -- raise-on-call stubs (비-NoSuchKey ClientError 강제) -----------------------


def _err(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, op)


class _GetRaiser:
    """get_object 가 비-NoSuchKey ClientError 를 던지는 client."""

    def __init__(self, code: str = "AccessDenied") -> None:
        self._code = code

    def get_object(self, Bucket, Key):
        raise _err(self._code, "GetObject")


class _PutRaiser:
    def put_object(self, Bucket, Key, Body, ContentType=""):
        raise _err("AccessDenied", "PutObject")


# -- _serialize / _deserialize ------------------------------------------------


def test_serialize_json():
    body, ct = store._serialize("models/iom.json", {"a": 1})
    assert ct == "application/json"
    assert json.loads(body.decode("utf-8")) == {"a": 1}


def test_serialize_yaml():
    body, ct = store._serialize("manifest.context.yaml", {"status": "draft"})
    assert ct == "application/yaml"
    assert yaml.safe_load(body.decode("utf-8")) == {"status": "draft"}


def test_deserialize_json():
    assert store._deserialize("x.json", b'{"k": 2}') == {"k": 2}


def test_deserialize_yaml_empty_returns_dict():
    # yaml.safe_load(None) -> None, store coalesces to {}
    assert store._deserialize("m.yaml", b"") == {}


def test_deserialize_yaml_content():
    assert store._deserialize("m.yml", b"a: 1\nb: two\n") == {"a": 1, "b": "two"}


# -- apply_json_patch (add / remove / replace / move) -------------------------


def test_apply_json_patch_add_remove_replace_move():
    doc = {"a": 1, "b": {"c": 2}, "list": [1, 2, 3]}
    patched = store.apply_json_patch(
        doc,
        [
            {"op": "add", "path": "/new", "value": 9},
            {"op": "remove", "path": "/a"},
            {"op": "replace", "path": "/b/c", "value": 22},
            {"op": "move", "from": "/list", "path": "/moved"},
        ],
    )
    assert patched == {"new": 9, "b": {"c": 22}, "moved": [1, 2, 3]}
    # in_place=False → 원본 불변
    assert doc == {"a": 1, "b": {"c": 2}, "list": [1, 2, 3]}


# -- read_pointer (빈 / 루트 / 경로) ------------------------------------------


def test_read_pointer_empty_returns_root():
    doc = {"x": {"y": 1}}
    assert store.read_pointer(doc, "") is doc


def test_read_pointer_slash_returns_root():
    doc = {"x": 1}
    assert store.read_pointer(doc, "/") is doc


def test_read_pointer_path():
    assert store.read_pointer({"x": {"y": 7}}, "/x/y") == 7


# -- read (존재 / NoSuchKey→None / 다른 ClientError→raise) --------------------


def test_read_existing(stub_s3):
    mem = stub_s3
    store.write(UID, IID, "models/iom.json", {"hello": "world"})
    assert store.read(UID, IID, "models/iom.json") == {"hello": "world"}
    # 키가 실제로 mem 에 쓰였는지
    assert any(k.endswith("models/iom.json") for k in mem)


def test_read_nosuchkey_returns_none(stub_s3):
    assert store.read(UID, IID, "models/missing.json") is None


def test_read_other_clienterror_raises(stub_s3):
    prev = store._s3_client
    store._s3_client = _GetRaiser("AccessDenied")
    try:
        with pytest.raises(ClientError):
            store.read(UID, IID, "models/x.json")
    finally:
        store._s3_client = prev


# -- write (정상 / ClientError→log+raise) -------------------------------------


def test_write_normal(stub_s3):
    mem = stub_s3
    store.write(UID, IID, "models/cmm.json", {"overall": 0.5})
    key = store._key(UID, IID, "models/cmm.json")
    assert json.loads(mem[key].decode("utf-8")) == {"overall": 0.5}


def test_write_clienterror_raises(stub_s3):
    prev = store._s3_client
    store._s3_client = _PutRaiser()
    try:
        with pytest.raises(ClientError):
            store.write(UID, IID, "models/x.json", {"a": 1})
    finally:
        store._s3_client = prev


# -- read_by_key / write_by_key (동일) ----------------------------------------


def test_write_then_read_by_key(stub_s3):
    mem = stub_s3
    key = "users/profiles/u-1/profile.json"
    store.write_by_key(key, {"nickname": "kim"})
    assert key in mem
    assert store.read_by_key(key) == {"nickname": "kim"}


def test_read_by_key_nosuchkey_returns_none(stub_s3):
    assert store.read_by_key("users/profiles/missing/profile.json") is None


def test_read_by_key_other_clienterror_raises(stub_s3):
    prev = store._s3_client
    store._s3_client = _GetRaiser("Throttling")
    try:
        with pytest.raises(ClientError):
            store.read_by_key("k")
    finally:
        store._s3_client = prev


def test_write_by_key_clienterror_raises(stub_s3):
    prev = store._s3_client
    store._s3_client = _PutRaiser()
    try:
        with pytest.raises(ClientError):
            store.write_by_key("k", {"a": 1})
    finally:
        store._s3_client = prev


# -- patch (없으면 {} 시작 + last_updated / dict / non-dict) ------------------


def test_patch_from_empty_adds_last_updated(stub_s3):
    result = store.patch(UID, IID, "models/cmm.json", [{"op": "add", "path": "/x", "value": 1}])
    assert result["x"] == 1
    assert "last_updated" in result


def test_patch_existing_dict(stub_s3):
    store.write(UID, IID, "models/cmm.json", {"a": 1})
    result = store.patch(UID, IID, "models/cmm.json", [{"op": "add", "path": "/b", "value": 2}])
    assert result["a"] == 1 and result["b"] == 2
    assert "last_updated" in result


def test_patch_non_dict_result_no_last_updated(stub_s3):
    # 기존이 dict 인데 replace 로 root 를 array 로 바꾸면 patched 는 list → last_updated 미부착
    store.write(UID, IID, "models/user-roadmap.json", {"placeholder": True})
    result = store.patch(
        UID, IID, "models/user-roadmap.json", [{"op": "replace", "path": "", "value": [1, 2, 3]}]
    )
    assert result == [1, 2, 3]
    assert not isinstance(result, dict)


# -- append_conversation (신규 / 기존 / user role total++) --------------------


def test_append_conversation_new_user_turn(stub_s3):
    res = store.append_conversation(UID, IID, {"role": "user", "text": "hi"})
    assert res["total_user_turns"] == 1
    assert res["messages"] == [{"role": "user", "text": "hi"}]
    assert "last_updated" in res


def test_append_conversation_existing_and_assistant_no_increment(stub_s3):
    store.append_conversation(UID, IID, {"role": "user", "text": "first"})
    res = store.append_conversation(UID, IID, {"role": "assistant", "text": "reply"})
    # assistant turn 은 total_user_turns 증가 안 함
    assert res["total_user_turns"] == 1
    assert len(res["messages"]) == 2
    res2 = store.append_conversation(UID, IID, {"role": "user", "text": "again"})
    assert res2["total_user_turns"] == 2
    assert len(res2["messages"]) == 3


def test_append_conversation_correlation_idempotent(stub_s3):
    # meta.correlation_id 멱등 — 같은 corr 재-append 는 no-op(중복 turn 0). A-4 W5 닫음.
    turn = {"role": "user", "content": "hi", "meta": {"correlation_id": "c-1"}}
    r1 = store.append_conversation(UID, IID, turn)
    r2 = store.append_conversation(UID, IID, dict(turn))  # 같은 corr 재처리
    assert len(r1["messages"]) == 1 and len(r2["messages"]) == 1  # 중복 안 됨
    assert r2["total_user_turns"] == 1
    # 다른 corr → append
    r3 = store.append_conversation(
        UID, IID, {"role": "user", "content": "yo", "meta": {"correlation_id": "c-2"}}
    )
    assert len(r3["messages"]) == 2
    # correlation_id 없으면(meta 무) 항상 append
    r4 = store.append_conversation(UID, IID, {"role": "user", "content": "z"})
    assert len(r4["messages"]) == 3


# -- read_identity / write_identity -------------------------------------------


def test_identity_roundtrip(stub_s3):
    mem = stub_s3
    store.write_identity("google", "sub-123", "user-abc")
    key = vm.identity_key("google", "sub-123")
    assert key in mem
    rec = store.read_identity("google", "sub-123")
    assert rec["user_id"] == "user-abc"
    assert "linked_at" in rec


def test_read_identity_missing_none(stub_s3):
    assert store.read_identity("google", "nope") is None


def test_delete_identity_removes(stub_s3):
    # disconnect — 로그인 인덱스 제거 → 이후 read None (재로그인 시 새 user_id mint)
    store.write_identity("google", "sub-9", "user-z")
    store.delete_identity("google", "sub-9")
    assert store.read_identity("google", "sub-9") is None


def test_delete_identity_idempotent(stub_s3):
    assert store.delete_identity("google", "absent") is True  # 무조건(None) — S3 no-op


def test_delete_identity_ownership_checked(stub_s3):
    # expected_user_id 일치만 삭제 — 재발급된 다른 user 매핑 오삭제 방지(cross-account 차단)
    store.write_identity("google", "g1", "owner")
    assert store.delete_identity("google", "g1", expected_user_id="other") is False  # 미일치 → 보존
    assert store.read_identity("google", "g1")["user_id"] == "owner"
    assert store.delete_identity("google", "g1", expected_user_id="owner") is True  # 일치 → 삭제
    assert store.read_identity("google", "g1") is None


def test_delete_identity_ownership_missing_rec(stub_s3):
    # 매핑 자체 없음 + expected 지정 → False (삭제 안 함)
    assert store.delete_identity("google", "gone", expected_user_id="owner") is False


# -- read_profile / write_profile ---------------------------------------------


def test_profile_roundtrip(stub_s3):
    store.write_profile("user-abc", {"nickname": "lee", "providers": ["google"]})
    rec = store.read_profile("user-abc")
    assert rec["nickname"] == "lee"


def test_read_profile_missing_none(stub_s3):
    assert store.read_profile("ghost") is None


def test_write_profile_stamps_updated_at(stub_s3):
    # write_profile 가 updated_at 스탬프 + 스탬프된 dict 반환 (alias ETag 기준, D7)
    rec = store.write_profile("user-x", {"nickname": "n"})
    assert "updated_at" in rec
    assert store.read_profile("user-x")["updated_at"]


# -- read_idempotency / write_idempotency (D6) --------------------------------


def test_idempotency_roundtrip(stub_s3):
    assert store.read_idempotency("u-1", "kh-1") is None
    store.write_idempotency("u-1", "kh-1", {"status": 201, "body": {"work_id": "w"}})
    rec = store.read_idempotency("u-1", "kh-1")
    assert rec["body"]["work_id"] == "w"


def test_idempotency_claim_lifecycle(stub_s3):
    # 1st claim → claimed(선점) · 2nd(미완료) → in_flight · 확정 후 → done(+record)
    state, rec = store.claim_idempotency("u-c", "kh")
    assert state == "claimed" and rec is None
    state, _ = store.claim_idempotency("u-c", "kh")
    assert state == "in_flight"
    store.write_idempotency("u-c", "kh", {"status": 201, "body": {"work_id": "w"}})
    state, rec = store.claim_idempotency("u-c", "kh")
    assert state == "done" and rec["body"]["work_id"] == "w"


def test_idempotency_claim_content_hash(stub_s3):
    # content_hash 를 주면 선점 마커에 보존 → in_flight 회신 rec 로 같은 키·다른 내용 충돌 검출(메시지 멱등).
    state, rec = store.claim_idempotency("u-ch", "kh", "abc123")
    assert state == "claimed" and rec is None
    state, rec = store.claim_idempotency("u-ch", "kh", "abc123")
    assert state == "in_flight" and rec is not None and rec["content_hash"] == "abc123"


def test_idempotency_delete_releases(stub_s3):
    store.claim_idempotency("u-d", "kh")
    store.delete_idempotency("u-d", "kh")
    state, _ = store.claim_idempotency("u-d", "kh")  # 해제 후 다시 선점 가능
    assert state == "claimed"


def test_idempotency_stale_reclaim(stub_s3):
    # 오래된 미완료 선점(claimed_at 과거) → 죽은 요청으로 보고 재선점
    store.write_by_key(vm.idempotency_key("u-s", "kh"), {"claimed_at": "2000-01-01T00:00:00+00:00"})
    state, _ = store.claim_idempotency("u-s", "kh")
    assert state == "claimed"


# -- refresh token family (C1 인증 — 회전·재사용 탐지·logout) ------------------


def test_refresh_family_roundtrip(stub_s3):
    assert store.read_refresh_family("u-r", "fam") is None
    rec = store.write_refresh_family("u-r", "fam", "jti-1")
    assert rec["current_jti"] == "jti-1" and rec["revoked"] is False
    assert store.read_refresh_family("u-r", "fam")["current_jti"] == "jti-1"


def test_refresh_family_rotate_ok(stub_s3):
    store.write_refresh_family("u-r", "fam", "jti-1")
    assert store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-2") == "rotated"
    assert store.read_refresh_family("u-r", "fam")["current_jti"] == "jti-2"


def test_refresh_family_rotate_missing(stub_s3):
    assert store.rotate_refresh_family("u-r", "none", "x", "y") == "missing"


def test_refresh_family_rotate_concurrent_grace(stub_s3):
    # 직전(prev) jti 재사용 = 동시 갱신/재시도 → 'concurrent' (탈취 아님, revoke 안 함)
    store.write_refresh_family("u-r", "fam", "jti-1")
    store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-2")  # current=jti-2, prev=jti-1
    assert store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-3") == "concurrent"
    rec = store.read_refresh_family("u-r", "fam")
    assert rec["revoked"] is False and rec["current_jti"] == "jti-2"  # 현 토큰 유지


def test_refresh_family_rotate_reuse_revokes(stub_s3):
    # current/prev 둘 다 아닌 오래된 jti → 진짜 재사용(탈취 의심) → family revoke + 'reuse'
    store.write_refresh_family("u-r", "fam", "jti-1")
    store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-2")  # current=jti-2, prev=jti-1
    store.rotate_refresh_family("u-r", "fam", "jti-2", "jti-3")  # current=jti-3, prev=jti-2
    assert store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-9") == "reuse"  # jti-1 = 오래됨
    assert store.read_refresh_family("u-r", "fam")["revoked"] is True


def test_refresh_family_rotate_prev_outside_grace_revokes(stub_s3):
    # 직전 jti 라도 grace 창 밖(오래된 rotated_at) → 탈취된 prev 의 지연 replay → reuse + revoke
    store.write_by_key(
        vm.refresh_token_key("u-r", "fam"),
        {
            "current_jti": "jti-2",
            "prev_jti": "jti-1",
            "revoked": False,
            "rotated_at": "2000-01-01T00:00:00+00:00",
        },
    )
    assert store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-9") == "reuse"
    assert store.read_refresh_family("u-r", "fam")["revoked"] is True


def test_refresh_family_rotate_prev_no_rotated_at_revokes(stub_s3):
    # prev jti 이나 rotated_at 없음 → grace 판정 불가 → 보수적으로 reuse
    store.write_by_key(
        vm.refresh_token_key("u-r", "fam"),
        {"current_jti": "jti-2", "prev_jti": "jti-1", "revoked": False, "rotated_at": None},
    )
    assert store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-9") == "reuse"


def test_refresh_family_rotate_prev_bad_rotated_at_revokes(stub_s3):
    # rotated_at 파싱 불가 → grace False → reuse
    store.write_by_key(
        vm.refresh_token_key("u-r", "fam"),
        {"current_jti": "jti-2", "prev_jti": "jti-1", "revoked": False, "rotated_at": "nope"},
    )
    assert store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-9") == "reuse"


def test_refresh_family_rotate_revoked(stub_s3):
    store.write_refresh_family("u-r", "fam", "jti-1")
    store.revoke_refresh_family("u-r", "fam")
    assert store.rotate_refresh_family("u-r", "fam", "jti-1", "jti-2") == "revoked"


def test_refresh_family_revoke_idempotent(stub_s3):
    store.revoke_refresh_family("u-r", "none")  # 없어도 no-op (멱등)
    store.write_refresh_family("u-r", "fam", "jti-1")
    store.revoke_refresh_family("u-r", "fam")
    assert store.read_refresh_family("u-r", "fam")["revoked"] is True


# -- list_inventions (CommonPrefixes + manifest read) -------------------------


def test_list_inventions_with_manifest(stub_s3):
    # 두 invention: 하나는 manifest 있음 (yaml), 하나는 없음 → 기본값
    store.write(
        UID,
        "inv-a",
        vm.ROOT_MANIFEST,
        {
            "current_phase": "drafting",
            "status": "active",
            "created_at": "2026-01-01",
            "updated_at": "2026-01-02",
        },
    )
    # inv-b: manifest 없이 아무 키만 → CommonPrefix 잡히게
    store.write(UID, "inv-b", "models/iom.json", {"a": 1})

    result = store.list_inventions(UID)
    by_id = {r["work_id"]: r for r in result}
    assert set(by_id) == {"inv-a", "inv-b"}
    assert by_id["inv-a"]["phase"] == "drafting"
    assert by_id["inv-a"]["status"] == "active"
    assert by_id["inv-a"]["created_at"] == "2026-01-01"
    # manifest 없는 inv-b 는 기본값
    assert by_id["inv-b"]["phase"] == "discovery"
    assert by_id["inv-b"]["status"] == "draft"
    assert "created_at" in by_id["inv-b"]


def test_list_inventions_empty(stub_s3):
    assert store.list_inventions("no-such-user") == []


# -- write_output / read_output (404→None) / list_outputs ---------------------


def test_write_and_read_output(stub_s3):
    mem = stub_s3
    store.write_output(UID, IID, "draft.docx", b"BINARY")
    key = vm.output_key(UID, IID, "draft.docx")
    assert mem[key] == b"BINARY"
    assert store.read_output(UID, IID, "draft.docx") == b"BINARY"


def test_write_output_clienterror_raises(stub_s3):
    prev = store._s3_client
    store._s3_client = _PutRaiser()
    try:
        with pytest.raises(ClientError):
            store.write_output(UID, IID, "draft.docx", b"x")
    finally:
        store._s3_client = prev


def test_read_output_missing_returns_none(stub_s3):
    assert store.read_output(UID, IID, "missing.docx") is None


def test_read_output_other_clienterror_raises(stub_s3):
    prev = store._s3_client
    store._s3_client = _GetRaiser("AccessDenied")
    try:
        with pytest.raises(ClientError):
            store.read_output(UID, IID, "draft.docx")
    finally:
        store._s3_client = prev


def test_list_outputs_filters_manifest_and_nested(stub_s3):
    mem = stub_s3
    root = vm.outputs_root(UID, IID)
    # 직접 mem 에 다양한 키 적재
    mem[f"{root}/draft.docx"] = b"a"
    mem[f"{root}/proposal.docx"] = b"b"
    mem[f"{root}/manifest.outputs.yaml"] = b"meta"  # manifest. 제외
    mem[f"{root}/sub/nested.docx"] = b"c"  # / 포함 제외
    mem[f"{root}/"] = b""  # 빈 name 제외
    names = store.list_outputs(UID, IID)
    assert names == ["draft.docx", "proposal.docx"]


def test_list_outputs_empty(stub_s3):
    assert store.list_outputs(UID, "empty-inv") == []


# -- delete_invention (키 있음 batch / 없음 0) --------------------------------


def test_delete_invention_with_keys(stub_s3):
    mem = stub_s3
    store.write(UID, "inv-del", "models/iom.json", {"a": 1})
    store.write(UID, "inv-del", "models/cmm.json", {"b": 2})
    store.write_output(UID, "inv-del", "draft.docx", b"x")
    count = store.delete_invention(UID, "inv-del")
    assert count == 3
    # 실제로 prefix 아래 키가 사라졌는지
    prefix = f"{store.ROOT_PREFIX}/{UID}/inv-del/"
    assert not any(k.startswith(prefix) for k in mem)


def test_delete_invention_none_returns_zero(stub_s3):
    assert store.delete_invention(UID, "ghost-inv") == 0


# -- media (work-level, presigned S3 direct) ----------------------------------


def test_presign_put_returns_url_fields_key(stub_s3):
    out = store.presign_put(UID, IID, "m-1", "png", "image/png", 2048, 300)
    assert out["key"] == vm.media_key(UID, IID, "m-1", "png")
    assert out["url"].startswith("https://")
    assert out["fields"]["Content-Type"] == "image/png"


def test_resolve_media_key_found(stub_s3):
    mem = stub_s3
    key = vm.media_key(UID, IID, "m-r", "jpg")
    mem[key] = b"x"
    assert store.resolve_media_key(UID, IID, "m-r") == key


def test_resolve_media_key_none_when_absent(stub_s3):
    assert store.resolve_media_key(UID, IID, "ghost") is None


def test_presign_get_found(stub_s3):
    mem = stub_s3
    mem[vm.media_key(UID, IID, "m-g", "png")] = b"x"
    url = store.presign_get(UID, IID, "m-g", 120)
    assert url is not None
    assert url.startswith("https://")


def test_presign_get_none_when_absent(stub_s3):
    assert store.presign_get(UID, IID, "no-such", 120) is None


def test_list_media_empty(stub_s3):
    assert store.list_media(UID, IID) == []


def test_list_media_with_items_and_mime(stub_s3):
    mem = stub_s3
    # head_object mime 분기 — content_types 있는 것 / 없는 것(=octet-stream)
    k1 = vm.media_key(UID, IID, "m-a", "png")
    k2 = vm.media_key(UID, IID, "m-b", "bin")
    mem[k1] = b"aaa"
    store._s3_client.content_types[k1] = "image/png"
    mem[k2] = b"bbbb"
    # media root 아래 nested(서브경로) key 는 무시돼야 함
    mem[f"{vm.media_root(UID, IID)}/nested/skip.png"] = b"z"
    items = store.list_media(UID, IID)
    assert [it["media_id"] for it in items] == ["m-a", "m-b"]
    assert items[0]["ext"] == "png"
    assert items[0]["size_bytes"] == 3
    assert items[0]["mime"] == "image/png"
    assert items[1]["mime"] == "application/octet-stream"
    assert isinstance(items[0]["last_modified"], str)


def test_delete_media_removes_and_counts(stub_s3):
    mem = stub_s3
    key = vm.media_key(UID, IID, "m-del", "png")
    mem[key] = b"data"
    assert store.delete_media(UID, IID, "m-del") == 1
    assert key not in mem


def test_delete_media_absent_returns_zero(stub_s3):
    assert store.delete_media(UID, IID, "ghost") == 0
