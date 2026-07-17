"""engine.config 로더 — persona 정의 + LLM/tool 운영 설정의 SoT read.

Actor 소스코드는 persona 를 모른다 (테이블/열거 0) — 본 로더는 파일의 *형태*만 알고
모든 persona 는 데이터다. 미등재 persona = fail-loud (수락 집합의 SoT).

소스 = 빌드타임 COPY 된 /app/engine.config.yaml (Dockerfile). host 도구/테스트는
ENGINE_CONFIG_FILE env 로 @deployment/engine.config.yaml 지정 (venezia_deployment 의
DEPLOYMENT_FILE 패턴 미러). 전체 스키마 검증 = validate stage 12
(@deployment/engine-config.schema.json) — 본 로더는 구조 최소검증만 (fail-loud).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = "/app/engine.config.yaml"

_REQUIRED_SECTIONS = ("personas", "vendors", "tools", "defaults")
_REQUIRED_LLM_KEYS = ("sdk", "model", "fallback_model")


def _config_path() -> Path:
    return Path(os.getenv("ENGINE_CONFIG_FILE", _DEFAULT_PATH))


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        raise RuntimeError(
            f"engine config not found: {path} — 컨테이너는 빌드타임 COPY(/app/engine.config.yaml), "
            "host 도구/테스트는 ENGINE_CONFIG_FILE env 로 @deployment/engine.config.yaml 지정"
        )
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"engine config 가 mapping 이 아님: {path}")
    missing = [s for s in _REQUIRED_SECTIONS if s not in data]
    if missing:
        raise RuntimeError(f"engine config 필수 섹션 누락 {missing}: {path}")
    if not isinstance(data["personas"], dict) or not data["personas"]:
        raise RuntimeError(f"engine config personas 가 비어 있음: {path}")
    return data


def persona(pid: int) -> dict[str, Any]:
    """persona 정의+운영 entry (name/role/channel/memory_dir/llm/max_concurrency)."""
    entry = _load()["personas"].get(str(pid))
    if entry is None:
        raise RuntimeError(
            f"persona {pid} 가 engine config 에 없음 — 수락 집합 = engine.config personas 키"
        )
    llm = entry.get("llm")
    if not isinstance(llm, dict) or any(k not in llm for k in _REQUIRED_LLM_KEYS):
        raise RuntimeError(f"persona {pid} 의 llm 설정 불완전 (sdk/model/fallback_model 필수)")
    return entry


def persona_ids() -> list[int]:
    """등재된 persona id 전체 (수락 집합)."""
    return sorted(int(k) for k in _load()["personas"])


def vendor_retry(sdk: str) -> dict[str, Any]:
    """vendor retry 설정 → with_backoff kwargs ({max_attempts, backoff_seconds})."""
    vendor = _load()["vendors"].get(sdk)
    if not isinstance(vendor, dict) or "retry" not in vendor:
        raise RuntimeError(f"vendor {sdk!r} 의 retry 설정이 engine config 에 없음")
    return dict(vendor["retry"])


def tools() -> dict[str, Any]:
    return _load()["tools"]


def defaults() -> dict[str, Any]:
    return _load()["defaults"]
