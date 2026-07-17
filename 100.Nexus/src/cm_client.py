"""CM HTTP 클라이언트. Nexus(100.Nexus) 가 CM(400.CM) endpoint 를 호출하는 wrapper.

남은 표면 (chain/RT/queue/dialog 는 DRO 전용 → Nexus 사본에서 제거):
- users/ (identity·profile — 인증·식별, PII 0)
- session (create/list) · context manifest (mypage 메타)
- conversation (00.dro) · media presigned (presign-put/get·list·delete)
- model GET (IOM / CMM / UR / conversation, RFC 6901 pointer)
- drawing manifest / document (output)
"""

from __future__ import annotations

import hashlib
from typing import Any

from venezia_cm_client import CMClientBase

from .config import settings


class CMClient(CMClientBase):
    """Nexus 고유 — users(identity/profile)·session·context manifest·conversation·media presigned·
    document. 공통(httpx·_model_get·model GET 4종)은 `CMClientBase` (D-4).
    """

    def __init__(self, base_url: str | None = None, timeout: float = 60.0) -> None:
        super().__init__(base_url or settings.CM_URL, timeout)

    # ── users/ (인증·식별 — sessions 와 별개 루트, PII 0) ──

    async def get_identity(self, provider: str, provider_sub: str) -> dict[str, Any] | None:
        """(provider, sub) → { user_id } 조회. 없으면 None."""
        r = await self._client.get(f"{self.base}/users/identities/{provider}/{provider_sub}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def put_identity(self, provider: str, provider_sub: str, user_id: str) -> None:
        r = await self._client.put(
            f"{self.base}/users/identities/{provider}/{provider_sub}",
            json={"user_id": user_id},
        )
        r.raise_for_status()

    async def delete_identity(
        self, provider: str, provider_sub: str, expected_user_id: str | None = None
    ) -> None:
        """disconnect — (provider, sub) 로그인 인덱스 제거 (멱등). expected_user_id 주면
        매핑이 그 user 를 가리킬 때만 삭제(재발급된 다른 user 매핑 오삭제 방지)."""
        params = {"user_id": expected_user_id} if expected_user_id is not None else None
        r = await self._client.delete(
            f"{self.base}/users/identities/{provider}/{provider_sub}", params=params
        )
        r.raise_for_status()

    async def get_profile(self, user_id: str) -> dict[str, Any] | None:
        r = await self._client.get(f"{self.base}/users/profiles/{user_id}/profile")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def put_profile(self, user_id: str, data: dict[str, Any]) -> None:
        r = await self._client.put(f"{self.base}/users/profiles/{user_id}/profile", json=data)
        r.raise_for_status()

    async def patch_profile(self, user_id: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
        r = await self._client.patch(f"{self.base}/users/profiles/{user_id}/profile", json=ops)
        r.raise_for_status()
        return r.json()

    # ── idempotency-key (D6, user-level 영속) ──

    @staticmethod
    def _key_hash(key: str) -> str:
        """client 제공 opaque Idempotency-Key → sha256 hex (URL·파일명 안전)."""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    async def get_idempotency(self, user_id: str, key: str) -> dict[str, Any] | None:
        """Idempotency-Key record 조회 (D6). 없으면 None."""
        kh = self._key_hash(key)
        r = await self._client.get(f"{self.base}/users/idempotency/{user_id}/{kh}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def put_idempotency(self, user_id: str, key: str, record: dict[str, Any]) -> None:
        """Idempotency-Key 완료 기록 저장 (확정)."""
        kh = self._key_hash(key)
        r = await self._client.put(f"{self.base}/users/idempotency/{user_id}/{kh}", json=record)
        r.raise_for_status()

    async def claim_idempotency(
        self, user_id: str, key: str, content_hash: str | None = None
    ) -> tuple[str, dict[str, Any] | None]:
        """원자적 선점 (D6). 반환 (state, record): state ∈ {done(+record), in_flight(+record), claimed}.
        content_hash 를 주면 선점 마커에 보존 → in_flight/done 회신 시 같은 키·다른 내용 충돌 검출."""
        kh = self._key_hash(key)
        json_body = {"content_hash": content_hash} if content_hash is not None else None
        r = await self._client.post(
            f"{self.base}/users/idempotency/{user_id}/{kh}/claim", json=json_body
        )
        r.raise_for_status()
        d = r.json()
        return (d["state"], d.get("record"))

    async def delete_idempotency(self, user_id: str, key: str) -> None:
        """선점 해제 (부수효과 실패 시)."""
        kh = self._key_hash(key)
        r = await self._client.delete(f"{self.base}/users/idempotency/{user_id}/{kh}")
        r.raise_for_status()

    # ── refresh token family (C1 인증 — 회전·재사용 탐지·logout revoke) ──

    async def put_refresh_family(self, user_id: str, family_id: str, jti: str) -> None:
        """최초 로그인 — 새 family 기록 (current_jti=jti)."""
        r = await self._client.put(
            f"{self.base}/users/refresh-tokens/{user_id}/{family_id}",
            json={"current_jti": jti},
        )
        r.raise_for_status()

    async def rotate_refresh_family(
        self, user_id: str, family_id: str, expected_jti: str, new_jti: str
    ) -> str:
        """회전 CAS — expected_jti 일치 시 new_jti 로 교체. 반환 result ∈
        {rotated, concurrent, reuse, revoked, missing}. concurrent=직전 jti grace(동시/재시도),
        reuse=오래된 jti(탈취 의심) → CM 이 family revoke."""
        r = await self._client.post(
            f"{self.base}/users/refresh-tokens/{user_id}/{family_id}/rotate",
            json={"expected_jti": expected_jti, "new_jti": new_jti},
        )
        r.raise_for_status()
        return str(r.json()["result"])

    async def revoke_refresh_family(self, user_id: str, family_id: str) -> None:
        """logout — family revoke (멱등)."""
        r = await self._client.post(
            f"{self.base}/users/refresh-tokens/{user_id}/{family_id}/revoke"
        )
        r.raise_for_status()

    # ── session ──

    async def create_session(self, user_id: str | None = None) -> dict[str, Any]:
        body = {"user_id": user_id} if user_id else {}
        r = await self._client.post(f"{self.base}/sessions", json=body)
        r.raise_for_status()
        return r.json()

    async def list_sessions(self, user_id: str) -> dict[str, Any]:
        r = await self._client.get(f"{self.base}/sessions/{user_id}")
        r.raise_for_status()
        return r.json()

    # ── context manifest (mypage 메타 — title / title_source / last_activity_at 등) ──

    async def get_context_manifest(self, user_id: str, work_id: str) -> dict[str, Any] | None:
        url = f"{self.base}/sessions/{user_id}/{work_id}/manifest/context"
        r = await self._client.get(url)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def patch_context_manifest(
        self, user_id: str, work_id: str, ops: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """P-E: RFC 6902 JSON Patch ops array."""
        url = f"{self.base}/sessions/{user_id}/{work_id}/manifest/context"
        r = await self._client.patch(url, json=ops)
        r.raise_for_status()
        return r.json()

    # ── conversation (00.dro) ──

    async def append_conversation(
        self, user_id: str, work_id: str, message: dict[str, Any]
    ) -> int:
        """append 후 그 turn 의 메시지 id(= conversation 내 0-based 위치) 반환 (A-4 server id).

        correlation_id(meta) 가 있으면 CM 이 멱등 append — 그 turn 의 위치를 찾아 반환(재처리 시
        이미 있던 turn 의 id 를 그대로). 없으면 방금 append 된 마지막 turn 의 위치."""
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/00.dro/conversation/append"
        r = await self._client.post(url, json=message)
        r.raise_for_status()
        msgs = r.json().get("messages", [])
        corr = (message.get("meta") or {}).get("correlation_id")
        if corr is not None:
            for i, t in enumerate(msgs):
                if isinstance(t, dict) and (t.get("meta") or {}).get("correlation_id") == corr:
                    return i
        return len(msgs) - 1

    # ── media (work-level, presigned S3 direct — CM 에 서명 위임. 바이트는 CM 안 거침) ──

    async def request_presigned_put(
        self,
        user_id: str,
        work_id: str,
        media_id: str,
        ext: str,
        mime: str,
        max_bytes: int,
        ttl: int,
    ) -> dict[str, Any]:
        url = f"{self.base}/sessions/{user_id}/{work_id}/media/presign-put"
        r = await self._client.post(
            url,
            json={
                "media_id": media_id,
                "ext": ext,
                "mime": mime,
                "max_bytes": max_bytes,
                "ttl": ttl,
            },
        )
        r.raise_for_status()
        return r.json()

    async def request_presigned_get(
        self, user_id: str, work_id: str, media_id: str, ttl: int
    ) -> dict[str, Any] | None:
        url = f"{self.base}/sessions/{user_id}/{work_id}/media/presign-get"
        r = await self._client.post(url, json={"media_id": media_id, "ttl": ttl})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def list_media(self, user_id: str, work_id: str) -> list[dict[str, Any]]:
        url = f"{self.base}/sessions/{user_id}/{work_id}/media"
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()["items"]

    async def delete_media(self, user_id: str, work_id: str, media_id: str) -> None:
        url = f"{self.base}/sessions/{user_id}/{work_id}/media/{media_id}"
        r = await self._client.delete(url)
        r.raise_for_status()

    # ── model GET (Nexus 고유: IOM. 공통 conversation/CMM/UR/drawing-manifest 는 base) ──

    async def get_iom(self, user_id: str, work_id: str, pointer: str = "") -> Any:
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/invention-object-model"
        return await self._model_get(url, pointer)

    async def set_roadmap_item(
        self, user_id: str, work_id: str, item_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        """UR 항목(id)을 CM 이 **락 안에서 find-by-id 후 fields 병합** — index race 없음.
        못 찾으면 None.

        구체화 단계에서 사용자가 로드맵 항목에 답하면 Nexus 가 그 항목의 answer+status 를
        즉시 기록(S3 쓰기는 CM). 로드맵 생성·점수는 AI(P02) 소유.
        """
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/user-roadmap/items/{item_id}"
        r = await self._client.patch(url, json=fields)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

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
