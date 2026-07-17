"""페르소나 → 외부 channel 라벨 매핑.

WS `progress.data.channel` 의 값 (구 message.thinking, #6). 클라이언트가 RT 진행을
lane 별로 구분해서 보여줄 수 있게 한다.

이 dict 한 줄 수정으로 라벨 전체 변경 가능 — 다른 코드 경로(event_mapper,
schema, endpoint test)는 모두 이 상수만 import.

메타 5 (AI 비식별): persona/LLM/buddy/director/AI 류 단어 금지. 행위 중심 명사만.
"""

from __future__ import annotations

PERSONA_TO_CHANNEL: dict[int, str] = {
    1: "support",  # P1 — 응대
    2: "analysis",  # P2 — 구체화 진단
    3: "research",  # P3 — 선행기술 조사
    4: "thinking",  # P4 — 추론
    5: "drafting",  # P5 — 작성
    6: "review",  # P6 — 검토
}

CHANNEL_LABELS: frozenset[str] = frozenset(PERSONA_TO_CHANNEL.values())


def channel_for_persona(persona: int) -> str:
    """persona int (1~6) → channel 라벨. 범위 밖이면 KeyError."""
    return PERSONA_TO_CHANNEL[persona]
