"""Stage 10 — WS contract 3원 cross-consistency.

WS 표면은 코드에서 생성되지 않고 수기 spec 2벌 + 라벨 SoT 1곳 → 어긋남이 자동으로 안 잡혔음.
세 출처를 강제 일치시킨다:

1. event 이름 집합 — `@contracts/00.dro/websocket-events.json` 의 `type.enum`
   == 그 파일 `_payload_schemas` 키(─ _comment)
   == `asyncapi.yaml` 의 event payload `const` 값들.
2. channel 라벨 — `asyncapi.yaml` `components.schemas.Channel.enum`
   == `channels.py:PERSONA_TO_CHANNEL` 값(6). (ws-events 의 channel 은 open string by design → 미강제.)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import yaml

from .._common import CONTRACTS_DIR, ROOT, ValidationReport

STAGE_NAME = "ws consistency"
_ASYNCAPI = ROOT / ".docs" / "Architectures" / "external_api" / "asyncapi.yaml"
_WS_EVENTS = CONTRACTS_DIR / "00.dro" / "websocket-events.json"
_EVENT_PREFIXES = ("message.", "work.", "model.", "output.", "system.")
# inbound action(client→server) — asyncapi 엔 있으나 ws-events.json(outbound 전용)엔 없음.
# message.send 도 message. 접두사라 const 수집됨 → 여기서 빼야 outbound 만 남음 (A-4: resend 폐기, 1종).
_INBOUND_ACTIONS = {"message.send"}


def _walk(obj: Any) -> Iterator[Any]:
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _event_consts(obj: Any) -> set[str]:
    out: set[str] = set()
    for node in _walk(obj):
        if isinstance(node, dict) and isinstance(node.get("const"), str):
            if node["const"].startswith(_EVENT_PREFIXES):
                out.add(node["const"])
    return out


def validate_ws_consistency(rep: ValidationReport) -> bool:
    ok = True
    try:
        from venezia_contracts.models.dro_api.channels import PERSONA_TO_CHANNEL
    except Exception as e:
        rep.err(f"[ws] channels.py import 실패: {e}")
        return False
    channels_sot = set(PERSONA_TO_CHANNEL.values())

    if not _WS_EVENTS.exists():
        rep.err(f"[ws] websocket-events.json 없음: {_WS_EVENTS}")
        return False
    if not _ASYNCAPI.exists():
        rep.err(f"[ws] asyncapi.yaml 없음: {_ASYNCAPI}")
        return False
    wsev = json.loads(_WS_EVENTS.read_text(encoding="utf-8"))
    ay = yaml.safe_load(_ASYNCAPI.read_text(encoding="utf-8"))

    # 1) event 이름 3원 일치
    e_ws = set((wsev.get("properties", {}).get("type", {}) or {}).get("enum") or [])
    payload_keys = set((wsev.get("_payload_schemas") or {}).keys()) - {"_comment"}
    if e_ws != payload_keys:
        rep.err(
            f"[ws] websocket-events.json type.enum ↔ _payload_schemas 키 불일치: "
            f"{sorted(e_ws ^ payload_keys)}"
        )
        ok = False
    # asyncapi 의 outbound event const (inbound action 제외).
    e_ay = _event_consts(ay) - _INBOUND_ACTIONS
    if e_ws != e_ay:
        rep.err(
            f"[ws] ws-events enum ↔ asyncapi outbound event const 불일치: "
            f"ws-only={sorted(e_ws - e_ay)}, asyncapi-only={sorted(e_ay - e_ws)}"
        )
        ok = False

    # 2) channel 라벨 — asyncapi Channel.enum == PERSONA_TO_CHANNEL
    ch_schema = (ay.get("components", {}).get("schemas", {}) or {}).get("Channel") or {}
    ch_enum = set(ch_schema.get("enum") or [])
    if not ch_enum:
        rep.err("[ws] asyncapi components.schemas.Channel.enum 없음")
        ok = False
    elif ch_enum != channels_sot:
        rep.err(
            f"[ws] asyncapi Channel.enum {sorted(ch_enum)} ↔ "
            f"PERSONA_TO_CHANNEL {sorted(channels_sot)} 불일치"
        )
        ok = False

    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok
