"""invoke suites 공유 fixture (Phase 0 인프라).

모든 무거운 import 는 **fixture 본문 안에서 lazy** — 각 패키지 ephemeral venv 가 실제로
가진 dep 만 쓰도록(collection 시점에 없는 dep 를 module-level import 해서 전 suite 가
깨지지 않게). module-level 은 stdlib + pytest 만.

fixture (Phase 1+ 가 사용):
  - stub_s3        : 400.CM store 의 boto3 S3 를 in-memory stub 로 교체 (store._s3_client 주입/복구)
  - asgi_client    : httpx.ASGITransport AsyncClient 팩토리 — factory(app) → AsyncClient
  - fixture_actor_env : LLM_MODE=FIXTURE + src.* 모듈 캐시 클리어 (300.Actor)
  - pipelines_env  : PIPELINES_DIR=@pipelines (pipeline_walker/loader)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _root() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "@pipelines").is_dir():
            return p
    raise FileNotFoundError("project root (@pipelines) not found")


ROOT = _root()

# shared/ source 를 sys.path 최우선 → venezia_* 를 venv 의 stale wheel(non-editable path-dep,
# version 고정이라 source 변경 미반영) 대신 라이브 source 로 import. config.py 의 모드 default_factory
# 가 venezia_deployment 를 lazy import 하므로, 어느 test 모듈보다 먼저(conftest 시점) 깔아둬야
# source 가 잡힌다. (단순 path 추가 — 무거운 import 아님.)
_SHARED = str(ROOT / "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)


@pytest.fixture
def stub_s3():
    """400.CM store 의 boto3 S3 client 를 in-memory stub 으로 교체.

    `store._s3_client` 주입 → 모든 store/chain_store/queue_store 가 메모리 동작.
    in-memory _StubS3 (get/put/delete/list — clean/list 경로 포함).
    yield 는 backing dict (테스트가 키 직접 검사 가능).
    """
    from src import store  # 400.CM venv 한정

    mem: dict[str, bytes] = {}

    class _StubS3:
        def get_object(self, Bucket, Key):
            if Key not in mem:
                from botocore.exceptions import ClientError

                raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "miss"}}, "GetObject")

            class _Body:
                def __init__(self, b: bytes) -> None:
                    self._b = b

                def read(self) -> bytes:
                    return self._b

            return {"Body": _Body(mem[Key])}

        def put_object(self, Bucket, Key, Body, ContentType=""):
            mem[Key] = Body if isinstance(Body, bytes) else str(Body).encode()
            return {"ETag": "stub"}

        def delete_object(self, Bucket, Key):
            mem.pop(Key, None)
            return {}

        def list_objects_v2(self, Bucket, Prefix="", **_kw):
            keys = sorted(k for k in mem if k.startswith(Prefix))
            return {"Contents": [{"Key": k} for k in keys], "KeyCount": len(keys)}

        def delete_objects(self, Bucket, Delete):
            for o in Delete.get("Objects", []):
                mem.pop(o["Key"], None)
            return {"Deleted": Delete.get("Objects", [])}

    prev = getattr(store, "_s3_client", None)
    store._s3_client = _StubS3()
    try:
        yield mem
    finally:
        store._s3_client = prev


@pytest.fixture
def asgi_client():
    """httpx.ASGITransport AsyncClient 팩토리. 사용: `async with asgi_client(app) as c:`."""
    import httpx

    def _make(app):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return _make


@pytest.fixture
def fixture_actor_env(monkeypatch):
    """LLM_MODE=FIXTURE 강제 + src.* 모듈 캐시 클리어 (config/llm 재로드)."""
    monkeypatch.setenv("LLM_MODE", "FIXTURE")
    for m in [k for k in list(sys.modules) if k == "src" or k.startswith("src.")]:
        sys.modules.pop(m, None)
    yield


@pytest.fixture
def pipelines_env(monkeypatch):
    """PIPELINES_DIR 을 repo @pipelines 로 (loader/pipeline_walker 단위테스트)."""
    monkeypatch.setenv("PIPELINES_DIR", str(ROOT / "@pipelines"))
    yield
