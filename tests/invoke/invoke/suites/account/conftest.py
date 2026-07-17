"""100.Nexus invoke suite 공유 fixture.

- sys.path 에 100.Nexus 추가 (src.* import).
- topology_env(autouse): CM_URL / account_callback_url / provider_redirect_uri 등
  venezia_topology 파생 경로가 @deployment/topology.yaml 로 resolve 되도록 (host 에서 필요).

async 테스트는 기존 suite 패턴대로 `asyncio.run(...)` 직접 호출 (pytest-asyncio mark 미사용).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
if str(ROOT / "100.Nexus") not in sys.path:
    sys.path.insert(0, str(ROOT / "100.Nexus"))


@pytest.fixture(autouse=True)
def topology_env(monkeypatch):
    """account/cm 서비스 URL 파생이 @deployment/topology.yaml 을 읽도록 + lru_cache 초기화."""
    import venezia_topology as vt

    monkeypatch.setenv("TOPOLOGY_FILE", str(ROOT / "@deployment" / "topology.yaml"))
    vt._load.cache_clear()
    yield
    vt._load.cache_clear()
