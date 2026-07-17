"""CM aux module 단위테스트 — queue_store / lock / config.

probe 트랙 (400.CM venv). stub_s3 (in-memory S3) 위에서 직접 호출.
async 함수는 pytest-asyncio mark 없이 asyncio.run() 으로 구동.
"""

from __future__ import annotations

import asyncio

import venezia_memory as vm

from src import config, queue_store
from src.lock import lock_for

U = "user-uuid-1"
INV = "inv-uuid-1"


# ── queue_store ───────────────────────────────────────────────────────────────


def test_get_persona_queue_default_when_absent(stub_s3):
    async def _run():
        pq = await queue_store.get_persona_queue(U, INV, 1)
        assert pq["pending"] == []
        assert pq["leases"] == {}
        assert "updated_at" in pq

    asyncio.run(_run())


def test_persona_queue_push_accumulates(stub_s3):
    mem = stub_s3

    async def _run():
        await queue_store.persona_queue_push(U, INV, 1, "rt-1", "chain-1")
        pq = await queue_store.persona_queue_push(U, INV, 1, "rt-2", "chain-1")
        assert [p["rt_id"] for p in pq["pending"]] == ["rt-1", "rt-2"]
        assert all(p["chain_id"] == "chain-1" for p in pq["pending"])
        # backing dict 에 queue 키가 실제로 기록됐는지 확인
        key = vm.queue_key(U, INV, 1)
        assert key in mem

    asyncio.run(_run())


def test_persona_queue_pop_head_to_lease_with_actor(stub_s3):
    async def _run():
        await queue_store.persona_queue_push(U, INV, 1, "rt-1", "chain-1")
        await queue_store.persona_queue_push(U, INV, 1, "rt-2", "chain-1")
        head = await queue_store.persona_queue_pop(U, INV, 1, actor_id="300.Actor")
        assert head["rt_id"] == "rt-1"
        pq = await queue_store.get_persona_queue(U, INV, 1)
        assert [p["rt_id"] for p in pq["pending"]] == ["rt-2"]
        lease = pq["leases"]["rt-1"]
        assert lease["chain_id"] == "chain-1"
        assert lease["actor"] == "300.Actor"
        assert "started_at" in lease
        assert lease["expires_at"] > lease["started_at"]  # ttl 연동 (D-1)

    asyncio.run(_run())


def test_persona_queue_pop_default_actor_none(stub_s3):
    async def _run():
        await queue_store.persona_queue_push(U, INV, 2, "rt-x", "chain-x")
        head = await queue_store.persona_queue_pop(U, INV, 2)
        assert head["rt_id"] == "rt-x"
        pq = await queue_store.get_persona_queue(U, INV, 2)
        assert pq["leases"]["rt-x"]["actor"] is None

    asyncio.run(_run())


def test_persona_queue_concurrent_leases_coexist(stub_s3):
    """persona cap 세마포어 하의 병렬 dispatch — rt_id 별 lease 동시 다건 (구 단일 슬롯 폐기)."""

    async def _run():
        await queue_store.persona_queue_push(U, INV, 1, "rt-1", "chain-A")
        await queue_store.persona_queue_push(U, INV, 1, "rt-2", "chain-B")
        await queue_store.persona_queue_pop(U, INV, 1, chain_id="chain-A")
        await queue_store.persona_queue_pop(U, INV, 1, chain_id="chain-B")
        pq = await queue_store.get_persona_queue(U, INV, 1)
        assert set(pq["leases"]) == {"rt-1", "rt-2"}

    asyncio.run(_run())


def test_persona_queue_pop_empty_returns_none(stub_s3):
    async def _run():
        head = await queue_store.persona_queue_pop(U, INV, 3)
        assert head is None

    asyncio.run(_run())


def test_persona_queue_release_only_own_rt(stub_s3):
    """release 는 본인 rt_id 만 해제 — 동시 lease 의 타 기록 보존 (구 clear_inflight 오인 삭제 폐기)."""

    async def _run():
        await queue_store.persona_queue_push(U, INV, 1, "rt-1", "chain-A")
        await queue_store.persona_queue_push(U, INV, 1, "rt-2", "chain-B")
        await queue_store.persona_queue_pop(U, INV, 1, chain_id="chain-A")
        await queue_store.persona_queue_pop(U, INV, 1, chain_id="chain-B")
        pq = await queue_store.persona_queue_release(U, INV, 1, "rt-1")
        assert "rt-1" not in pq["leases"]
        assert "rt-2" in pq["leases"]  # 타 RT lease 보존
        # idempotent — 이미 없는 rt 해제는 무해
        again = await queue_store.persona_queue_release(U, INV, 1, "rt-1")
        assert "rt-2" in again["leases"]

    asyncio.run(_run())


