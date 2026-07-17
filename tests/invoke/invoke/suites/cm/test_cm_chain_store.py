"""src.chain_store 단위 커버리지 (probe 트랙, in-process exerciser).

stub_s3(mem) 를 받아 chain_store 의 async 함수를 `asyncio.run(...)` 로 직접 호출.
모든 함수가 store.read_by_key / write_by_key (= _s3() stub) 경유 → 메모리 동작.
mem 으로 S3 키 직접 검사 가능.

커버 분기:
- get_chains_manifest (없음 기본 / 있음)
- add_chain_to_manifest / update_chain_in_manifest (매칭 / 비매칭 entry)
- create_chain ①loader=None(import 실패: _CONTRACT_LOADER=False) ②loader invalid result
  (fake loader → schema_violation trail append) ③valid result
- get_chain (존재 / None)
- patch_chain (merge + mirror status/completed_at / mirror 없음)
- read_trail (있음 / 없음→b"")
- append_trail (신규 / 기존 append)
- create_rt (기본 state/retry_count/sse_events) / get_rt
- patch_rt (일반 ops + /sse_events_append 특수 path + cleaned_ops 빈 경우)
- get_agent_state (없음 기본 / 있음) / put_agent_state
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

import venezia_memory as vm

from src import chain_store

UID = "u-chainstore-1"
IID = "i-chainstore-1"
PERSONA = 2
CHAIN = "chain-abc"
PIPELINE = "P02.R00.CONCEPT_MATURITY"


# ── fake ContractLoader (create_chain validation 분기용) ──────────────────────


class _FakeResult:
    """validate() 가 반환하는 result 객체 — truthiness 제어 + .errors."""

    def __init__(self, ok: bool, errors: list | None = None) -> None:
        self._ok = ok
        self.errors = errors or []

    def __bool__(self) -> bool:
        return self._ok


class _FakeLoader:
    def __init__(self, ok: bool, errors: list | None = None) -> None:
        self._result = _FakeResult(ok, errors)
        self.calls: list = []

    def validate(self, contract: str, doc: dict):
        self.calls.append((contract, doc))
        return self._result


# ── get_chains_manifest ───────────────────────────────────────────────────────


def test_get_chains_manifest_default_when_missing(stub_s3):
    m = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    assert m["session"] == {"user_id": UID, "work_id": IID}
    assert m["chains"] == []
    assert "last_updated" in m


def test_get_chains_manifest_existing(stub_s3):
    key = vm.runtime_manifest_key(UID, IID)
    asyncio.run(chain_store.add_chain_to_manifest(UID, IID, CHAIN, PIPELINE, PERSONA))
    m = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    assert key in stub_s3
    assert len(m["chains"]) == 1
    assert m["chains"][0]["chain_id"] == CHAIN


# ── add_chain_to_manifest ─────────────────────────────────────────────────────


def test_add_chain_to_manifest(stub_s3):
    asyncio.run(chain_store.add_chain_to_manifest(UID, IID, CHAIN, PIPELINE, PERSONA))
    m = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    entry = m["chains"][0]
    assert entry["chain_id"] == CHAIN
    assert entry["pipeline_id"] == PIPELINE
    assert entry["persona"] == PERSONA
    assert entry["status"] == "pending"
    assert entry["completed_at"] is None
    assert "started_at" in entry


def test_add_chain_to_manifest_dedup(stub_s3):
    """같은 chain_id 두 번 add → 인덱스 entry 1개 (멱등, 중복 방지)."""
    asyncio.run(chain_store.add_chain_to_manifest(UID, IID, CHAIN, PIPELINE, PERSONA))
    asyncio.run(chain_store.add_chain_to_manifest(UID, IID, CHAIN, PIPELINE, PERSONA))
    m = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    assert len([c for c in m["chains"] if c["chain_id"] == CHAIN]) == 1


# ── update_chain_in_manifest (매칭 / 비매칭) ──────────────────────────────────


def test_update_chain_in_manifest_matching(stub_s3):
    asyncio.run(chain_store.add_chain_to_manifest(UID, IID, CHAIN, PIPELINE, PERSONA))
    asyncio.run(
        chain_store.update_chain_in_manifest(
            UID, IID, CHAIN, status="completed", completed_at="2026-06-04T00:00:00Z"
        )
    )
    m = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    assert m["chains"][0]["status"] == "completed"
    assert m["chains"][0]["completed_at"] == "2026-06-04T00:00:00Z"


def test_update_chain_in_manifest_no_match(stub_s3):
    asyncio.run(chain_store.add_chain_to_manifest(UID, IID, CHAIN, PIPELINE, PERSONA))
    # 존재하지 않는 chain_id → entry update 안 됨 (loop 통과만)
    asyncio.run(chain_store.update_chain_in_manifest(UID, IID, "other-chain", status="failed"))
    m = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    assert m["chains"][0]["status"] == "pending"  # 변경 없음


# ── create_chain ① loader=None (import 실패 분기) ─────────────────────────────


def test_create_chain_loader_none_skips_validation(stub_s3, monkeypatch):
    # _CONTRACT_LOADER=False → _contract_loader() 가 None 반환 → validation skip
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", False)
    manifest = asyncio.run(
        chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {"kind": "user_message"})
    )
    assert manifest["chain_id"] == CHAIN
    assert manifest["status"] == "pending"
    assert manifest["rt_count"] == 0
    assert manifest["completed_rt_count"] == 0
    assert manifest["trigger"] == {"kind": "user_message"}
    assert manifest["error"] is None
    # chain manifest 키 + runtime manifest 둘 다 쓰여야 함
    ckey = vm.chain_manifest_key(UID, IID, PERSONA, CHAIN)
    assert ckey in stub_s3
    rm = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    assert rm["chains"][0]["chain_id"] == CHAIN
    # validation skip 이므로 trail (schema_violation) 없음
    tkey = vm.trail_key(UID, IID, PERSONA, CHAIN)
    assert tkey not in stub_s3


def test_create_chain_idempotent_returns_existing(stub_s3, monkeypatch):
    """같은 chain_id 재생성(retry 등)은 기존 manifest 그대로 반환 — status 리셋 X, 인덱스 재-append X."""
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", False)
    first = asyncio.run(
        chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {"kind": "user_message"})
    )
    assert first["status"] == "pending"
    # 진행(상태 변경) 후 같은 chain_id 재생성 → 덮어쓰지 않고 기존(active) 반환
    asyncio.run(
        chain_store.patch_chain(
            UID, IID, PERSONA, CHAIN, [{"op": "replace", "path": "/status", "value": "active"}]
        )
    )
    again = asyncio.run(
        chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {"kind": "user_message"})
    )
    assert again["status"] == "active"  # 멱등 — pending 으로 리셋 안 됨
    rm = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    assert len([c for c in rm["chains"] if c["chain_id"] == CHAIN]) == 1


# ── create_chain ② loader invalid result → schema_violation trail append ──────


def test_create_chain_invalid_result_appends_trail(stub_s3, monkeypatch):
    fake = _FakeLoader(ok=False, errors=["e1", "e2", "e3", "e4", "e5", "e6"])
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", fake)
    manifest = asyncio.run(chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {"k": 1}))
    assert manifest["chain_id"] == CHAIN
    assert fake.calls and fake.calls[0][0] == "chain_manifest"
    # schema_violation trail 이 append 되었는지 (errors[:5] 만)
    tkey = vm.trail_key(UID, IID, PERSONA, CHAIN)
    assert tkey in stub_s3
    raw = stub_s3[tkey].decode("utf-8").strip()
    rec = json.loads(raw)
    assert rec["event"] == "schema_violation"
    assert rec["contract"] == "chain_manifest"
    assert rec["chain_id"] == CHAIN
    assert rec["errors"] == ["e1", "e2", "e3", "e4", "e5"]


# ── create_chain ② 내부 except (append_trail 실패 → swallow) ──────────────────


def test_create_chain_invalid_result_trail_append_swallows(stub_s3, monkeypatch):
    fake = _FakeLoader(ok=False, errors=["x"])
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", fake)

    async def _boom(*_a, **_k):
        raise RuntimeError("trail down")

    monkeypatch.setattr(chain_store, "append_trail", _boom)
    # append_trail 이 던져도 create_chain 은 정상 반환해야 함 (try/except pass)
    manifest = asyncio.run(chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {}))
    assert manifest["chain_id"] == CHAIN
    ckey = vm.chain_manifest_key(UID, IID, PERSONA, CHAIN)
    assert ckey in stub_s3


# ── create_chain ③ valid result → trail 없음 ─────────────────────────────────


def test_create_chain_valid_result_no_trail(stub_s3, monkeypatch):
    fake = _FakeLoader(ok=True)
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", fake)
    manifest = asyncio.run(chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {}))
    assert manifest["chain_id"] == CHAIN
    assert fake.calls  # validate 호출됨
    tkey = vm.trail_key(UID, IID, PERSONA, CHAIN)
    assert tkey not in stub_s3  # valid 이므로 schema_violation 없음


# ── _contract_loader real-path: import 성공/실패 lazy 초기화 ───────────────────


def test_contract_loader_lazy_init_success(stub_s3, monkeypatch):
    # _CONTRACT_LOADER=None → 실제 import 성공 경로 (이 venv 는 venezia_contracts 보유).
    # 두 번째 호출은 캐시된 같은 싱글톤.
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", None)
    first = chain_store._contract_loader()
    second = chain_store._contract_loader()
    assert first is not None
    assert first is second  # 싱글톤 캐시


def test_contract_loader_import_failure_sets_false(stub_s3, monkeypatch):
    # `from venezia_contracts import ContractLoader` 가 ImportError 던지도록
    # sys.modules 에 ContractLoader 없는 stub 주입 → except 분기 (line 42-45).
    stub_mod = types.ModuleType("venezia_contracts")  # ContractLoader 속성 없음
    monkeypatch.setitem(sys.modules, "venezia_contracts", stub_mod)
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", None)
    result = chain_store._contract_loader()
    assert result is None
    # except 분기에서 _CONTRACT_LOADER = False 로 세팅
    assert chain_store._CONTRACT_LOADER is False
    # 이후 호출은 False 빠른 경로 → None
    assert chain_store._contract_loader() is None


# ── get_chain (존재 / None) ───────────────────────────────────────────────────


def test_get_chain_existing(stub_s3, monkeypatch):
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", False)
    asyncio.run(chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {}))
    got = asyncio.run(chain_store.get_chain(UID, IID, PERSONA, CHAIN))
    assert got is not None
    assert got["chain_id"] == CHAIN


def test_get_chain_missing_none(stub_s3):
    assert asyncio.run(chain_store.get_chain(UID, IID, PERSONA, "ghost")) is None


# ── patch_chain (merge + mirror / mirror 없음) ────────────────────────────────


def test_patch_chain_mirrors_status_and_completed_at(stub_s3, monkeypatch):
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", False)
    asyncio.run(chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {}))
    merged = asyncio.run(
        chain_store.patch_chain(
            UID,
            IID,
            PERSONA,
            CHAIN,
            [
                {"op": "replace", "path": "/status", "value": "completed"},
                {"op": "replace", "path": "/completed_at", "value": "2026-06-04T12:00:00Z"},
                {"op": "add", "path": "/note", "value": "done"},
            ],
        )
    )
    assert merged["status"] == "completed"
    assert merged["completed_at"] == "2026-06-04T12:00:00Z"
    assert merged["note"] == "done"
    # mirror → runtime manifest entry 반영
    rm = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    entry = rm["chains"][0]
    assert entry["status"] == "completed"
    assert entry["completed_at"] == "2026-06-04T12:00:00Z"


def test_patch_chain_no_mirror_for_other_fields(stub_s3, monkeypatch):
    monkeypatch.setattr(chain_store, "_CONTRACT_LOADER", False)
    asyncio.run(chain_store.create_chain(UID, IID, PERSONA, CHAIN, PIPELINE, {}))
    # status/completed_at 아닌 path + remove op (mirror 대상 아님)
    merged = asyncio.run(
        chain_store.patch_chain(
            UID,
            IID,
            PERSONA,
            CHAIN,
            [
                {"op": "replace", "path": "/rt_count", "value": 3},
                {"op": "remove", "path": "/error"},
            ],
        )
    )
    assert merged["rt_count"] == 3
    assert "error" not in merged
    # mirror_fields 비어 → runtime manifest entry 변경 없음 (status 그대로 pending)
    rm = asyncio.run(chain_store.get_chains_manifest(UID, IID))
    assert rm["chains"][0]["status"] == "pending"


def test_patch_chain_on_missing_starts_empty(stub_s3):
    # cur = read(key) or {} → 없는 chain 도 빈 dict 에서 시작
    merged = asyncio.run(
        chain_store.patch_chain(
            UID, IID, PERSONA, "fresh-chain", [{"op": "add", "path": "/x", "value": 1}]
        )
    )
    assert merged == {"x": 1}


# ── read_trail (없음→b"" / 있음) ──────────────────────────────────────────────


def test_read_trail_missing_returns_empty_bytes(stub_s3):
    assert asyncio.run(chain_store.read_trail(UID, IID, PERSONA, "no-trail")) == b""


def test_append_then_read_trail(stub_s3):
    asyncio.run(chain_store.append_trail(UID, IID, PERSONA, CHAIN, {"event": "started"}))
    asyncio.run(chain_store.append_trail(UID, IID, PERSONA, CHAIN, {"event": "done"}))
    raw = asyncio.run(chain_store.read_trail(UID, IID, PERSONA, CHAIN))
    lines = raw.decode("utf-8").strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["event"] == "started"
    assert second["event"] == "done"
    assert "ts" in first and "ts" in second


# ── append_trail 신규 (기존 없음 → except existing="") ────────────────────────


def test_append_trail_new_starts_empty(stub_s3):
    asyncio.run(chain_store.append_trail(UID, IID, PERSONA, "brand-new", {"event": "init"}))
    tkey = vm.trail_key(UID, IID, PERSONA, "brand-new")
    assert tkey in stub_s3
    rec = json.loads(stub_s3[tkey].decode("utf-8").strip())
    assert rec["event"] == "init"


# ── create_rt / get_rt ────────────────────────────────────────────────────────


def test_create_rt_defaults(stub_s3):
    rt = asyncio.run(
        chain_store.create_rt(UID, IID, PERSONA, CHAIN, {"rt_id": "rt-1", "step_id": "s0"})
    )
    assert rt["rt_id"] == "rt-1"
    assert rt["state"] == "pending"
    assert rt["retry_count"] == 0
    assert rt["max_retries"] == 3
    assert rt["sse_events"] == []
    assert "created_at" in rt
    assert "updated_at" in rt
    key = vm.rt_key(UID, IID, PERSONA, CHAIN, "rt-1")
    assert key in stub_s3


def test_create_rt_preserves_existing_created_at(stub_s3):
    rt = asyncio.run(
        chain_store.create_rt(
            UID,
            IID,
            PERSONA,
            CHAIN,
            {"rt_id": "rt-2", "created_at": "2020-01-01T00:00:00Z", "state": "running"},
        )
    )
    # created_at 보존, state 도 setdefault 라 기존값 유지
    assert rt["created_at"] == "2020-01-01T00:00:00Z"
    assert rt["state"] == "running"


def test_get_rt_existing_and_missing(stub_s3):
    asyncio.run(chain_store.create_rt(UID, IID, PERSONA, CHAIN, {"rt_id": "rt-3"}))
    got = asyncio.run(chain_store.get_rt(UID, IID, PERSONA, CHAIN, "rt-3"))
    assert got is not None and got["rt_id"] == "rt-3"
    assert asyncio.run(chain_store.get_rt(UID, IID, PERSONA, CHAIN, "ghost")) is None


# ── patch_rt (일반 ops / sse_events_append 특수 / cleaned_ops 빈 경우) ─────────


def test_patch_rt_normal_ops(stub_s3):
    asyncio.run(chain_store.create_rt(UID, IID, PERSONA, CHAIN, {"rt_id": "rt-n"}))
    merged = asyncio.run(
        chain_store.patch_rt(
            UID,
            IID,
            PERSONA,
            CHAIN,
            "rt-n",
            [{"op": "replace", "path": "/state", "value": "succeeded"}],
        )
    )
    assert merged["state"] == "succeeded"
    assert "updated_at" in merged


def test_patch_rt_sse_events_append(stub_s3):
    asyncio.run(chain_store.create_rt(UID, IID, PERSONA, CHAIN, {"rt_id": "rt-sse"}))
    merged = asyncio.run(
        chain_store.patch_rt(
            UID,
            IID,
            PERSONA,
            CHAIN,
            "rt-sse",
            [
                {"op": "replace", "path": "/state", "value": "running"},
                {"op": "add", "path": "/sse_events_append", "value": [{"e": 1}, {"e": 2}]},
            ],
        )
    )
    assert merged["state"] == "running"
    assert merged["sse_events"] == [{"e": 1}, {"e": 2}]
    # 두 번째 append 누적
    merged2 = asyncio.run(
        chain_store.patch_rt(
            UID,
            IID,
            PERSONA,
            CHAIN,
            "rt-sse",
            [{"op": "add", "path": "/sse_events_append", "value": [{"e": 3}]}],
        )
    )
    assert merged2["sse_events"] == [{"e": 1}, {"e": 2}, {"e": 3}]


def test_patch_rt_sse_append_only_no_cleaned_ops(stub_s3):
    # cleaned_ops 가 비면 merged = cur (apply_json_patch 미호출 분기)
    asyncio.run(chain_store.create_rt(UID, IID, PERSONA, CHAIN, {"rt_id": "rt-only"}))
    merged = asyncio.run(
        chain_store.patch_rt(
            UID,
            IID,
            PERSONA,
            CHAIN,
            "rt-only",
            [{"op": "add", "path": "/sse_events_append", "value": [{"only": True}]}],
        )
    )
    assert merged["sse_events"] == [{"only": True}]
    assert merged["rt_id"] == "rt-only"


def test_patch_rt_sse_append_non_list_value_ignored(stub_s3):
    # value 가 list 아니면 (isinstance False) extend 안 함. cleaned_ops 도 비어
    # merged = cur, sse_to_append 비어 → setdefault/extend 미실행.
    asyncio.run(chain_store.create_rt(UID, IID, PERSONA, CHAIN, {"rt_id": "rt-bad"}))
    merged = asyncio.run(
        chain_store.patch_rt(
            UID,
            IID,
            PERSONA,
            CHAIN,
            "rt-bad",
            [{"op": "add", "path": "/sse_events_append", "value": "not-a-list"}],
        )
    )
    # 기존 빈 sse_events 그대로
    assert merged["sse_events"] == []


def test_patch_rt_on_missing_starts_empty(stub_s3):
    # cur = read(key) or {} → 없는 rt 빈 dict 시작
    merged = asyncio.run(
        chain_store.patch_rt(
            UID,
            IID,
            PERSONA,
            CHAIN,
            "fresh-rt",
            [{"op": "add", "path": "/state", "value": "pending"}],
        )
    )
    assert merged["state"] == "pending"
    assert "updated_at" in merged


# ── get_agent_state (없음 기본 / 있음) / put_agent_state ──────────────────────


def test_get_agent_state_default_when_missing(stub_s3):
    """default = 빈 envelope 동형 (컨텍스트 ② — messages 키 없음, legacy 감지와 충돌 방지)."""
    state = asyncio.run(chain_store.get_agent_state(UID, IID, PERSONA, "no-state"))
    assert state["persona"] == PERSONA
    assert state["schema_version"] == 1
    assert state["vendor"] is None
    assert state["model"] is None
    assert state["items"] == []
    assert "messages" not in state
    assert "updated_at" in state


def test_put_then_get_agent_state(stub_s3):
    """PUT body(envelope) pass-through — persona/updated_at 만 CM 이 스탬프."""
    env = {
        "schema_version": 1,
        "vendor": "gemini",
        "model": "gemini-3.1-pro-preview",
        "items": [{"author": "user", "content": {"role": "user", "parts": [{"text": "hi"}]}}],
    }
    put = asyncio.run(chain_store.put_agent_state(UID, IID, PERSONA, CHAIN, env))
    assert put["persona"] == PERSONA
    assert put["vendor"] == "gemini"
    assert put["items"] == env["items"]
    assert "updated_at" in put
    key = vm.agent_state_key(UID, IID, PERSONA, CHAIN)
    assert key in stub_s3
    got = asyncio.run(chain_store.get_agent_state(UID, IID, PERSONA, CHAIN))
    assert got["items"] == env["items"]
    assert got["model"] == "gemini-3.1-pro-preview"


def test_list_active_chains_scans_all_sessions(stub_s3):
    """전 세션 스캔 → pending/active chain 만 (done 제외). DRO 재시작 자동복구 진입점 (A-3)."""
    asyncio.run(chain_store.add_chain_to_manifest("uA", "wA", "c1", PIPELINE, 2))  # pending
    asyncio.run(chain_store.add_chain_to_manifest("uA", "wA", "c2", PIPELINE, 2))
    asyncio.run(chain_store.update_chain_in_manifest("uA", "wA", "c2", status="active"))
    asyncio.run(chain_store.add_chain_to_manifest("uA", "wA", "c3", PIPELINE, 2))
    asyncio.run(chain_store.update_chain_in_manifest("uA", "wA", "c3", status="done"))  # 제외
    asyncio.run(chain_store.add_chain_to_manifest("uB", "wB", "c9", PIPELINE, 3))  # 타 세션 pending

    out = chain_store.list_active_chains()
    got = {(c["user_id"], c["work_id"], c["chain_id"], c["status"]) for c in out}
    assert ("uA", "wA", "c1", "pending") in got
    assert ("uA", "wA", "c2", "active") in got
    assert ("uB", "wB", "c9", "pending") in got
    assert all(c["chain_id"] != "c3" for c in out)  # done 제외
    c1 = next(c for c in out if c["chain_id"] == "c1")
    assert c1["persona"] == 2 and c1["pipeline_id"] == PIPELINE
