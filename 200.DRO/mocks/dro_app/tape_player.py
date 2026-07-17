"""tape player — pipeline_id 별 playlist 순차재생 (사용자 확정).

`{TAPE_DIR}/{pipeline_id}/{NN-슬러그}.json` 의 tape 들을 정렬순 playlist 로 보고,
i번째 spawn 이 i번째 tape 를 재생한다 (소진 시 마지막 반복 — authoring 불변: 마지막
tape 는 무해). cursor 키 = (user_id, work_id, pipeline_id) — endpoint 의 phase 들이
각자 fresh work 를 쓰므로 phase 간 완전 격리.

tape 포맷: {description, events: [{type, persona?, payload?, step?, delay_ms?}], expected?}
— seq/timestamp/user/work/chain_id 는 런타임 주입 (hub 가 seq/ts, player 가 chain_id).
`expected` 는 endpoint ws_tape 러너가 읽는 기대값 — mock 은 무시.

startup 에 TAPE_DIR 전수 load + 구조 검증 — **fail-loud** (잘못된 tape = 컨테이너
crash → make up healthcheck 가 게이트). type enum 은 강제하지 않음 (unknown-type
tape 가 mapper-skip 검증용으로 존재).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from . import config, hub

log = logging.getLogger(__name__)


def _validate_tape(path: Path, tape: Any) -> None:
    if not isinstance(tape, dict):
        raise RuntimeError(f"tape must be a JSON object: {path}")
    events = tape.get("events")
    if not isinstance(events, list):
        raise RuntimeError(f"tape.events must be a list: {path}")
    for i, ev in enumerate(events):
        if not isinstance(ev, dict) or not isinstance(ev.get("type"), str):
            raise RuntimeError(f"tape.events[{i}].type must be a string: {path}")
        if "payload" in ev and not isinstance(ev["payload"], dict):
            raise RuntimeError(f"tape.events[{i}].payload must be an object: {path}")


def load_playlists(tape_dir: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """{pipeline_id: [tape, ...]} — 디렉토리 = pipeline_id, 파일 정렬순 = 재생순."""
    root = Path(tape_dir or config.TAPE_DIR)
    if not root.is_dir():
        raise RuntimeError(f"TAPE_DIR not found: {root} — compose 의 dro-tapes mount 확인")
    playlists: dict[str, list[dict[str, Any]]] = {}
    for pipeline_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        tapes = []
        for f in sorted(pipeline_dir.glob("*.json")):
            tape = json.loads(f.read_text(encoding="utf-8"))  # parse 실패 = fail-loud
            _validate_tape(f, tape)
            tape["_name"] = f"{pipeline_dir.name}/{f.stem}"
            tapes.append(tape)
        if not tapes:
            raise RuntimeError(f"empty playlist dir: {pipeline_dir}")
        playlists[pipeline_dir.name] = tapes
    if not playlists:
        raise RuntimeError(f"no playlists under {root}")
    return playlists


# startup 시 1회 load — import 실패 = 컨테이너 crash (fail-loud 게이트).
PLAYLISTS: dict[str, list[dict[str, Any]]] = load_playlists()

_cursor: dict[tuple[str, str, str], int] = {}
_cursor_lock = asyncio.Lock()


async def _next_tape(user_id: str, work_id: str, pipeline_id: str) -> dict[str, Any]:
    playlist = PLAYLISTS[pipeline_id]
    key = (user_id, work_id, pipeline_id)
    async with _cursor_lock:
        idx = _cursor.get(key, 0)
        _cursor[key] = idx + 1
    return playlist[min(idx, len(playlist) - 1)]  # 소진 = 마지막 반복


async def replay(user_id: str, work_id: str, pipeline_id: str, chain_id: str) -> None:
    """spawn 1건의 tape 재생 — background task 로 호출."""
    tape = await _next_tape(user_id, work_id, pipeline_id)
    await hub.wait_subscriber(user_id, work_id)  # race 보험 — timeout 시 그냥 재생(drop)
    log.info("tape replay: %s (chain=%s)", tape["_name"], chain_id[:8])
    for ev in tape["events"]:
        delay_ms = ev.get("delay_ms") or 0
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000.0)
        payload = dict(ev.get("payload") or {})
        payload.setdefault("chain_id", chain_id)
        await hub.emit(
            user_id,
            work_id,
            ev["type"],
            payload,
            persona=ev.get("persona"),
            step=ev.get("step"),
        )
