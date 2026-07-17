"""DRC Actor 의 LLM 호출 통합 entry.

`create_session(persona, ...)` 가 mode (FIXTURE / PRODUCTION) 분기 후
- FIXTURE → FixtureSession (JSON replay)
- PRODUCTION  → ActorSession (Inner) → vendor adapter (Outer) 호출

persona → sdk/model/effort/fallback 등 LLM 운영 설정의 SoT 는
engine.config (`src/engine_config.py` 로더) — 코드에 persona 테이블 없음.
허용 MODE = {FIXTURE, PRODUCTION}. 그 외 값은 fail-loud.
vendor client singleton (Gemini embedding 용) 은 client.py.
"""

from __future__ import annotations

from typing import Any

from .. import engine_config
from ..config import settings
from .fixture import FixtureSession

_ALLOWED_MODES = {"FIXTURE", "PRODUCTION"}


def create_session(
    persona: int,
    prior_state: dict[str, Any] | None = None,
    *,
    step_id: str | None = None,
    pipeline_id: str | None = None,
):
    """persona + mode → 세션 인스턴스. persona 설정은 engine.config 가 SoT.

    prior_state = agent_state envelope (parse_agent_state 결과 | None) — 컨텍스트 ②.
    """
    entry = engine_config.persona(persona)
    llm = entry["llm"]
    sdk, model = llm["sdk"], llm["model"]
    mode = (settings.LLM_MODE or "").upper()

    if mode not in _ALLOWED_MODES:
        raise RuntimeError(
            f"Invalid LLM_MODE={mode!r}. Allowed: {sorted(_ALLOWED_MODES)}. "
            "ECHO_LLM / FIXTURE 폐기됨 — FIXTURE 사용."
        )

    if mode == "FIXTURE":
        if not (step_id and pipeline_id):
            raise RuntimeError(
                "FIXTURE mode 는 step_id + pipeline_id 필수 — "
                "dispatcher 에서 RT.step_id / RT.pipeline_id 가 set 됐는지 확인."
            )
        return FixtureSession(
            persona=persona,
            sdk=sdk,
            model=model,
            pipeline_id=pipeline_id,
            step_id=step_id,
            fixture_dir=settings.FIXTURE_PATH,
            prior_state=prior_state,
        )

    # PRODUCTION — engine.config 의 운영 설정 전체를 ActorSession 에 주입
    from ..actor_session import ActorSession

    return ActorSession(
        persona=persona,
        sdk=sdk,
        model=model,
        prior_state=prior_state,
        fallback_model=llm["fallback_model"],
        effort=llm.get("effort"),
        llm_settings=dict(llm.get("llm_settings") or {}),
        retry_cfg=engine_config.vendor_retry(sdk),
        defaults_cfg=engine_config.defaults(),
    )


__all__ = [
    "create_session",
]
