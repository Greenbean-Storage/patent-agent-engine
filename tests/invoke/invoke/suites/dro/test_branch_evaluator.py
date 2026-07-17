"""200.DRO branch_evaluator — placeholder $.path 치환 (순수)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))

from src.branch_evaluator import _resolve, substitute_placeholders  # noqa: E402

CTX = {"a": {"b": "VAL"}, "list": [{"x": 1}, {"x": 2}], "n": 42}


def test_resolve_dict_path():
    assert _resolve("$.a.b", CTX) == "VAL"


def test_resolve_list_index():
    assert _resolve("$.list.0.x", CTX) == 1
    assert _resolve("$.list.5", CTX) is None  # out of range


def test_resolve_non_path_and_non_str():
    assert _resolve("plain", CTX) == "plain"
    assert _resolve(123, CTX) == 123


def test_resolve_missing_and_non_traversable():
    assert _resolve("$.a.missing", CTX) is None
    assert _resolve("$.n.deeper", CTX) is None  # int 은 dict/list 아님 → None


def test_substitute_scalar_dict_list_passthrough():
    assert substitute_placeholders("$.a.b", CTX) == "VAL"
    assert substitute_placeholders({"k": "$.a.b", "lit": "x"}, CTX) == {"k": "VAL", "lit": "x"}
    assert substitute_placeholders(["$.a.b", "lit"], CTX) == ["VAL", "lit"]
    assert substitute_placeholders(42, CTX) == 42
