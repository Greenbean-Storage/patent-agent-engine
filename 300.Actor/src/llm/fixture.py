"""FixtureSession — FIXTURE mode (회귀 테스트용 JSON replay).

`{fixture_dir}/{pipeline_id}/{step_id}.json` 의 dict 를 그대로 응답.
파일 미존재 시 echo fallback (chain 진행은 막지 않음).

컨텍스트 ② 정합: agent_state envelope 의 fixture 원형 = 평문 {role, content}.
prior_state(envelope) 수용 — vendor 일치(fixture) 시 items→history, 불일치 시
items_to_plain 강등. export_state() 가 envelope 반환 (출력은 fixture 고정이라
history 는 관측·강등용 기록일 뿐 replay 에 무영향).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .state import build_agent_state, items_to_plain

log = logging.getLogger(__name__)


@dataclass
class FixtureSession:
    persona: int
    sdk: str
    model: str
    pipeline_id: str
    step_id: str
    fixture_dir: str
    prior_state: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        st = self.prior_state
        if not st or not st.get("items"):
            return
        if st.get("vendor") == "fixture":
            self.history = list(st["items"])
        else:
            self.history = items_to_plain(st["vendor"], st["items"])

    def _fixture_path(self) -> Path:
        return Path(self.fixture_dir) / self.pipeline_id / f"{self.step_id}.json"

    def _load(self) -> dict[str, Any] | list[Any] | None:
        """Fixture JSON load. dict (대부분 step) 또는 list (top-level array root,
        예: update_roadmap step 6 output) 모두 허용."""
        p = self._fixture_path()
        try:
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict | list):
                log.warning("fixture not a dict or list: %s", p)
                return None
            return data
        except FileNotFoundError:
            log.warning("fixture missing: %s", p)
            return None
        except Exception as e:  # noqa: BLE001
            log.warning("fixture load error %s: %s", p, e)
            return None

    async def run(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        media_refs: list[str] | None = None,
        max_iterations: int | None = None,
        response_schema: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        function_tools: list[Any] | None = None,
    ) -> dict[str, Any]:
        await asyncio.sleep(0.0)
        self.history.append({"role": "user", "content": prompt})
        structured = self._load()
        if structured is None:
            text = (
                f"[FIXTURE-MISS persona={self.persona} "
                f"pipeline={self.pipeline_id} step={self.step_id}]"
            )
            log.warning("fixture miss → echo: %s", text)
            self.history.append({"role": "assistant", "content": text})
            return {"text": text, "structured": None}
        text = f"(fixture {self.pipeline_id}/{self.step_id})"
        self.history.append(
            {"role": "assistant", "content": json.dumps(structured, ensure_ascii=False)}
        )
        return {"text": text, "structured": structured}

    def export_state(self) -> dict[str, Any]:
        """다음 RT 용 agent_state envelope — items = 평문 history (fixture 원형)."""
        return build_agent_state("fixture", self.model, list(self.history))
