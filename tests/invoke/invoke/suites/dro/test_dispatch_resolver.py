"""src.dispatch_resolver (200.DRO) — 분기 전수 (기본 + 에러/엣지)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))

from src.dispatch_resolver import (  # noqa: E402
    DispatchError,
    resolve_dispatch,
)


def _r(**kw):
    base = dict(
        pipeline_id="P",
        dispatch_to={"actions": [["X"]]},
        last_step_output=None,
        ancestor_pipeline_ids=[],
    )
    base.update(kw)
    return resolve_dispatch(**base)


def test_actions_none():
    with pytest.raises(DispatchError):
        _r(dispatch_to={})


def test_actions_not_list():
    with pytest.raises(DispatchError):
        _r(dispatch_to={"actions": "x"})


def test_multi_without_output():
    with pytest.raises(DispatchError):
        _r(dispatch_to={"actions": [["A"], ["B"]]}, last_step_output=None)


def test_dispatch_choice_not_int():
    with pytest.raises(DispatchError):
        _r(dispatch_to={"actions": [["A"], ["B"]]}, last_step_output={"dispatch_choice": "x"})


def test_dispatch_choice_out_of_range():
    with pytest.raises(DispatchError):
        _r(dispatch_to={"actions": [["A"], ["B"]]}, last_step_output={"dispatch_choice": 5})


def test_choice_not_list():
    with pytest.raises(DispatchError):
        _r(dispatch_to={"actions": ["not-a-list"]})


def test_next_pid_not_str():
    with pytest.raises(DispatchError):
        _r(dispatch_to={"actions": [[123]]})


def test_multi_choice_selects_index():
    out = _r(
        dispatch_to={"actions": [["A"], ["B", "C"]]},
        last_step_output={"dispatch_choice": 1},
    )
    assert out == ["B", "C"]


def test_self_recursion_guard_drops_self():
    out = resolve_dispatch(
        pipeline_id="P",
        dispatch_to={"actions": [["P"]]},
        last_step_output=None,
        ancestor_pipeline_ids=["P", "P", "P"],
    )
    assert out == []  # self count 3 + 1 > max 3 → dropped


def test_actions_empty_exit():
    assert _r(dispatch_to={"actions": []}) == []


def test_single_action_passthrough():
    # 단일 action 은 dispatch_choice 무관 그대로 통과
    assert _r(dispatch_to={"actions": [["A"]]}, last_step_output={"dispatch_choice": 0}) == ["A"]


def test_branch_choice_zero_selects_first():
    out = _r(
        dispatch_to={"actions": [["A"], ["B"]]},
        last_step_output={"dispatch_choice": 0},
    )
    assert out == ["A"]
