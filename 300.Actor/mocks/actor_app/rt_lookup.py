"""실 CM 에서 RT read — fixture 키 (pipeline_id, step_id) 해소의 단일 경로.

CM 의 chain-only 호환 route (`GET /sessions/{u}/{w}/chains/{chain_id}/rts/{rt_id}`,
`400.CM/src/router.py` "probe / 외부 호환용") 를 사용 — persona_dir 매핑·venezia_memory
불필요 (mock 이미지 = minimal, 3f). CM URL 은 mount 된 topology.yaml 에서 직접 파싱.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx
import yaml

from . import config


@lru_cache(maxsize=1)
def cm_url() -> str:
    with open(config.TOPOLOGY_FILE, encoding="utf-8") as f:
        topo = yaml.safe_load(f)
    svc = topo["services"]["cm"]
    return f"http://{svc['host']}:{svc['port']}"


async def get_rt(user_id: str, work_id: str, chain_id: str, rt_id: str) -> dict[str, Any] | None:
    """RT dict 또는 None (404). 그 외 실패는 전파 — 호출측이 SSE error 로 fail-loud."""
    url = f"{cm_url()}/sessions/{user_id}/{work_id}/chains/{chain_id}/rts/{rt_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"CM RT response not a dict: {type(data).__name__}")
    return data
