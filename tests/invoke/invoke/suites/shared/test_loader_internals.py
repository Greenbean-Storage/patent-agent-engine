"""venezia_pipeline_runtime.loader — 헬퍼 에러분기 + load_pipeline_cascaded step 분기."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))

from venezia_pipeline_runtime.loader import (  # noqa: E402
    LoaderError,
    _find_persona_dir,
    _merge_dict,
    _merge_list,
    _read_json,
    _validate_step_instructions,
    load_pipeline_cascaded,
)


def test_read_json_missing(tmp_path):
    with pytest.raises(LoaderError):
        _read_json(tmp_path / "nope.json")


def test_read_json_bad(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(LoaderError):
        _read_json(bad)


def test_find_persona_dir_missing(tmp_path):
    (tmp_path / "_shared").mkdir()
    with pytest.raises(LoaderError):
        _find_persona_dir(tmp_path, 3)


def test_merge_dict_not_dict():
    with pytest.raises(LoaderError):
        _merge_dict({}, "GLOBAL", {"inject_context": "notdict"}, "inject_context")


def test_merge_dict_conflict_recorded():
    into: dict = {"a": "v1", "__source__": {"a": "GLOBAL"}}
    conflicts = _merge_dict(into, "persona", {"k": {"a": "v2"}}, "k")
    assert conflicts and conflicts[0][0] == "a"


def test_merge_list_not_list():
    with pytest.raises(LoaderError):
        _merge_list([], {"llm_tools": "notlist"}, "llm_tools")


def test_merge_list_dedup():
    into = ["x"]
    _merge_list(into, {"llm_tools": ["x", "y"]}, "llm_tools")
    assert into == ["x", "y"]


def test_validate_step_instructions_branches():
    assert _validate_step_instructions(None, "P", 0) is None
    with pytest.raises(LoaderError):
        _validate_step_instructions(42, "P", 0)  # non-dict, non-list, non-str
    with pytest.raises(LoaderError):
        _validate_step_instructions({"bogus": "x"}, "P", 0)  # extra key
    with pytest.raises(LoaderError):
        _validate_step_instructions({"inline": "a", "reference": "b"}, "P", 0)  # 2 keys
    with pytest.raises(LoaderError):
        _validate_step_instructions({"inline": 123}, "P", 0)  # inner not str
    assert _validate_step_instructions({"inline": "ok"}, "P", 0) == {"inline": "ok"}


def _mk_pipelines(tmp_path: Path) -> Path:
    root = tmp_path / "@pipelines"
    (root / "_shared").mkdir(parents=True)
    (root / "_shared" / "GLOBAL.json").write_text(
        json.dumps({"llm_tools": ["g1"], "fragments": {"gf": "x"}}), encoding="utf-8"
    )
    pdir = root / "03.finder"
    pdir.mkdir(parents=True)
    (pdir / "P03.COMMON.json").write_text(
        json.dumps({"persona_prompt": "P3", "inject_context": {"a": "@knowledge/y"}}),
        encoding="utf-8",
    )
    return root


def test_load_cascaded_steps(tmp_path):
    root = _mk_pipelines(tmp_path)
    pipe = {
        "common": {"fragments": {"pf": "y"}},
        "steps": [
            [{"description": "parallel", "id": "p0"}],  # list step → 정적 병렬 묶음 (bare list)
            {
                "description": "s1",
                "instructions": {"inline": "do"},
                "llm_tools": ["g1", "s_new"],  # g1 dup skip, s_new append
            },
        ],
        "dispatch_to": {"actions": []},
    }
    (root / "03.finder" / "P03.R00.TEST.pipeline.json").write_text(
        json.dumps(pipe), encoding="utf-8"
    )
    out = load_pipeline_cascaded("P03.R00.TEST", root=root)
    assert out["persona"] == 3 and out["persona_prompt"] == "P3"
    # nested list = 정적 병렬 묶음 → bare list (구 {_parallel_group} dict-wrap 폐기, D-6 배관 통일).
    # sub 도 단일 step 과 동형 cascading + 명시 id 보존.
    assert isinstance(out["steps"][0], list)
    assert out["steps"][0][0]["description"] == "parallel"
    assert out["steps"][0][0]["id"] == "p0"
    assert "effective_fragments" in out["steps"][0][0]
    s1 = out["steps"][1]
    assert "s_new" in s1["effective_llm_tools"] and "g1" in s1["effective_llm_tools"]
    assert s1["effective_fragments"]["gf"] == "x" and s1["effective_fragments"]["pf"] == "y"


def test_load_cascaded_step_not_dict(tmp_path):
    root = _mk_pipelines(tmp_path)
    (root / "03.finder" / "P03.R01.BAD.pipeline.json").write_text(
        json.dumps({"steps": [42]}), encoding="utf-8"
    )
    with pytest.raises(LoaderError):
        load_pipeline_cascaded("P03.R01.BAD", root=root)
