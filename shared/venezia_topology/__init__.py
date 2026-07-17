"""DRC service host/port SoT loader.

`@deployment/topology.yaml` 한 파일이 모든 컨테이너의 host/port 를 정의한다 (순수 주소록 —
persona 관련 정의는 engine.config 의 도메인, 구 persona_mapping 은 unified actor 컷오버로 폐기).
이 모듈은 그 yaml 을 read 해 URL/port lookup 헬퍼를 노출한다.

환경변수:
  TOPOLOGY_FILE          — yaml 경로 (default: /etc/topology.yaml, 컨테이너 안 mount)
  TOPOLOGY_NETWORK       — "internal" (컨테이너 간 DNS) | "external" (host 에서 localhost)
                           default: internal
  TOPOLOGY_EXTERNAL_HOST — external 모드일 때 host 이름 (default: localhost)

호출 예:
  service_url("cm")             → "http://cm:59400" (internal)
                                  / "http://localhost:59400" (external)
  service_port("dro")           → 59200
  service_publish_port("actor") → 59300
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_DEFAULT_PATH = "/etc/topology.yaml"


def _topology_path() -> Path:
    return Path(os.getenv("TOPOLOGY_FILE", _DEFAULT_PATH))


def _network() -> str:
    return os.getenv("TOPOLOGY_NETWORK", "internal").lower()


def _external_host() -> str:
    return os.getenv("TOPOLOGY_EXTERNAL_HOST", "localhost")


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    path = _topology_path()
    if not path.exists():
        raise RuntimeError(
            f"topology.yaml not found: {path} — "
            "컨테이너는 /etc/topology.yaml 마운트, host 도구는 TOPOLOGY_FILE env 설정 필요"
        )
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "services" not in data:
        raise RuntimeError(f"topology.yaml schema invalid: {path}")
    return data


def _service(name: str) -> dict[str, Any]:
    services = _load()["services"]
    if name not in services:
        raise KeyError(f"unknown service in topology.yaml: {name!r}")
    return services[name]


def all_service_names() -> list[str]:
    return list(_load()["services"].keys())


def service_port(name: str) -> int:
    return int(_service(name)["port"])


def service_publish_port(name: str) -> int:
    return int(_service(name)["host_publish_port"])


def service_url(name: str, *, scheme: str = "http") -> str:
    """Network 모드에 따라 internal DNS / external localhost URL 조립."""
    svc = _service(name)
    if _network() == "external":
        host = _external_host()
        port = int(svc["host_publish_port"])
    else:
        host = svc["host"]
        port = int(svc["port"])
    return f"{scheme}://{host}:{port}"


def account_callback_url() -> str:
    """100.Nexus 의 OAuth redirect URL. DRO 가 아닌 Account 가 OAuth 발급 책임."""
    path = _load().get("account_callback_path", "/auth/callback")
    return f"{service_url('nexus')}{path}"
