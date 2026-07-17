"""CM HTTP 클라이언트. DRO(200.DRO) 가 CM(400.CM) endpoint 를 호출하는 wrapper.

DRO 가 직접 쓰는 표면만 보존 (write 계열 session/conversation-append/context-manifest
는 Nexus 전용 → DRO 사본에서 제거):
- persona dialog · DRC chain (runtime/{persona}/{cid}) · RT · persona queue (RT 큐)
- model GET (IOM / CDS / CMM / UR / conversation read, RFC 6901 pointer)
- drawing manifest / document (output)
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import venezia_memory as vm
from venezia_cm_client import CMClientBase, dict_to_add_ops

from .config import settings


class CMClient(CMClientBase):
    """DRO 고유 — DRC chain/RT/persona queue + trail/dialog + IOM/CDS + document.

    공통(httpx·_model_get·_get_or_none·dict_to_add_ops·model GET 4종)은 `CMClientBase` (D-4).
    """

    def __init__(self, base_url: str | None = None, timeout: float = 60.0) -> None:
        super().__init__(base_url or settings.CM_URL, timeout)

    # ── persona dialog (누적) ──

    async def get_persona_dialog(
        self, user_id: str, work_id: str, persona: int, name: str
    ) -> dict | None:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/dialog/{name}"
        r = await self._client.get(url)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    # ── DRC chain (runtime/{persona}/{cid}) ──

    async def create_chain(
        self,
        user_id: str,
        work_id: str,
        chain_id: str,
        pipeline_id: str,
        persona: int,
        trigger: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime"
        body = {
            "chain_id": chain_id,
            "pipeline_id": pipeline_id,
            "persona": persona,
            "trigger": trigger,
        }
        r = await self._client.post(url, json=body)
        r.raise_for_status()
        return r.json()

    async def get_chain(
        self, user_id: str, work_id: str, persona: int, chain_id: str
    ) -> dict[str, Any]:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}"
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()

    async def list_active_chains(self) -> list[dict[str, Any]]:
        """전 세션 미완(pending/active) chain 열거 — DRO 재시작 자동복구용 (A-3).
        각 entry: {user_id, work_id, persona, chain_id, pipeline_id, status}."""
        url = f"{self.base}/admin/active-chains"
        r = await self._client.get(url)
        r.raise_for_status()
        return (r.json() or {}).get("chains") or []

    async def get_chains(self, user_id: str, work_id: str) -> list[dict[str, Any]]:
        """이 work 의 chain 인덱스(runtime manifest) entry 들 — admission dedup 판정용 (D-1).
        각 entry: {chain_id, pipeline_id, persona, status, ...}."""
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime"
        r = await self._client.get(url)
        r.raise_for_status()
        return (r.json() or {}).get("chains") or []

    async def get_trail(
        self, user_id: str, work_id: str, persona: int, chain_id: str
    ) -> list[dict[str, Any]]:
        """chain trail(ndjson) → event list. 재시작 시 완료 step 재구성용 (A-3).
        없으면(404) 빈 list. 깨진 줄은 건너뜀."""
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/trail"
        r = await self._client.get(url)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        events: list[dict[str, Any]] = []
        for line in r.text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            with contextlib.suppress(ValueError, TypeError):
                events.append(json.loads(stripped))
        return events

    async def patch_chain(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        chain_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """P-E: RFC 6902 ops array 로 전송. fields 의 top-level key 마다 add op (안전한 upsert)."""
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}"
        ops = dict_to_add_ops(fields)
        r = await self._client.patch(url, json=ops)
        r.raise_for_status()
        return r.json()

    async def append_trail(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        chain_id: str,
        event: dict[str, Any],
    ) -> None:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/trail"
        r = await self._client.post(url, json=event)
        r.raise_for_status()

    # ── RT ──

    async def create_rt(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        chain_id: str,
        rt: dict[str, Any],
    ) -> dict[str, Any]:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/rts"
        r = await self._client.post(url, json=rt)
        r.raise_for_status()
        return r.json()

    async def get_rt(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        chain_id: str,
        rt_id: str,
    ) -> dict[str, Any]:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/rts/{rt_id}"
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()

    async def patch_rt(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        chain_id: str,
        rt_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """P-E: RFC 6902 ops array 로 전송. fields top-level key 마다 add op (안전한 upsert)."""
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/rts/{rt_id}"
        ops = dict_to_add_ops(fields)
        r = await self._client.patch(url, json=ops)
        r.raise_for_status()
        return r.json()

    # ── persona queue (RT 큐 — chain_queue 폐기) ──

    async def get_persona_queue(self, user_id: str, work_id: str, persona: int) -> dict[str, Any]:
        """persona RT 큐 전체 read (pending[]+leases{}). worker 가 다음 구동할 chain 선택용
        (pending[0].chain_id) — 순수 GET, lease 안 잡음 (pop 과 별개). CM endpoint 기존재
        (`400.CM/src/router.py` GET .../runtime/{persona}/queue)."""
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/queue"
        r = await self._client.get(url)
        if r.status_code == 404:
            return {"pending": [], "leases": {}}
        r.raise_for_status()
        return r.json()

    async def persona_queue_push(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        rt_id: str,
        chain_id: str,
    ) -> dict[str, Any]:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/queue/push"
        r = await self._client.post(url, json={"rt_id": rt_id, "chain_id": chain_id})
        r.raise_for_status()
        return r.json()

    async def persona_queue_pop(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        chain_id: str | None = None,
        lease_ttl_s: float | None = None,
    ) -> dict[str, Any]:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/queue/pop"
        body: dict[str, Any] = {}
        if chain_id is not None:
            body["chain_id"] = chain_id
        if lease_ttl_s is not None:
            body["lease_ttl_s"] = lease_ttl_s
        r = await self._client.post(url, json=body or None)
        r.raise_for_status()
        return r.json()

    async def persona_queue_release(
        self, user_id: str, work_id: str, persona: int, rt_id: str
    ) -> dict[str, Any]:
        """본인 rt_id lease 해제 (구 clear_inflight 폐기 — rt_id 별 lease, D-1)."""
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/queue/release"
        r = await self._client.post(url, json={"rt_id": rt_id})
        r.raise_for_status()
        return r.json()

    # ── model GET (DRO 고유: IOM·CDS. 공통 conversation/CMM/UR/drawing-manifest 는 base) ──

    async def get_iom(self, user_id: str, work_id: str, pointer: str = "") -> Any:
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/invention-object-model"
        return await self._model_get(url, pointer)

    async def get_concept_discovery_stack(
        self, user_id: str, work_id: str, pointer: str = ""
    ) -> Any:
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/concept-discovery-stack"
        return await self._model_get(url, pointer)

    async def upload_document(
        self,
        user_id: str,
        work_id: str,
        filename: str,
        body: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        url = f"{self.base}/sessions/{user_id}/{work_id}/outputs/{filename}"
        files = {"file": (filename, body, content_type)}
        r = await self._client.put(url, files=files)
        r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return {"filename": filename, "size": len(body)}
        ctype = r.headers.get("content-type", "")
        return r.json() if ctype.startswith("application/json") else {}

    async def download_document(self, user_id: str, work_id: str, filename: str) -> bytes | None:
        url = f"{self.base}/sessions/{user_id}/{work_id}/outputs/{filename}"
        r = await self._client.get(url)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content


_default: CMClient | None = None


def get_cm_client() -> CMClient:
    global _default
    if _default is None:
        _default = CMClient()
    return _default
