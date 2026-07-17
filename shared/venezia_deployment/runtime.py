"""deployment profile 런타임 read — `venezia_topology` 미러.

`@deployment/profile.stack.yaml` 이 마운트된 `/etc/deployment.yaml` 을 read 해 knob 값을
앱 모드 문자열로 노출한다. via:config knob(llm/kipris/auth/engine)을 각 unit config 가 소비.

환경변수:
  DEPLOYMENT_FILE — profile yaml 경로 (default: /etc/deployment.yaml, 컨테이너 마운트)
                    host 도구/테스트는 이 env 로 경로 지정.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_DEFAULT_PATH = "/etc/deployment.yaml"

# knob value → 앱 모드 문자열 (knob 어휘는 lowercase, 앱 모드는 기존 UPPER 호환)
_LLM_MODE = {"real": "PRODUCTION", "fake": "FIXTURE"}


def _deployment_path() -> Path:
    return Path(os.getenv("DEPLOYMENT_FILE", _DEFAULT_PATH))


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    path = _deployment_path()
    if not path.exists():
        raise RuntimeError(
            f"deployment profile not found: {path} — "
            "컨테이너는 /etc/deployment.yaml 마운트, host 도구는 DEPLOYMENT_FILE env 설정 필요"
        )
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "version" not in data:
        raise RuntimeError(f"deployment profile schema invalid: {path}")
    return data


def value(knob: str) -> str:
    """raw knob 값(예: real|fake|open|secure). profile 에 없으면 KeyError."""
    data = _load()
    if knob not in data:
        raise KeyError(f"knob not in profile: {knob!r}")
    return str(data[knob])


# ── 앱 모드 getter (config 가 소비) ──
#
# 파일 부재(컨테이너 밖 — invoke import / host) 시 fallback = knobs.yaml default 미러.
# 컨테이너는 profile 이 항상 마운트(make up guard + x-deployment-mount)되어 fallback 안 탐.
# config.py 의 모듈수준 `settings = Settings()` 가 invoke import 시 default_factory 를 fire 하므로
# (명시 인자 없는 import 경로), 파일 없을 때 crash 대신 default 로 떨어져야 import 가 성공한다.
_FALLBACK = {"auth": "SECURE", "engine": "FULL", "llm": "PRODUCTION", "kipris": "real"}


def auth() -> str:
    try:
        return value("auth").upper()  # open|secure → OPEN|SECURE
    except RuntimeError:
        return _FALLBACK["auth"]


def engine() -> str:
    try:
        return value("engine").upper()  # full|smalltalk → FULL|SMALLTALK
    except RuntimeError:
        return _FALLBACK["engine"]


def llm() -> str:
    try:
        return _LLM_MODE[value("llm")]  # real|fake → PRODUCTION|FIXTURE
    except RuntimeError:
        return _FALLBACK["llm"]


def kipris() -> str:
    try:
        return value("kipris")  # real|fake (raw lowercase — Actor KIPRIS handler 가 소비)
    except RuntimeError:
        return _FALLBACK["kipris"]
