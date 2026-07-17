"""CM in-process exerciser 공유 fixture (probe 트랙, Phase 5).

400.CM venv 에서 실행 (`uv run --directory 400.CM ... pytest tests/probe/cm_exercise`).
boto3 S3 를 in-memory stub 으로 교체 → CM 의 store/chain_store/queue_store 가
메모리 동작. app 은 main.py(=secrets→AWS import) 우회하고 router 로 직접 구성.

async 테스트는 기존 suite 패턴대로 `asyncio.run(...)` 직접 호출 (pytest-asyncio mark 미사용):
    async def _run():
        async with asgi_client(cm_app) as c:
            r = await c.get(...)
    asyncio.run(_run())
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
if str(ROOT / "400.CM") not in sys.path:
    sys.path.insert(0, str(ROOT / "400.CM"))
# venezia_memory 는 source 에서 (400.CM venv 의 설치 wheel 은 path-dep 라 신규 함수 반영 지연).
# shared suite 와 동일 패턴 — 라이브 소스 import.
if str(ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(ROOT / "shared"))

# config.Settings 는 S3_BUCKET 필수 — import(=store/router/main) 전에 주입.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "ap-northeast-2")
os.environ.setdefault("AWS_SECRET_NAME", "")


def _client_error(code: str, op: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": "stub"}}, op)


class _Body:
    def __init__(self, b: bytes) -> None:
        self._b = b

    def read(self) -> bytes:
        return self._b


class _LastModified:
    """boto3 의 datetime LastModified 흉내 — store.list_media 가 .isoformat() 호출."""

    def __init__(self, iso: str) -> None:
        self._iso = iso

    def isoformat(self) -> str:
        return self._iso


class _Paginator:
    """list_objects_v2 paginator stub — Delimiter 유무에 따라 CommonPrefixes/Contents."""

    def __init__(self, mem: dict[str, bytes]) -> None:
        self._mem = mem

    def _content(self, k: str, i: int) -> dict[str, object]:
        return {
            "Key": k,
            "Size": len(self._mem[k]),
            "LastModified": _LastModified(f"2026-06-19T00:00:0{i % 10}+00:00"),
        }

    def paginate(self, Bucket=None, Prefix="", Delimiter=None, **_kw):
        keys = sorted(k for k in self._mem if k.startswith(Prefix))
        if Delimiter:
            commons: list[dict[str, str]] = []
            seen: set[str] = set()
            direct: list[dict[str, object]] = []
            for i, k in enumerate(keys):
                rest = k[len(Prefix) :]
                seg, sep, _tail = rest.partition(Delimiter)
                if sep:
                    cp = Prefix + seg + Delimiter
                    if cp not in seen:
                        seen.add(cp)
                        commons.append({"Prefix": cp})
                else:
                    direct.append(self._content(k, i))
            yield {"CommonPrefixes": commons, "Contents": direct}
        else:
            yield {"Contents": [self._content(k, i) for i, k in enumerate(keys)]}


class StubS3:
    """in-memory boto3 S3 client 대체 — get/put/delete/delete_objects/get_paginator.

    media presigned/list/delete 경로용으로 generate_presigned_post/_url · list_objects_v2 ·
    head_object 도 stub. Content-Type 은 put_object 시 별도 dict 에 기록 (head_object 재현용).
    """

    def __init__(self, mem: dict[str, bytes]) -> None:
        self.mem = mem
        self.content_types: dict[str, str] = {}

    def get_object(self, Bucket, Key):
        if Key not in self.mem:
            raise _client_error("NoSuchKey", "GetObject")
        return {"Body": _Body(self.mem[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=""):
        self.mem[Key] = Body if isinstance(Body, bytes) else str(Body).encode("utf-8")
        if ContentType:
            self.content_types[Key] = ContentType
        return {"ETag": "stub"}

    def delete_object(self, Bucket, Key):
        self.mem.pop(Key, None)
        self.content_types.pop(Key, None)
        return {}

    def delete_objects(self, Bucket, Delete):
        for o in Delete.get("Objects", []):
            self.mem.pop(o["Key"], None)
            self.content_types.pop(o["Key"], None)
        return {"Deleted": Delete.get("Objects", [])}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _Paginator(self.mem)

    # -- media presigned / list / head (work-level media direct) --------------

    def generate_presigned_post(self, Bucket, Key, Fields=None, Conditions=None, ExpiresIn=None):
        return {
            "url": f"https://s3.example/{Bucket}",
            "fields": {**(Fields or {}), "key": Key},
        }

    def generate_presigned_url(self, ClientMethod, Params=None, ExpiresIn=None):
        params = Params or {}
        return f"https://s3.example/{params.get('Bucket')}/{params.get('Key')}?sig=stub"

    def list_objects_v2(self, Bucket, Prefix="", MaxKeys=None):
        keys = sorted(k for k in self.mem if k.startswith(Prefix))
        if MaxKeys is not None:
            keys = keys[:MaxKeys]
        contents = [
            {
                "Key": k,
                "Size": len(self.mem[k]),
                "LastModified": _LastModified(f"2026-06-19T00:00:0{i % 10}+00:00"),
            }
            for i, k in enumerate(keys)
        ]
        if not contents:
            return {"KeyCount": 0}
        return {"Contents": contents, "KeyCount": len(contents)}

    def head_object(self, Bucket, Key):
        if Key not in self.mem:
            raise _client_error("NoSuchKey", "HeadObject")
        ct = self.content_types.get(Key)
        return {"ContentType": ct} if ct is not None else {}


@pytest.fixture
def stub_s3():
    """store._s3_client 를 StubS3 로 교체. yield = backing dict (키 직접 검사용)."""
    from src import store

    mem: dict[str, bytes] = {}
    prev = getattr(store, "_s3_client", None)
    store._s3_client = StubS3(mem)
    try:
        yield mem
    finally:
        store._s3_client = prev


@pytest.fixture(scope="module")
def cm_app():
    """CM FastAPI app — main.py(secrets→AWS) 우회, router 직접 마운트."""
    from fastapi import FastAPI

    from src.router import router

    app = FastAPI(title="cm-exercise")
    app.include_router(router)
    return app


@pytest.fixture
def asgi_client():
    """httpx.ASGITransport AsyncClient 팩토리. `async with asgi_client(cm_app) as c:`."""
    import httpx

    def _make(app):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cm")

    return _make
