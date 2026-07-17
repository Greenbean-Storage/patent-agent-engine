"""CM /tree endpoint + store.list_session_keys (스택 없는 CM 로직 검증).

구조검증(verify_structure) 자체는 probe 트랙 소속 — 여기선 CM 의 /tree·list_session_keys
코드만 커버하고, chain/RT/trail/agent_state 생성이 tree 에 반영되는지 raw 로 확인.
"""

from __future__ import annotations

import asyncio


def test_list_session_keys_empty(stub_s3):
    from src import store

    assert store.list_session_keys("nobody", "nothing") == []


def test_tree_lists_session_relative_keys(stub_s3, cm_app, asgi_client):
    import venezia_memory as vm
    from src import store

    u, inv = "u-tree", "i-tree"
    store.write_by_key(vm.context_manifest_key(u, inv), {"status": "draft"})
    store.write_by_key(vm.iom_key(u, inv), {"x": 1})
    # 다른 세션 키 — tree 에 섞이면 안 됨
    store.write_by_key(vm.iom_key("other", "other"), {"y": 2})

    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get(f"/sessions/{u}/{inv}/tree")
            assert r.status_code == 200
            keys = r.json()["keys"]
            assert "manifest.context.yaml" in keys
            assert "models/invention-object-model.json" in keys
            assert all("other" not in k for k in keys)

    asyncio.run(_run())


def test_tree_reflects_chain_resources(stub_s3, cm_app, asgi_client):
    """chain/RT/trail/agent_state 생성이 tree 에 그대로 나타나는지 (CM 코드 구동)."""
    import venezia_memory as vm
    from src import chain_store, store

    u, inv = "u-st", "i-st"
    store.write_by_key(vm.context_manifest_key(u, inv), {"status": "draft"})
    store.write_by_key(vm.iom_key(u, inv), {"x": 1})
    store.write_by_key(vm.cmm_key(u, inv), {"overall_score": 0.5})
    store.write_by_key(vm.conversation_key(u, inv), {"messages": []})
    store.write_by_key(vm.queue_key(u, inv, 2), {"pending": []})

    async def _run():
        await chain_store.create_chain(u, inv, 2, "c1", "P02.R00.X", {"kind": "user_message"})
        await chain_store.create_rt(u, inv, 2, "c1", {"rt_id": "rt1"})
        await chain_store.append_trail(u, inv, 2, "c1", {"event": "x"})
        await chain_store.put_agent_state(
            u, inv, 2, "c1", {"schema_version": 1, "vendor": "fixture", "model": None, "items": []}
        )
        async with asgi_client(cm_app) as c:
            tree = set((await c.get(f"/sessions/{u}/{inv}/tree")).json()["keys"])
            runtime = (await c.get(f"/sessions/{u}/{inv}/runtime")).json()
        sroot = vm.session_root(u, inv) + "/"
        assert vm.chain_manifest_key(u, inv, 2, "c1")[len(sroot) :] in tree
        assert vm.rt_key(u, inv, 2, "c1", "rt1")[len(sroot) :] in tree
        assert vm.trail_key(u, inv, 2, "c1")[len(sroot) :] in tree
        assert vm.agent_state_key(u, inv, 2, "c1")[len(sroot) :] in tree
        assert any(c.get("chain_id") == "c1" for c in runtime["chains"])

    asyncio.run(_run())


def test_tree_includes_stray_key(stub_s3, cm_app, asgi_client):
    """세션 prefix 안 임의 키도 tree 가 전수 반환 (list_session_keys 의 전수성)."""
    import venezia_memory as vm
    from src import store

    u, inv = "u-or", "i-or"
    store.write_by_key(vm.context_manifest_key(u, inv), {"status": "draft"})
    store.write_by_key(vm.runtime_manifest_key(u, inv), {"chains": []})
    sroot = vm.session_root(u, inv)
    store.write_by_key(f"{sroot}/runtime/99.ghost/queue.json", {"x": 1})

    async def _run():
        async with asgi_client(cm_app) as c:
            keys = (await c.get(f"/sessions/{u}/{inv}/tree")).json()["keys"]
        assert "runtime/99.ghost/queue.json" in keys
        assert "manifest.context.yaml" in keys

    asyncio.run(_run())
