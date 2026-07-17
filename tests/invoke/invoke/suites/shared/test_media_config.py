"""venezia_media_config — 미디어 업로드/다운로드 운영 설정 SoT loader (shared venv).

`@deployment/media.config.yaml` 한 파일이 크기·MIME·개수 제한 + presigned TTL 을 정의.
accessors 5종 + _load 의 전 에러분기(파일 부재·키 결손·presign 결손·allowed_mime 형식·non-dict).
@lru_cache 때문에 케이스마다 `_load.cache_clear()` 로 캐시 busting.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))

import venezia_media_config as mc  # noqa: E402

REAL_CONFIG = ROOT / "@deployment" / "media.config.yaml"


@pytest.fixture(autouse=True)
def _bust_cache():
    """매 케이스 전후 @lru_cache busting — env 가 케이스마다 다르므로."""
    mc._load.cache_clear()
    yield
    mc._load.cache_clear()


def _point_at(monkeypatch, path: Path):
    monkeypatch.setenv("MEDIA_CONFIG_FILE", str(path))
    mc._load.cache_clear()


# ── accessors (실 committed media.config.yaml) ──


def test_accessors_real_config(monkeypatch):
    """5 accessor 가 committed media.config.yaml 값을 반환."""
    _point_at(monkeypatch, REAL_CONFIG)
    assert mc.max_file_bytes() == 20971520
    am = mc.allowed_mime()
    assert isinstance(am, frozenset)
    assert "image/png" in am and "application/pdf" in am
    assert mc.max_files_per_work() == 50
    assert mc.put_ttl() == 600
    assert mc.get_ttl() == 300


def test_default_path_when_env_unset(monkeypatch):
    """env 미설정 시 default 경로(/etc/media.config.yaml) 사용."""
    monkeypatch.delenv("MEDIA_CONFIG_FILE", raising=False)
    mc._load.cache_clear()
    assert mc._config_path() == Path("/etc/media.config.yaml")


# ── _load 에러분기 ──


def test_missing_file_raises(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path / "nope.yaml")
    with pytest.raises(RuntimeError, match="not found"):
        mc._load()


def test_non_dict_yaml_raises(monkeypatch, tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    _point_at(monkeypatch, p)
    with pytest.raises(RuntimeError, match="not a mapping"):
        mc._load()


def _write(tmp_path, data) -> Path:
    p = tmp_path / "media.config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _valid_data() -> dict:
    return {
        "max_file_bytes": 1024,
        "allowed_mime": ["image/png"],
        "max_files_per_work": 5,
        "presign": {"put_ttl": 100, "get_ttl": 50},
    }


def test_missing_required_key_raises(monkeypatch, tmp_path):
    data = _valid_data()
    del data["max_files_per_work"]
    _point_at(monkeypatch, _write(tmp_path, data))
    with pytest.raises(RuntimeError, match="missing required key 'max_files_per_work'"):
        mc._load()


def test_presign_not_dict_raises(monkeypatch, tmp_path):
    data = _valid_data()
    data["presign"] = "nope"
    _point_at(monkeypatch, _write(tmp_path, data))
    with pytest.raises(RuntimeError, match="presign must define put_ttl/get_ttl"):
        mc._load()


def test_presign_missing_put_ttl_raises(monkeypatch, tmp_path):
    data = _valid_data()
    data["presign"] = {"get_ttl": 50}
    _point_at(monkeypatch, _write(tmp_path, data))
    with pytest.raises(RuntimeError, match="presign must define put_ttl/get_ttl"):
        mc._load()


def test_presign_missing_get_ttl_raises(monkeypatch, tmp_path):
    data = _valid_data()
    data["presign"] = {"put_ttl": 100}
    _point_at(monkeypatch, _write(tmp_path, data))
    with pytest.raises(RuntimeError, match="presign must define put_ttl/get_ttl"):
        mc._load()


def test_allowed_mime_not_list_raises(monkeypatch, tmp_path):
    data = _valid_data()
    data["allowed_mime"] = "image/png"
    _point_at(monkeypatch, _write(tmp_path, data))
    with pytest.raises(RuntimeError, match="allowed_mime must be a non-empty list"):
        mc._load()


def test_allowed_mime_empty_raises(monkeypatch, tmp_path):
    data = _valid_data()
    data["allowed_mime"] = []
    _point_at(monkeypatch, _write(tmp_path, data))
    with pytest.raises(RuntimeError, match="allowed_mime must be a non-empty list"):
        mc._load()


def test_accessors_on_temp_valid(monkeypatch, tmp_path):
    """temp valid yaml 로 accessor 정수 캐스팅 경로 확인."""
    _point_at(monkeypatch, _write(tmp_path, _valid_data()))
    assert mc.max_file_bytes() == 1024
    assert mc.allowed_mime() == frozenset({"image/png"})
    assert mc.max_files_per_work() == 5
    assert mc.put_ttl() == 100
    assert mc.get_ttl() == 50
