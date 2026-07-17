"""probe 공통 헬퍼 — DRO/CM URL, auth(OPEN 무토큰 / SECURE mint), session 생성, IOM seed.

probe 의 sub-command(seed/list 등)들이 이 setup/auth primitive 를 사용. (pipeline 실행 '로직' 은
play 소유 — `play/_run.py`. play 는 probe 를 CM-하네스로 import.)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from venezia_topology import service_url

DRO_URL = os.environ.get("DRO_URL", service_url("dro"))
CM_URL = os.environ.get("CM_URL", service_url("cm"))
# 100.Nexus 컨테이너 — auth + account + work CRUD/metadata.
ACCOUNT_URL = os.environ.get("ACCOUNT_URL", service_url("nexus"))


def log(msg: str) -> None:
    """기본 로그. probe 호출자 출력."""
    print(f"[probe] {msg}", flush=True)


OPEN_USER_ID = "00000000-0000-0000-0000-00000000open"


async def dev_token(http: httpx.AsyncClient) -> tuple[str, str]:
    """auth 전략 (구 /auth/dev-token 폐기) — OPEN: 무토큰·고정 user_id / SECURE: 공유 secret JWT mint.

    반환 (token, user_id). OPEN 은 token="" (서버가 무시). 함수명·시그니처 불변(play 호환).
    """
    auth_mode = "open"
    try:
        auth_mode = (
            ((await http.get(f"{DRO_URL}/health", timeout=5)).json() or {})
            .get("auth_mode", "open")
            .lower()
        )
    except Exception:  # noqa: BLE001
        pass
    if auth_mode == "secure":
        import jwt  # noqa: PLC0415
        from datetime import UTC, datetime, timedelta  # noqa: PLC0415

        secret = os.environ.get("JWT_SECRET_KEY") or "dev-only-jwt-secret-NOT-FOR-PRODUCTION-USE"
        now = datetime.now(UTC)
        tok = jwt.encode(  # nosemgrep
            {"sub": OPEN_USER_ID, "typ": "access", "iat": now, "exp": now + timedelta(hours=1)},
            secret,
            algorithm="HS256",
        )
        return tok, OPEN_USER_ID
    return "", OPEN_USER_ID


async def create_session(http: httpx.AsyncClient, token: str) -> str:
    """POST /api/v1/user/works → work_id (컬렉션 생성)."""
    cookies = {"nx_access": token} if token else {}
    r = await http.post(f"{ACCOUNT_URL}/api/v1/user/works", cookies=cookies, timeout=30)
    r.raise_for_status()
    return r.json()["work_id"]


async def seed_iom(
    http: httpx.AsyncClient,
    user_id: str,
    work_id: str,
    seed_path: Path,
) -> None:
    """IOM JSON 파일을 CM 에 PUT.

    fixture / production mode 의 P2 Director 우회 — 검증 도구만 사용.
    파일 path 만 받음 (inline default X).
    """
    iom = json.loads(seed_path.read_text(encoding="utf-8"))
    r = await http.put(
        f"{CM_URL}/sessions/{user_id}/{work_id}/models/invention-object-model",
        json=iom,
        timeout=30,
    )
    if r.status_code not in (200, 201, 204):
        log(f"WARN seed IOM status={r.status_code} body={r.text[:200]}")


# 호환 alias — 기존 simulator 코드의 `_<name>` 명 import 그대로 동작
_log = log
_dev_token = dev_token
_create_session = create_session
_seed_iom = seed_iom
