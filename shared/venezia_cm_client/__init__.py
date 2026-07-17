"""공통 CM HTTP 클라이언트 base (D-4).

세 컨테이너(DRO/Nexus/Actor)의 `src/cm_client.CMClient` 가 이 `CMClientBase` 를 상속해
**고유 메서드를 그 위에** 추가한다 (DRO chain/queue · Nexus identity/profile/session ·
Actor agent_state/model-write/drawing-part). 공통부만 여기:
  - httpx 연결 / aclose
  - `_model_get`(RFC 6901 pointer) · `_get_or_none` (404→None)
  - `dict_to_add_ops` (RFC 6902 안전한 upsert) — 모듈 레벨 헬퍼
  - 세 컨테이너 동일한 model GET 4종 (conversation · CMM · UR · drawing manifest)

base_url 은 각 컨테이너의 `settings.CM_URL` (= `venezia_topology.service_url("cm")` / env override)
을 super().__init__ 로 전달 — base 가 topology 를 직접 import 하지 않아 컨테이너 설정을 존중.
"""

from __future__ import annotations

from typing import Any

import httpx


def dict_to_add_ops(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """flat dict → RFC 6902 add ops array. top-level key 마다 1 op.

    `add` 는 RFC 6902 상 *존재하면 교체, 없으면 추가* — `replace` 는 *path 존재 필수* 라
    optional field 가 처음 들어올 때 `replace` 면 422. nested dict sub-key 부분 update 는
    raw ops 직접 전달 권장 (이 헬퍼는 top-level 교체만).
    """
    return [{"op": "add", "path": f"/{k}", "value": v} for k, v in fields.items()]


class CMClientBase:
    """컨테이너 cm_client 가 상속하는 공통 base. base_url = 컨테이너 settings.CM_URL."""

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _model_get(self, url: str, pointer: str = "") -> Any:
        """공통 model GET — pointer="" 면 root 전체, 아니면 ?pointer=/path 로 서버 부분 fetch."""
        params = {"pointer": pointer} if pointer else None
        r = await self._client.get(url, params=params)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def _get_or_none(self, url: str) -> Any:
        """단순 GET, 404 → None."""
        r = await self._client.get(url)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    # ── 공통 model GET (세 컨테이너 동일) ──

    async def get_conversation(self, user_id: str, work_id: str, pointer: str = "") -> Any:
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/00.dro/conversation"
        return await self._model_get(url, pointer)

    async def get_concept_maturity_model(
        self, user_id: str, work_id: str, pointer: str = ""
    ) -> Any:
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/concept-maturity-model"
        return await self._model_get(url, pointer)

    async def get_user_roadmap(self, user_id: str, work_id: str, pointer: str = "") -> Any:
        """UR GET — pointer="" 면 top-level array 또는 None, pointer 지정 시 subtree."""
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/user-roadmap"
        return await self._model_get(url, pointer)

    async def get_drawing_manifest(self, user_id: str, work_id: str) -> dict[str, Any] | None:
        url = f"{self.base}/sessions/{user_id}/{work_id}/drawings/manifest"
        return await self._get_or_none(url)
