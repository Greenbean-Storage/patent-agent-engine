"""미디어 업로드/다운로드 운영 설정 SoT loader.

`@deployment/media.config.yaml` 한 파일이 업로드 제한(크기·MIME·개수)과 presigned URL TTL 을
정의한다. Nexus(업로드 게이트·소유권 검증)·CM(presigned 서명) 이 런타임 read.
크기·MIME 은 presigned POST 정책(content-length-range·Content-Type)으로 S3 가 직접 강제.

환경변수:
  MEDIA_CONFIG_FILE — yaml 경로 (default: /etc/media.config.yaml, 컨테이너 안 mount)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_DEFAULT_PATH = "/etc/media.config.yaml"
_REQUIRED: tuple[str, ...] = ("max_file_bytes", "allowed_mime", "max_files_per_work", "presign")
_REQUIRED_PRESIGN: tuple[str, ...] = ("put_ttl", "get_ttl")


def _config_path() -> Path:
    return Path(os.getenv("MEDIA_CONFIG_FILE", _DEFAULT_PATH))


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        raise RuntimeError(
            f"media.config.yaml not found: {path} — "
            "컨테이너는 /etc/media.config.yaml 마운트, host 도구는 MEDIA_CONFIG_FILE env 설정 필요"
        )
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"media.config.yaml schema invalid (not a mapping): {path}")
    for key in _REQUIRED:
        if key not in data:
            raise RuntimeError(f"media.config.yaml missing required key {key!r}: {path}")
    presign = data["presign"]
    if not isinstance(presign, dict) or any(k not in presign for k in _REQUIRED_PRESIGN):
        raise RuntimeError(f"media.config.yaml presign must define put_ttl/get_ttl: {path}")
    if not isinstance(data["allowed_mime"], list) or not data["allowed_mime"]:
        raise RuntimeError(f"media.config.yaml allowed_mime must be a non-empty list: {path}")
    return data


def max_file_bytes() -> int:
    return int(_load()["max_file_bytes"])


def allowed_mime() -> frozenset[str]:
    return frozenset(_load()["allowed_mime"])


def max_files_per_work() -> int:
    return int(_load()["max_files_per_work"])


def put_ttl() -> int:
    return int(_load()["presign"]["put_ttl"])


def get_ttl() -> int:
    return int(_load()["presign"]["get_ttl"])
