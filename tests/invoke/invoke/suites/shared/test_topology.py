"""venezia_topology — topology.yaml lookup 헬퍼 (env-driven, lru_cache)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))

import venezia_topology as vt  # noqa: E402

TOPO = str(ROOT / "@deployment" / "topology.yaml")


def _clear() -> None:
    vt._load.cache_clear()


@pytest.fixture(autouse=True)
def _topo_env(monkeypatch):
    monkeypatch.setenv("TOPOLOGY_FILE", TOPO)
    monkeypatch.delenv("TOPOLOGY_NETWORK", raising=False)
    monkeypatch.delenv("TOPOLOGY_EXTERNAL_HOST", raising=False)
    _clear()
    yield
    _clear()


def test_service_port_publish():
    assert vt.service_port("dro") == 59200
    assert isinstance(vt.service_publish_port("dro"), int)
    assert vt.service_publish_port("actor") == 59300  # unified 단일 actor


def test_service_url_internal(monkeypatch):
    monkeypatch.setenv("TOPOLOGY_NETWORK", "internal")
    _clear()
    assert vt.service_url("cm") == "http://cm:59400"


def test_service_url_external(monkeypatch):
    monkeypatch.setenv("TOPOLOGY_NETWORK", "external")
    monkeypatch.setenv("TOPOLOGY_EXTERNAL_HOST", "localhost")
    _clear()
    assert vt.service_url("cm").startswith("http://localhost:")


def test_all_service_names():
    """unified 4 서비스 — persona_mapping/personas_to_urls 는 컷오버로 폐기."""
    names = vt.all_service_names()
    assert set(names) == {"dro", "cm", "actor", "nexus"}
    assert not hasattr(vt, "personas_to_urls")


def test_callbacks():
    assert "callback" in vt.account_callback_url()


def test_service_unknown():
    with pytest.raises(KeyError):
        vt.service_port("nonexistent-service")


def test_load_missing_file(monkeypatch):
    monkeypatch.setenv("TOPOLOGY_FILE", "/nonexistent/topology.yaml")
    _clear()
    with pytest.raises(RuntimeError):
        vt.all_service_names()


def test_load_invalid_schema(monkeypatch, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("foo: bar\n")
    monkeypatch.setenv("TOPOLOGY_FILE", str(bad))
    _clear()
    with pytest.raises(RuntimeError):
        vt.all_service_names()
