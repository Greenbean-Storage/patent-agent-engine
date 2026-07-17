"""venezia_contracts.loader — ContractLoader load/validate/assert + _find_contracts_dir."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))

from venezia_contracts.loader import ContractError, ContractLoader  # noqa: E402


def _tmp_contracts(tmp_path: Path) -> Path:
    c = tmp_path / "@contracts"
    c.mkdir()
    (c / "thing.schema.json").write_text(
        json.dumps(
            {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
        ),
        encoding="utf-8",
    )
    (c / "doc.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    return c


def test_load_and_cache(tmp_path):
    ld = ContractLoader(_tmp_contracts(tmp_path))
    s = ld.load("thing")
    assert s["required"] == ["name"]
    assert ld.load("thing") is s  # cache hit
    assert ld.load("doc")["type"] == "object"  # .json fallback


def test_load_not_found(tmp_path):
    ld = ContractLoader(_tmp_contracts(tmp_path))
    with pytest.raises(ContractError):
        ld.load("nonexistent")


def test_validate_valid_invalid(tmp_path):
    ld = ContractLoader(_tmp_contracts(tmp_path))
    ok = ld.validate("thing", {"name": "x"})
    assert ok.valid and bool(ok) and not ok.errors
    bad = ld.validate("thing", {})  # missing required → errors
    assert not bad.valid and not bool(bad) and bad.errors
    nf = ld.validate("nope", {})  # load-fail name
    assert not nf.valid


def test_assert_valid(tmp_path):
    ld = ContractLoader(_tmp_contracts(tmp_path))
    ld.assert_valid("thing", {"name": "x"})  # no raise
    with pytest.raises(ContractError):
        ld.assert_valid("thing", {})


def test_root_property(tmp_path):
    c = _tmp_contracts(tmp_path)
    assert ContractLoader(c).root == c


def test_find_contracts_dir_env(tmp_path, monkeypatch):
    c = _tmp_contracts(tmp_path)
    monkeypatch.setenv("CONTRACTS_DIR", str(c))
    assert ContractLoader().root == c  # no arg → env


def test_find_contracts_dir_walk(monkeypatch):
    monkeypatch.delenv("CONTRACTS_DIR", raising=False)
    assert ContractLoader().root.name == "@contracts"  # file-walk → repo @contracts
