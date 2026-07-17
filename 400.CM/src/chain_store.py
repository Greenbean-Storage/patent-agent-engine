"""Chain manifest, RT, trail, agent_state — runtime/{persona}/{chain_id}/* 관리. (P-A v3)

chain 자료가 페르소나별 sub-folder 아래. 모든 함수가 persona 인자 받음.
chain_queue 폐기 — manifest.runtime.yaml 은 chain 인덱스 (페르소나 무관 root).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import venezia_memory as vm

from . import config
from .lock import lock_for
from .store import _s3, apply_json_patch
from .store import read_by_key as read
from .store import write_by_key as write

_BUCKET = config.settings.S3_BUCKET
log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


_CONTRACT_LOADER = None  # type: ignore[assignment]


def _contract_loader():
    """Lazy ContractLoader 싱글톤. import 실패 시 None — validation skip."""
    global _CONTRACT_LOADER
    if _CONTRACT_LOADER is False:
        return None
    if _CONTRACT_LOADER is None:
        try:
            from venezia_contracts import ContractLoader

            _CONTRACT_LOADER = ContractLoader()
        except Exception as e:  # noqa: BLE001
            log.warning("ContractLoader unavailable, chain_manifest validation skipped: %s", e)
            _CONTRACT_LOADER = False
            return None
    return _CONTRACT_LOADER


# ── manifest.runtime.yaml (전체 세션 chain 인덱스, 페르소나 무관 root) ────────


def _runtime_manifest_key(user_id: str, work_id: str) -> str:
    return vm.runtime_manifest_key(user_id, work_id)


async def get_chains_manifest(user_id: str, work_id: str) -> dict[str, Any]:
    data = read(_runtime_manifest_key(user_id, work_id))
    if data is None:
        return {
            "session": {"user_id": user_id, "work_id": work_id},
            "chains": [],
            "last_updated": _now(),
        }
    return data


async def add_chain_to_manifest(
    user_id: str, work_id: str, chain_id: str, pipeline_id: str, persona: int
) -> None:
    key = _runtime_manifest_key(user_id, work_id)
    async with lock_for(key):
        m = await get_chains_manifest(user_id, work_id)
        if any(e.get("chain_id") == chain_id for e in m["chains"]):
            return  # 이미 인덱스됨 — 중복 entry 방지 (멱등)
        m["chains"].append(
            {
                "chain_id": chain_id,
                "pipeline_id": pipeline_id,
                "persona": persona,
                "status": "pending",
                "started_at": _now(),
                "completed_at": None,
            }
        )
        m["last_updated"] = _now()
        write(key, m)


async def update_chain_in_manifest(
    user_id: str, work_id: str, chain_id: str, **fields: Any
) -> None:
    key = _runtime_manifest_key(user_id, work_id)
    async with lock_for(key):
        m = await get_chains_manifest(user_id, work_id)
        for entry in m["chains"]:
            if entry["chain_id"] == chain_id:
                entry.update(fields)
        m["last_updated"] = _now()
        write(key, m)


def _runtime_manifest_suffix() -> str:
    """runtime manifest key 의 세션루트 이후 부분 (예: '/runtime/manifest.runtime.yaml').
    하드코딩 대신 key builder 에서 도출 — scaffolding 변경에 자동 추종."""
    su, sw = "\x01u", "\x01w"
    return vm.runtime_manifest_key(su, sw)[len(vm.session_root(su, sw)) :]


def list_active_chains() -> list[dict[str, Any]]:
    """전 세션의 미완(pending/active) chain 열거 — DRO 재시작 자동복구용 (A-3).

    sessions/ prefix 전수 스캔 → 각 세션 runtime manifest(chain 인덱스)의
    status in {pending, active} entry. DRO 재시작은 드물고 멈춘 chain 도 대개 소수라
    전역 1회 스캔 허용 (status 는 patch_chain 이 인덱스에 mirror 하므로 최신)."""
    suffix = _runtime_manifest_suffix()
    out: list[dict[str, Any]] = []
    paginator = _s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_BUCKET, Prefix="sessions/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(suffix):
                continue
            # key = sessions/{user_id}/{work_id}/runtime/manifest.runtime.yaml
            # (suffix·prefix 가 최소 5 parts 보장 — parts[1]/[2] 항상 존재)
            parts = key.split("/")
            user_id, work_id = parts[1], parts[2]
            manifest = read(key) or {}
            for entry in manifest.get("chains") or []:
                if entry.get("status") in ("pending", "active") and entry.get("chain_id"):
                    out.append(
                        {
                            "user_id": user_id,
                            "work_id": work_id,
                            "persona": entry.get("persona"),
                            "chain_id": entry.get("chain_id"),
                            "pipeline_id": entry.get("pipeline_id"),
                            "status": entry.get("status"),
                        }
                    )
    return out


# ── chain manifest (개별 chain — runtime/{persona}/{chain_id}/manifest.json) ─


def _chain_manifest_key(user_id: str, work_id: str, persona: int, chain_id: str) -> str:
    return vm.chain_manifest_key(user_id, work_id, persona, chain_id)


async def create_chain(
    user_id: str,
    work_id: str,
    persona: int,
    chain_id: str,
    pipeline_id: str,
    trigger: dict[str, Any],
) -> dict[str, Any]:
    key = _chain_manifest_key(user_id, work_id, persona, chain_id)
    async with lock_for(key):
        # 멱등 — 같은 chain_id 재생성(네트워크 retry 등)은 기존 manifest 그대로 반환:
        # status/timestamp 클로버 + 인덱스 재-append 방지 (단일 writer 가드, DRO admission 과 이중).
        existing = read(key)
        if existing is not None:
            return existing
        manifest = {
            "chain_id": chain_id,
            "user_id": user_id,
            "work_id": work_id,
            "pipeline_id": pipeline_id,
            "persona": persona,
            "trigger": trigger,
            "status": "pending",
            "rt_count": 0,
            "completed_rt_count": 0,
            "started_at": _now(),
            "activated_at": None,
            "completed_at": None,
            "error": None,
        }
        loader = _contract_loader()
        if loader is not None:
            result = loader.validate("chain_manifest", manifest)
            if not result:
                log.warning(
                    "chain_manifest schema invalid chain_id=%s errors=%s",
                    chain_id,
                    result.errors[:3],
                )
                try:
                    await append_trail(
                        user_id,
                        work_id,
                        persona,
                        chain_id,
                        {
                            "event": "schema_violation",
                            "contract": "chain_manifest",
                            "chain_id": chain_id,
                            "errors": result.errors[:5],
                        },
                    )
                except Exception:  # noqa: BLE001  # nosec B110
                    pass
        write(key, manifest)
        await add_chain_to_manifest(user_id, work_id, chain_id, pipeline_id, persona)
        return manifest


async def get_chain(
    user_id: str, work_id: str, persona: int, chain_id: str
) -> dict[str, Any] | None:
    return read(_chain_manifest_key(user_id, work_id, persona, chain_id))


async def patch_chain(
    user_id: str,
    work_id: str,
    persona: int,
    chain_id: str,
    ops: list[dict[str, Any]],
) -> dict[str, Any]:
    """P-E: RFC 6902 JSON Patch ops array 적용."""
    key = _chain_manifest_key(user_id, work_id, persona, chain_id)
    async with lock_for(key):
        cur = read(key) or {}
        merged = apply_json_patch(cur, ops)
        write(key, merged)
        # mirror — ops 중 path=/status 또는 /completed_at 의 value 만 runtime manifest 반영
        mirror_fields: dict[str, Any] = {}
        for op in ops:
            if op.get("op") not in ("add", "replace"):
                continue
            path = op.get("path", "")
            for field in ("status", "completed_at"):
                if path == f"/{field}":
                    mirror_fields[field] = op.get("value")
        if mirror_fields:
            await update_chain_in_manifest(user_id, work_id, chain_id, **mirror_fields)
        return merged


# ── trail.jsonl (event log, append-only) ──────────────────────────────────────


def _trail_key(user_id: str, work_id: str, persona: int, chain_id: str) -> str:
    return vm.trail_key(user_id, work_id, persona, chain_id)


async def read_trail(user_id: str, work_id: str, persona: int, chain_id: str) -> bytes:
    """trail.jsonl 전체 raw bytes 반환. 없으면 빈 bytes."""
    key = _trail_key(user_id, work_id, persona, chain_id)
    try:
        obj = _s3().get_object(Bucket=_BUCKET, Key=key)
        return obj["Body"].read()
    except Exception:
        return b""


async def append_trail(
    user_id: str,
    work_id: str,
    persona: int,
    chain_id: str,
    event: dict[str, Any],
) -> None:
    """jsonl 에 1줄 append. read-modify-write."""
    import json as _json

    key = _trail_key(user_id, work_id, persona, chain_id)
    async with lock_for(key):
        try:
            obj = _s3().get_object(Bucket=_BUCKET, Key=key)
            existing = obj["Body"].read().decode("utf-8")
        except Exception:
            existing = ""
        line = _json.dumps({"ts": _now(), **event}, ensure_ascii=False)
        body = (existing + line + "\n").encode("utf-8")
        _s3().put_object(Bucket=_BUCKET, Key=key, Body=body, ContentType="application/x-ndjson")


# ── RT (runtime/{persona}/{chain_id}/rts/{rt_id}.json) ────────────────────────


def _rt_key(user_id: str, work_id: str, persona: int, chain_id: str, rt_id: str) -> str:
    return vm.rt_key(user_id, work_id, persona, chain_id, rt_id)


async def create_rt(
    user_id: str,
    work_id: str,
    persona: int,
    chain_id: str,
    rt: dict[str, Any],
) -> dict[str, Any]:
    """RT 본체 영속화. rt 는 reasoning_task.schema 형식 가정."""
    rt = {**rt, "created_at": rt.get("created_at") or _now(), "updated_at": _now()}
    rt.setdefault("state", "pending")
    rt.setdefault("retry_count", 0)
    rt.setdefault("max_retries", 3)
    rt.setdefault("sse_events", [])
    write(_rt_key(user_id, work_id, persona, chain_id, rt["rt_id"]), rt)
    return rt


async def get_rt(
    user_id: str, work_id: str, persona: int, chain_id: str, rt_id: str
) -> dict[str, Any] | None:
    return read(_rt_key(user_id, work_id, persona, chain_id, rt_id))


async def patch_rt(
    user_id: str,
    work_id: str,
    persona: int,
    chain_id: str,
    rt_id: str,
    ops: list[dict[str, Any]],
) -> dict[str, Any]:
    """P-E: RFC 6902 JSON Patch ops array 적용.

    sse_events_append 의 특수 path (`/sse_events_append`) 가 있으면 sse_events array 에
    server-side append (= JSON Patch 의 `add /sse_events/-` 의미). 호출자가 ops 에
    `{op:"add", path:"/sse_events_append", value:[event1, event2]}` 형태로 보내면 변환.
    """
    key = _rt_key(user_id, work_id, persona, chain_id, rt_id)
    async with lock_for(key):
        cur = read(key) or {}
        # sse_events_append 특수 처리 — replace /sse_events_append 값 list 추출
        sse_to_append: list[Any] = []
        cleaned_ops: list[dict[str, Any]] = []
        for op in ops:
            if op.get("path") == "/sse_events_append" and op.get("op") in ("add", "replace"):
                val = op.get("value") or []
                if isinstance(val, list):
                    sse_to_append.extend(val)
                continue
            cleaned_ops.append(op)
        merged = apply_json_patch(cur, cleaned_ops) if cleaned_ops else cur
        if sse_to_append:
            merged.setdefault("sse_events", []).extend(sse_to_append)
        merged["updated_at"] = _now()
        write(key, merged)
        return merged


# ── agent_state (runtime/{persona}/{chain_id}/agent_state.json) ───────────────


def _agent_state_key(user_id: str, work_id: str, persona: int, chain_id: str) -> str:
    return vm.agent_state_key(user_id, work_id, persona, chain_id)


async def get_agent_state(
    user_id: str, work_id: str, persona: int, chain_id: str
) -> dict[str, Any]:
    """미존재 시 default = 빈 envelope 동형 (컨텍스트 ② — vendor 원형 items).

    envelope 내용은 Actor 소유 (CM 은 opaque) — default 의 키 셋만 envelope 과 동형.
    """
    data = read(_agent_state_key(user_id, work_id, persona, chain_id))
    if data is None:
        return {
            "persona": persona,
            "schema_version": 1,
            "vendor": None,
            "model": None,
            "items": [],
            "updated_at": _now(),
        }
    return data


async def put_agent_state(
    user_id: str,
    work_id: str,
    persona: int,
    chain_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """body(envelope) pass-through 저장 — persona/updated_at 만 CM 이 스탬프."""
    key = _agent_state_key(user_id, work_id, persona, chain_id)
    async with lock_for(key):
        merged = {**state, "persona": persona, "updated_at": _now()}
        write(key, merged)
        return merged
