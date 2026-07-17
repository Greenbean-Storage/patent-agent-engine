"""100.Nexus 설정 — DRO 의 chain·LLM·pipeline 의존 제거된 mypage 영역 전용 설정.

JWT secret 과 Google OAuth credentials 은 DRO 와 **동일 AWS Secret** 에서 read —
shared/venezia_secrets 가 모듈 import 시 자동 fetch + env 주입.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings
from venezia_topology import service_url


def _dep():
    # lazy import — circular 회피 + invoke import 가능.
    from venezia_deployment import runtime

    return runtime


# 사용자 메시지 인입 시 spawn 할 root chain — (pipeline_id, persona). DRO 의 구 handle_message
# 에서 이관 (Q18=B — 무슨 chain 띄울지는 Nexus 결정). DRO 는 받은 pipeline 실행만.
P01_ENTRY = ("P01.R00.CHAT_CONVERSATION", 1)  # Buddy 응대 (항상)
P02_ENTRY = ("P02.R00.CONCEPT_MATURITY", 2)  # Director 구체화 (ENGINE_MODE=FULL 일 때)

# AUTH_MODE=OPEN 일 때 JWT_SECRET_KEY 가 AWS Secret 으로부터 주입 못 받았을 경우 fallback.
# DRO 와 동일 값이어야 token 검증 일관성 유지. SECURE 모드는 secret 필수.
_DEV_JWT_FALLBACK = "dev-only-jwt-secret-NOT-FOR-PRODUCTION-USE"  # nosec B105


class Settings(BaseSettings):
    # Federated OAuth2 — provider credential (AWS Secret). _KEY_MAP 으로 env 주입.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""
    KAKAO_CLIENT_ID: str = ""
    KAKAO_CLIENT_SECRET: str = ""

    # JWT — 우리 세션 토큰. user_id(우리 발급) 를 claim 으로 실음 (provider sub 아님).
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15  # 짧은 access (쿠키). 만료 시 /refresh 로 silent 갱신.
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 14  # refresh (회전·family) — 14 days

    # httpOnly 쿠키 전달 (C1). access=Lax·/api/v1, refresh=Strict·/api/v1/user/auth.
    # COOKIE_SECURE: 외부 https 종단에선 True. 내부 http 검증 스택은 쿠키를 명시 주입하므로
    # prod-safe default True 유지 (필요 시 env COOKIE_SECURE 로 override).
    COOKIE_SECURE: bool = True
    ACCESS_COOKIE_NAME: str = "nx_access"
    REFRESH_COOKIE_NAME: str = "nx_refresh"
    PKCE_COOKIE_NAME: str = "nx_pkce"
    # OAuth 콜백이 access+refresh 쿠키를 심은 뒤 브라우저를 보낼 SPA 라우트 (302 도착지).
    SPA_COMPLETE_ROUTE: str = "/auth/complete"
    # CSRF 방어 = SameSite (access=Lax → cross-site mutation 에 쿠키 미전송, refresh=Strict).
    # 모든 mutation 이 non-GET 이라 Lax 가 차단 → 별도 CSRF 토큰/Origin 체크 불요.

    # client WS 최대 수명 cap (분). connect 후 이 시간(또는 SECURE 토큰 만료 중 이른 쪽)에
    # 도달하면 소켓 close — 재연결(재인증) 유도. 유실은 best-effort, 재연결 since_seq 로 복구.
    WS_MAX_LIFETIME_MINUTES: int = 60 * 12  # 12h

    # AUTH_MODE (DEV_MODE 폐기) — OPEN: 인증 불요·고정 user_id / SECURE: federated 강제.
    # 소스 = 마운트된 profile(/etc/deployment.yaml) via venezia_deployment (env 아님).
    # default_factory 는 인자·env 미지정 시만 fire → invoke 는 Settings(AUTH_MODE=...) 직접.
    AUTH_MODE: str = Field(default_factory=lambda: _dep().auth())

    # Pipeline 차원 모드 — 사용자 메시지 인입 시 어떤 root chain 을 spawn 할지 (DRO 에서 이관).
    #   FULL      — P01 (Buddy) + P02 (Director) 동시 spawn (default)
    #   SMALLTALK — P01 만 spawn (P02 director OFF, 응대만 빠르게)
    ENGINE_MODE: str = Field(default_factory=lambda: _dep().engine())

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _normalize_auth_mode(self) -> Settings:
        object.__setattr__(self, "AUTH_MODE", (self.AUTH_MODE or "SECURE").upper())
        if self.AUTH_MODE not in ("OPEN", "SECURE"):
            raise ValueError(f"AUTH_MODE must be OPEN|SECURE, got {self.AUTH_MODE!r}")
        # OPEN 모드에서 JWT secret 미주입 시 fallback (로컬 dev 일관성).
        if self.AUTH_MODE == "OPEN" and not self.JWT_SECRET_KEY:
            object.__setattr__(self, "JWT_SECRET_KEY", _DEV_JWT_FALLBACK)
        return self

    @property
    def is_open(self) -> bool:
        return self.AUTH_MODE == "OPEN"

    @property
    def CM_URL(self) -> str:
        return service_url("cm")

    @property
    def DRO_URL(self) -> str:
        """DRO 내부 control(POST /control/spawn) + event(GET /events/...) base. 같은 host:port."""
        return service_url("dro")


settings = Settings()  # type: ignore[reportCallIssue]
