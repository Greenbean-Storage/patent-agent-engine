"""Actor → CM HTTP 클라이언트 (RT GET/PATCH, agent_state, dialogs). (P-A v3)

URL 갱신:
- runtime/{persona}/{chain_id}/... — chain 자료가 persona sub-folder 안
- runtime/{persona}/dialog/{name} — 페르소나 누적 dialog
- runtime/00.dro/conversation — DRO 자료 (미디어는 work 레벨 presigned S3 직접, Actor 미경유)
- chain_queue 메서드 없음 (chain_queue 폐기)
"""

from __future__ import annotations

from typing import Any

import venezia_memory as vm
from venezia_cm_client import CMClientBase, dict_to_add_ops

from .config import settings


class CMClient(CMClientBase):
    """Actor 고유 — RT/agent_state/trail/dialog/input/drawing-part/model-write/step_output/
    load_resource. 공통(httpx·_model_get·_get_or_none·model GET 4종)은 `CMClientBase` (D-4).
    """

    def __init__(self, base_url: str | None = None) -> None:
        from . import engine_config

        super().__init__(
            base_url or settings.CM_URL,
            timeout=float(engine_config.defaults()["cm_http_timeout_s"]),
        )

    # ── RT (runtime/{persona}/{cid}/rts/{rt_id}) ──

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
        """P-E: RFC 6902 ops array 로 전송. fields top-level key 마다 add op.

        `add` 는 존재하면 교체, 없으면 추가 — `replace` (path 존재 필수) 와 달리 optional 필드
        (output, error 등) 의 첫 set 에서도 안전.
        """
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/rts/{rt_id}"
        ops = dict_to_add_ops(fields)
        r = await self._client.patch(url, json=ops)
        r.raise_for_status()
        return r.json()

    # ── agent_state (runtime/{persona}/{cid}/agent_state) ──

    async def get_agent_state(
        self, user_id: str, work_id: str, persona: int, chain_id: str
    ) -> dict[str, Any]:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/agent_state"
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()

    async def put_agent_state(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        chain_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """state = vendor 원형 envelope (llm/state.py build_agent_state) — body 통째 PUT."""
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/agent_state"
        r = await self._client.put(url, json=state)
        r.raise_for_status()
        return r.json()

    # ── trail (runtime/{persona}/{cid}/trail) ──

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

    async def get_trail(
        self, user_id: str, work_id: str, persona: int, chain_id: str
    ) -> list[dict[str, Any]]:
        """chain trail (jsonl). 각 line 을 dict 로 파싱해 list 반환."""
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/{chain_id}/trail"
        r = await self._client.get(url)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        import json as _json

        out: list[dict[str, Any]] = []
        for line in (r.text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(_json.loads(line))
            except (ValueError, TypeError):
                pass
        return out

    # ── conversation (00.dro) ──

    async def append_conversation(
        self, user_id: str, work_id: str, message: dict[str, Any]
    ) -> None:
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/00.dro/conversation/append"
        r = await self._client.post(url, json=message)
        r.raise_for_status()

    # ── persona dialog (누적) ──

    async def get_persona_dialog(
        self, user_id: str, work_id: str, persona: int, name: str
    ) -> dict[str, Any] | None:
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/dialog/{name}"
        return await self._get_or_none(url)

    async def patch_persona_dialog(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        name: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """P-E: RFC 6902 ops array 로 전송.

        fields top-level key 마다 add op (replace 는 path 존재 필수).
        """
        pdir = vm.persona_dir(persona)
        url = f"{self.base}/sessions/{user_id}/{work_id}/runtime/{pdir}/dialog/{name}"
        ops = dict_to_add_ops(fields)
        r = await self._client.patch(url, json=ops)
        r.raise_for_status()
        return r.json()

    # ── Read-only loaders (공통 _get_or_none/_model_get 은 base) ──

    async def get_invention_object_model(
        self, user_id: str, work_id: str, pointer: str = ""
    ) -> Any:
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/invention-object-model"
        return await self._model_get(url, pointer)

    async def get_drawing_part(
        self, user_id: str, work_id: str, drawing_id: str, part: str
    ) -> dict[str, Any] | None:
        """part ∈ {numerals, dl, figure}."""
        if part not in ("numerals", "dl", "figure"):
            raise ValueError(f"unknown drawing part: {part}")
        url = f"{self.base}/sessions/{user_id}/{work_id}/drawings/{drawing_id}/{part}"
        return await self._get_or_none(url)

    async def put_drawing_part(
        self,
        user_id: str,
        work_id: str,
        drawing_id: str,
        part: str,
        body: dict[str, Any],
    ) -> None:
        """part ∈ {numerals, dl, figure}."""
        if part not in ("numerals", "dl", "figure"):
            raise ValueError(f"unknown drawing part: {part}")
        url = f"{self.base}/sessions/{user_id}/{work_id}/drawings/{drawing_id}/{part}"
        r = await self._client.put(url, json=body)
        r.raise_for_status()

    async def put_concept_discovery_stack(
        self, user_id: str, work_id: str, body: dict[str, Any]
    ) -> None:
        """구체화 단계 정보 stack PUT — staging.save tool 이 호출."""
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/concept-discovery-stack"
        r = await self._client.put(url, json=body)
        r.raise_for_status()

    async def get_concept_discovery_stack(
        self, user_id: str, work_id: str, pointer: str = ""
    ) -> Any:
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/concept-discovery-stack"
        return await self._model_get(url, pointer)

    async def put_concept_maturity_model(
        self, user_id: str, work_id: str, body: dict[str, Any]
    ) -> None:
        """CMM PUT — maturity.compute tool 이 호출."""
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/concept-maturity-model"
        r = await self._client.put(url, json=body)
        r.raise_for_status()

    async def put_user_roadmap(
        self, user_id: str, work_id: str, body: list[dict[str, Any]]
    ) -> None:
        """UR PUT — roadmap.persist tool 이 호출. body = top-level array."""
        url = f"{self.base}/sessions/{user_id}/{work_id}/models/user-roadmap"
        r = await self._client.put(url, json=body)
        r.raise_for_status()

    async def get_step_output(
        self,
        user_id: str,
        work_id: str,
        persona: int,
        chain_id: str,
        step_id: str,
    ) -> dict[str, Any] | None:
        """trail 에서 step_id → rt_id 매핑 후 그 RT 의 output.structured 반환."""
        trail = await self.get_trail(user_id, work_id, persona, chain_id)
        rt_id: str | None = None
        for e in trail:
            if e.get("event") in ("rt_enqueued", "rt_started") and e.get("step_id") == step_id:
                rt_id = e.get("rt_id")
        if not rt_id:
            return None
        rt = await self.get_rt(user_id, work_id, persona, chain_id, rt_id)
        output = rt.get("output") or {}
        return output.get("structured") or {"text": output.get("text", "")}

    async def get_outputs_list(self, user_id: str, work_id: str) -> dict[str, Any] | None:
        url = f"{self.base}/sessions/{user_id}/{work_id}/outputs"
        return await self._get_or_none(url)

    # backwards-compat alias
    get_documents_list = get_outputs_list

    async def load_resource(self, user_id: str, work_id: str, resource_key: str) -> Any:
        """`context_manager_reads.resource` 문법을 read 호출로 dispatch.

        - "invention_object_model"
        - "dialog.{persona}.{name}"  (예: dialog.02.director.analysis 또는 dialog.2.analysis)
        - "drawing_manifest"
        - "drawing.{drawing_id}.{part}"  (part ∈ numerals|dl|figure)
        - "conversation"
        """
        if resource_key == "invention_object_model":
            return await self.get_invention_object_model(user_id, work_id)
        if resource_key == "drawing_manifest":
            return await self.get_drawing_manifest(user_id, work_id)
        if resource_key == "conversation":
            return await self.get_conversation(user_id, work_id)
        if resource_key.startswith("dialog."):
            # dialog.{persona_int}.{name}  e.g. dialog.2.analysis
            parts = resource_key.split(".", 2)
            if len(parts) != 3:
                raise ValueError(
                    f"dialog resource must be dialog.{{persona}}.{{name}}: {resource_key}"
                )
            _, persona_str, name = parts
            return await self.get_persona_dialog(user_id, work_id, int(persona_str), name)
        if resource_key.startswith("drawing."):
            parts = resource_key.split(".", 2)
            if len(parts) != 3:
                raise ValueError(
                    f"drawing resource must be drawing.{{id}}.{{part}}: {resource_key}"
                )
            _, drawing_id, part = parts
            return await self.get_drawing_part(user_id, work_id, drawing_id, part)
        raise ValueError(f"unknown CM resource_key: {resource_key}")


_default: CMClient | None = None


def get_cm_client() -> CMClient:
    global _default
    if _default is None:
        _default = CMClient()
    return _default
