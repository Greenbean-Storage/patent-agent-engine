"""mock 설정 — env 단일점 (실 `src/config.py` 의 mock 대응부).

compose 가 target 무관하게 넣어주는 ACTOR_ID / FIXTURE_PATH 를 그대로 읽는다.
shared(venezia_*) 미포함 (mock 이미지 = minimal, 3f) — topology 는 mount 된 파일을 직접 파싱.

persona 수락 집합: real Actor 의 SoT 는 engine.config personas (unified — 전 페르소나 수락).
mock 은 engine.config 미보유라 default "1,2,3,4,5,6" 으로 미러 — MOCK 전용 env
ACTOR_PERSONAS 로 override 가능 (테스트 유연성, real 에는 이 env 없음 — divergence 명기).
"""

from __future__ import annotations

import os

ACTOR_ID = os.getenv("ACTOR_ID", "actor-unknown")
FIXTURE_PATH = os.getenv("FIXTURE_PATH", "/app/data/llm-fixtures")
KIPRIS_FIXTURE_DIR = os.getenv("KIPRIS_FIXTURE_DIR", "/app/data/kipris-fixtures")
BUSY_MARKER_DIR = os.getenv("BUSY_MARKER_DIR", "/app/busy_markers")  # 이미지에 bake (3b)
TOPOLOGY_FILE = os.getenv("TOPOLOGY_FILE", "/etc/topology.yaml")


def personas() -> list[int]:
    """수락 집합 — real 의 engine.config personas(1~6) 미러 (mock 전용 env 로 override 가능)."""
    raw = os.getenv("ACTOR_PERSONAS", "1,2,3,4,5,6")
    return [int(x.strip()) for x in raw.split(",") if x.strip()]
