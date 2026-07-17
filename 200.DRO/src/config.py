from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings
from venezia_topology import service_url


def _dep():
    # lazy import — circular 회피 + invoke 가 venezia_deployment 미설치여도 import 가능.
    from venezia_deployment import runtime

    return runtime


class Settings(BaseSettings):
    # Pipeline definitions
    PIPELINES_DIR: str = "/pipelines"

    # Dispatch / retry
    DISPATCH_TIMEOUT_S: float = 1200.0  # 20m for long agentic loops (단일 dispatch HTTP timeout)
    # 포화(AllActorsBusy) 재시도 — 포화 ≠ 실패 (B-1): 횟수 상한 없이 시간예산 안에서 backoff 지속.
    BUSY_BACKOFF_S: float = 1.0  # 지수 backoff 계수
    BUSY_BACKOFF_MAX_S: float = 30.0  # 지수 backoff 상한
    DISPATCH_RETRY_BUDGET_S: float = 1200.0  # 포화 대기 총 예산 (queue lease ttl 도 이와 연동)

    # LLM 차원 모드 — Actor 가 실 사용. DRO 는 정보 노출용 (health 응답).
    #   FIXTURE / PRODUCTION. 소스 = 마운트된 profile(/etc/deployment.yaml) via venezia_deployment.
    #   default_factory 는 인자·env 없을 때만 fire → invoke 는 Settings(LLM_MODE=...) 직접.
    LLM_MODE: str = Field(default_factory=lambda: _dep().llm())

    model_config = {"env_file": ".env", "extra": "ignore"}

    # ── topology.yaml 에서 derive (SoT: @deployment/topology.yaml) ──────────
    @property
    def CM_URL(self) -> str:
        return service_url("cm")

    @property
    def ACTOR_URL(self) -> str:
        """unified 단일 actor 직결 (구 persona_mapping 후보 풀 폐기 — B-3)."""
        return service_url("actor")


settings = Settings()  # type: ignore[reportCallIssue]
