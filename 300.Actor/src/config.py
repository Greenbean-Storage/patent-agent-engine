from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings
from venezia_topology import service_url


def _dep():
    # lazy import — circular 회피 + invoke import 가능.
    from venezia_deployment import runtime

    return runtime


class Settings(BaseSettings):
    ACTOR_ID: str = "actor-unknown"
    # persona 수락 집합은 env 아님 — engine.config personas 가 SoT (src/engine_config.persona_ids).
    # 구 ACTOR_PERSONAS env 는 unified 컷오버로 폐기.

    # LLM 호출 모드 — 허용 값 {FIXTURE, PRODUCTION}:
    #   FIXTURE     — FIXTURE_PATH 의 사전 정의 JSON 으로 replay (로컬 dev / 검증 default)
    #   PRODUCTION  — 실 SDK 호출 (Claude / Gemini / OpenAI). EC2 IAM role 환경 전제.
    #
    # 소스 = 마운트된 profile(/etc/deployment.yaml) via venezia_deployment (env 아님).
    # default_factory 는 인자·env 미지정 시만 fire → invoke 는 Settings(LLM_MODE=...) 직접 지정.
    # 다른 값은 300.Actor/src/llm/__init__.py:create_session 에서 fail-loud.
    LLM_MODE: str = Field(default_factory=lambda: _dep().llm())
    FIXTURE_PATH: str = "/app/data/llm-fixtures"

    # KIPRIS (P3 Finder tools/kipris)
    # KIPRIS_MODE — raw lowercase {real, fake} (kipris knob, via:config):
    #   real — 실 KIPRIS Plus API (KIPRIS_API_KEY 필요)
    #   fake — canned (KIPRIS_FIXTURE_DIR — mock-actor canned 과 단일 소스, 키 불요)
    # 소스 = 마운트된 profile via venezia_deployment (LLM_MODE 동일 패턴).
    # 다른 값은 tools/kipris handler 에서 fail-loud.
    KIPRIS_MODE: str = Field(default_factory=lambda: _dep().kipris())
    KIPRIS_FIXTURE_DIR: str = "/app/data/kipris-fixtures"
    KIPRIS_API_KEY: str = ""
    # KIPRIS 운영값 (base_url/timeout/결과수/cache) 은 engine.config tools.kipris 로 이동
    # (@deployment/engine.config.yaml — src/engine_config.py 로더가 SoT read)

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def CM_URL(self) -> str:
        return service_url("cm")


settings = Settings()  # type: ignore[reportCallIssue]
