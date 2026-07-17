"""knobs.yaml 스키마 모델 (Pydantic strict).

profile.stack.yaml(현재 값)은 평면 dict 라 loader 가 함수로 검증한다 — 여기엔 스키마만.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class Realize(BaseModel):
    """knob 의 fake 실현 방법 — via image(컨테이너 교체) | config(런타임 read)."""

    model_config = ConfigDict(extra="forbid")

    via: Literal["image", "config"]
    services: list[str] = []  # via:image — 교체할 compose service
    reads: list[str] = []  # via:config — 이 값을 읽는 unit


class KnobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["fidelity", "behavior"]
    values: list[str]
    default: str
    available: bool = True  # False = fake 미구현(NEXT-PLAN) → 선택 시 fail-loud
    realize: Realize

    @model_validator(mode="after")
    def _check_default(self) -> KnobSpec:
        if self.default not in self.values:
            raise ValueError(f"default {self.default!r} not in values {self.values}")
        return self


class KnobsSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knobs: dict[str, KnobSpec]
