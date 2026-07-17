"""enact 시나리오 registry — A1 의 5 패밀리가 그대로 대상 단위 (B1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from enact._invariants import Check

ALL_SCENARIOS = ("dispatch", "context", "tool", "concurrency", "errors")


@dataclass
class ScenarioOutcome:
    name: str
    checks: list[Check] = field(default_factory=list)
    fatal: str = ""  # 시나리오 진행 불가 사유 (dispatch HTTP 실패 등)
    work_id: str = ""

    @property
    def passed(self) -> bool:
        # 빈 checks = PASS 아님 (all([])=True false-pass 방어 — 검증을 0건 한 시나리오는 실패).
        return bool(self.checks) and not self.fatal and all(c.ok for c in self.checks)