def test_persona_queue_expired_lease_lazy_swept(stub_s3):
    """만료 lease 는 다음 큐 작업(push/pop/release) 시 lazy 제거 (D-1 — 별도 데몬 없음)."""

    async def _run():
        await queue_store.persona_queue_push(U, INV, 1, "rt-1", "chain-1")
        await queue_store.persona_queue_pop(U, INV, 1, lease_ttl_s=0.0)  # 즉시 만료
        pq = await queue_store.get_persona_queue(U, INV, 1)
        assert "rt-1" in pq["leases"]  # GET 은 순수 — 청소 안 함
        await queue_store.persona_queue_push(U, INV, 1, "rt-2", "chain-1")  # 큐 작업 → sweep
        pq = await queue_store.get_persona_queue(U, INV, 1)
        assert "rt-1" not in pq["leases"]

    asyncio.run(_run())


def test_persona_queues_are_independent(stub_s3):
    async def _run():
        await queue_store.persona_queue_push(U, INV, 1, "rt-p1", "chain-1")
        await queue_store.persona_queue_push(U, INV, 2, "rt-p2", "chain-2")
        q1 = await queue_store.get_persona_queue(U, INV, 1)
        q2 = await queue_store.get_persona_queue(U, INV, 2)
        assert [p["rt_id"] for p in q1["pending"]] == ["rt-p1"]
        assert [p["rt_id"] for p in q2["pending"]] == ["rt-p2"]

    asyncio.run(_run())


def test_persona_queue_pop_chain_scoped_picks_matching_chain(stub_s3):
    """chain_id 지정 pop 은 그 chain 의 첫 pending 만 — 다른 chain 의 head 는 건드리지 않음.

    동시 다중 chain 이 persona 큐를 공유할 때 한 chain 이 다른 chain 의 RT 를 가져가
    get_rt 404·오소비되는 회귀 방지(queue_store.persona_queue_pop chain_id 분기).
    """

    async def _run():
        await queue_store.persona_queue_push(U, INV, 1, "rt-a1", "chain-A")
        await queue_store.persona_queue_push(U, INV, 1, "rt-b1", "chain-B")
        # head 는 chain-A 의 rt-a1 이지만 chain-B 로 pop → chain-B 의 rt-b1
        head = await queue_store.persona_queue_pop(U, INV, 1, chain_id="chain-B")
        assert head is not None
        assert head["rt_id"] == "rt-b1"
        assert head["chain_id"] == "chain-B"
        # chain-A head 는 pending 에 보존
        pq = await queue_store.get_persona_queue(U, INV, 1)
        assert [p["rt_id"] for p in pq["pending"]] == ["rt-a1"]
        assert pq["leases"]["rt-b1"]["chain_id"] == "chain-B"

    asyncio.run(_run())


def test_persona_queue_pop_chain_scoped_absent_returns_none(stub_s3):
    """지정 chain_id 의 pending 이 없으면 None — 다른 chain entry 는 보존."""

    async def _run():
        await queue_store.persona_queue_push(U, INV, 1, "rt-a1", "chain-A")
        head = await queue_store.persona_queue_pop(U, INV, 1, chain_id="chain-Z")
        assert head is None
        pq = await queue_store.get_persona_queue(U, INV, 1)
        assert [p["rt_id"] for p in pq["pending"]] == ["rt-a1"]
        assert pq["leases"] == {}

    asyncio.run(_run())


# ── lock ──────────────────────────────────────────────────────────────────────


def test_lock_for_same_key_identity():
    a = lock_for("resource-key-A")
    b = lock_for("resource-key-A")
    assert a is b


def test_lock_for_different_keys_distinct():
    a = lock_for("resource-key-A")
    c = lock_for("resource-key-C")
    assert a is not c


# ── config ────────────────────────────────────────────────────────────────────


def test_settings_defaults():
    assert config.settings.S3_BUCKET  # conftest 가 주입한 값 존재
    assert config.settings.AWS_REGION == "ap-northeast-2"
