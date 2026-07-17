"""phase_ws_tape — 포괄 tape suite (dro:fake 전용).

mock-dro 의 pipeline_id 별 playlist 를 호스트에서 같은 규칙(정렬순·소진=마지막 반복)으로
미러해, i번째 message.send 가 소비할 P01[i]+P02[i] tape 쌍의 `expected` 를 알고 검증한다.
기대값은 tape JSON 의 `expected` 섹션에서 read — event_mapper 로직 재구현 없음 (단일 소스).

인터페이스 (사용자 확정 — play 패턴 미러):
  make endpoint ws_tape                         # 전수 sweep (전 인덱스 순차 검증)
  make endpoint ws_tape TAPE=<pipeline>/<tape>  # 그 tape 만 (선행 인덱스는 무검증 fast-forward)

dro:real 스택 → skip-pass (phase_secure 의 OPEN-skip 패턴). engine!=full → fail-loud
(suite 는 message.send 1건 = P01+P02 두 spawn 전제).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import websockets

from ._ws_schema import validate_ws_frame

_TAPE_DIR = Path(__file__).resolve().parents[3] / "data" / "dro-tapes"
_P01 = "P01.R00.CHAT_CONVERSATION"
_P02 = "P02.R00.CONCEPT_MATURITY"

_QUIET_S = 1.0  # 이 시간 동안 새 이벤트 없으면 케이스 종료
_CASE_CAP_S = 15.0  # 케이스당 상한 (delay/볼륨 tape 여유)


def _load_playlist(pipeline_id: str) -> list[tuple[str, dict]]:
    d = _TAPE_DIR / pipeline_id
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        tape = json.loads(f.read_text(encoding="utf-8"))
        out.append((f"{pipeline_id}/{f.stem}", tape))
    return out


def _at(playlist: list[tuple[str, dict]], i: int) -> tuple[str, dict] | None:
    """mock 과 동일 소진 규칙 — 마지막 반복."""
    if not playlist:
        return None
    return playlist[min(i, len(playlist) - 1)]


def _subset(exp: object, act: object) -> bool:
    """payload 부분일치 — dict 는 재귀 subset (빈 dict 는 정확히 빈 것 요구), 그 외 동등 비교."""
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            return False
        if exp == {}:
            return act == {}
        return all(k in act and _subset(v, act[k]) for k, v in exp.items())
    return bool(exp == act)


def _expected_pair(
    p01: tuple[str, dict] | None, p02: tuple[str, dict] | None
) -> tuple[set[str], set[str], set[str], dict[str, int], list[dict], str]:
    """인덱스 i 의 P01+P02 tape 쌍 → (expected ∪, forbidden ∩, channels ∪, counts Σ, contains ++, 라벨).

    forbidden 은 교집합 — 어느 한쪽 tape 가 정당하게 내는 이벤트는 금지일 수 없음.
    counts 는 합 — 같은 window 에 두 tape 의 이벤트가 함께 도착 (engine=full).
    """
    pair = [t for t in (p01, p02) if t is not None]
    expected: set[str] = set()
    channels: set[str] = set()
    counts: dict[str, int] = {}
    contains: list[dict] = []
    forb_sets = []
    for _name, tape in pair:
        exp = tape.get("expected") or {}
        expected |= set(exp.get("client_events") or [])
        channels |= set(exp.get("thinking_channels") or [])
        for ev_type, n in (exp.get("client_event_counts") or {}).items():
            counts[ev_type] = counts.get(ev_type, 0) + int(n)
        contains.extend(exp.get("payload_contains") or [])
        forb_sets.append(set(exp.get("forbidden") or []))
    forbidden = set.intersection(*forb_sets) if forb_sets else set()
    label = " + ".join(name for name, _ in pair)
    return expected, forbidden, channels, counts, contains, label


async def phase_ws_tape(http, dro_url, ctx) -> bool:
    from .all_phases import _fail, _new_work, _ok, _account_url  # noqa: PLC0415

    if ctx.get("dro_scope") != "fake":
        _ok("skip (dro:real — tape suite 는 dro:fake 전용. make deploy set dro fake)")
        return True
    try:
        from venezia_deployment.runtime import value  # noqa: PLC0415

        engine = str(value("engine"))
    except Exception:  # noqa: BLE001
        engine = "full"
    if engine != "full":
        _fail(f"ws_tape 는 engine=full 전제 (message.send = P01+P02 두 spawn) — 현재 {engine}")
        return False

    p01 = _load_playlist(_P01)
    p02 = _load_playlist(_P02)
    if not p01 or not p02:
        _fail(f"tape playlist 부재: {_TAPE_DIR} (P01 {len(p01)} / P02 {len(p02)})")
        return False
    n = max(len(p01), len(p02))

    # TAPE=<pipeline>/<tape명> — 그 tape 의 인덱스만 assert (선행은 fast-forward)
    target: str | None = ctx.get("tape")
    target_idx: int | None = None
    if target:
        for playlist in (p01, p02):
            for i, (name, _t) in enumerate(playlist):
                if name == target or name.endswith(f"/{target.split('/')[-1]}"):
                    if name == target:
                        target_idx = i
        if target_idx is None:
            _fail(f"TAPE 미발견: {target!r} (예: {_P01}/02-rt-error-message)")
            return False
        n = target_idx + 1
        _ok(f"단일 tape 모드 — index {target_idx} ({target}) 까지 fast-forward 후 검증")

    ok = True
    wid = await _new_work(http)  # fresh work — playlist cursor 0 보장
    ws_url = _account_url().replace("http", "ws") + f"/api/v1/works/{wid}/thread/stream"
    received: list[dict] = []
    stop = asyncio.Event()
    try:
        async with websockets.connect(
            ws_url,
            additional_headers=(
                [("Cookie", f"nx_access={ctx['token']}")] if ctx.get("token") else None
            ),
        ) as ws:

            async def recv():
                with contextlib.suppress(asyncio.TimeoutError, websockets.ConnectionClosed):
                    while not stop.is_set():
                        received.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0)))

            t = asyncio.create_task(recv())
            await asyncio.sleep(0.2)

            n_pass = 0
            for i in range(n):
                assert_this = target_idx is None or i == target_idx
                expected, forbidden, channels, counts, contains, label = _expected_pair(
                    _at(p01, i), _at(p02, i)
                )
                marker = len(received)
                await ws.send(
                    json.dumps(
                        {
                            "action": "message.send",
                            "data": {"content": f"tape case {i}", "correlation_id": f"tape-{i}"},
                        }
                    )
                )
                # quiet-drain — 새 이벤트가 _QUIET_S 동안 없으면 케이스 종료
                loop = asyncio.get_event_loop()
                t0 = loop.time()
                last_n = len(received)
                last_change = t0
                while loop.time() - t0 < _CASE_CAP_S:
                    await asyncio.sleep(0.2)
                    if len(received) != last_n:
                        last_n = len(received)
                        last_change = loop.time()
                    elif loop.time() - last_change >= _QUIET_S:
                        break
                window = received[marker:]
                types: set[str] = {ty for e in window if isinstance(ty := e.get("type"), str)}
                if not assert_this:
                    continue
                case_ok = True
                # C4 — 수신 프레임 전부 websocket-events.json 봉투+payload 스키마 검증.
                for fr in window:
                    serrs = validate_ws_frame(fr)
                    if serrs:
                        _fail(f"[{i}] {label}: 봉투 스키마 위반 {fr.get('type')!r}: {serrs}")
                        case_ok = False
                if "message.received" not in types:
                    _fail(f"[{i}] {label}: message.received 미수신")
                    case_ok = False
                missing = expected - types
                if missing:
                    _fail(
                        f"[{i}] {label}: expected 미수신 {sorted(missing)} (수신={sorted(types)})"
                    )
                    case_ok = False
                hit_forbidden = forbidden & types
                if hit_forbidden:
                    _fail(f"[{i}] {label}: forbidden 수신 {sorted(hit_forbidden)}")
                    case_ok = False
                got_channels = {
                    ch
                    for e in window
                    if e.get("type") == "work.progress"
                    for ch in [(e.get("data") or {}).get("channel")]
                    if isinstance(ch, str)
                }
                if channels and not channels <= got_channels:
                    _fail(f"[{i}] {label}: progress 채널 누락 {sorted(channels - got_channels)}")
                    case_ok = False
                # 건수 하한 — 매핑 drop/누락 검출 (set 존재만으로는 broken mapper 가 통과 가능).
                for ev_type, min_n in counts.items():
                    got_n = sum(1 for e in window if e.get("type") == ev_type)
                    if got_n < min_n:
                        _fail(f"[{i}] {label}: {ev_type} 건수 {got_n} < 기대 {min_n}")
                        case_ok = False
                # payload 내용 — event_mapper 가 tape payload 를 올바르게 매핑·forward 했는지
                # (text/structured/error.message/display_status fallback/score/count 등).
                for item in contains:
                    ity = item.get("type")
                    isub = item.get("data") or {}
                    if not any(
                        e.get("type") == ity and _subset(isub, e.get("data") or {}) for e in window
                    ):
                        _fail(
                            f"[{i}] {label}: payload 불일치 — {ity} 에 "
                            f"{json.dumps(isub, ensure_ascii=False)[:120]} 미발견"
                        )
                        case_ok = False
                if case_ok:
                    n_pass += 1
                    _ok(f"[{i}] {label} ({len(window)} events)")
                else:
                    ok = False

            stop.set()
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        asserted = 1 if target_idx is not None else n
        _ok(f"tape suite: {n_pass}/{asserted} 케이스 통과 (P01 {len(p01)} · P02 {len(p02)} tapes)")
    except Exception as e:  # noqa: BLE001
        _fail(f"ws_tape exception: {e!r}")
        ok = False
    return ok
