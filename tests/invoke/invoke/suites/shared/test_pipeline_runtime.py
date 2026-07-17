"""venezia_pipeline_runtime (loader 단일) — 단위 sanity test.

composer / dispatch_resolver 테스트는 모듈 흡수와 함께 이동 (Actor 재설계 A5):
suites/actor/test_composer.py · suites/dro/test_dispatch_resolver.py.

실행:
    make invoke
또는:
    cd tests/invoke && uv run python -m invoke
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))


def test_parse_filename_p_format():
    from venezia_pipeline_runtime.loader import parse_pipeline_filename

    meta = parse_pipeline_filename("P03.R01.SEARCH_AND_REFLECT.pipeline.json")
    assert meta["persona"] == 3
    assert meta["role"] == 1
    assert meta["title"] == "SEARCH_AND_REFLECT"
    assert meta["pipeline_id"] == "P03.R01.SEARCH_AND_REFLECT"


def test_parse_filename_rejects_w_format():
    from venezia_pipeline_runtime.loader import parse_pipeline_filename, LoaderError

    try:
        parse_pipeline_filename("W03.R00.prior-art-search.pipeline.json")
    except LoaderError:
        return
    raise AssertionError("LoaderError 가 raise 되어야 함")


def test_load_pipeline_cascaded_basic():
    from venezia_pipeline_runtime.loader import load_pipeline_cascaded

    cascaded = load_pipeline_cascaded(
        "P03.R00.PRIOR_ART_SEARCH_ANALYZE",
        root=ROOT / "@pipelines",
    )
    assert cascaded["pipeline_id"] == "P03.R00.PRIOR_ART_SEARCH_ANALYZE"
    assert cascaded["persona"] == 3
    assert "심사관" in cascaded["persona_prompt"]
    # (1) global + (2) persona + (3) pipeline cascading
    assert "invention_object_model" in cascaded["common"]["inject_context"]
    assert "kipris_token_and" in cascaded["common"]["fragments"]
    # steps 가 cascading 된 effective_* 키를 가짐
    assert len(cascaded["steps"]) == 1
    step = cascaded["steps"][0]
    assert step["output_contract"] == "analyze-output"
    assert "invention_object_model" in step["effective_inject_context"]
    assert "kipris_token_and" in step["effective_fragments"]
    assert cascaded["dispatch_to"]["actions"] == [["P03.R01.SEARCH_AND_REFLECT"]]


def test_loader_legacy_instructions_list_rejected():
    """legacy `instructions: [...]` 형태가 loader 에서 fail-loud."""
    from venezia_pipeline_runtime.loader import _validate_step_instructions, LoaderError

    try:
        _validate_step_instructions(["legacy", "list"], "P01.R00.TEST", 0)
    except LoaderError:
        return
    raise AssertionError("LoaderError 가 raise 되어야 함 (legacy list)")


def test_loader_instructions_inline_ok():
    from venezia_pipeline_runtime.loader import _validate_step_instructions

    result = _validate_step_instructions({"inline": "short"}, "P01.R00.TEST", 0)
    assert result == {"inline": "short"}


def test_loader_instructions_reference_ok():
    from venezia_pipeline_runtime.loader import _validate_step_instructions

    result = _validate_step_instructions(
        {"reference": "@pipelines/01.buddy/P01.R00/assess.md"}, "P01.R00.TEST", 0
    )
    assert result == {"reference": "@pipelines/01.buddy/P01.R00/assess.md"}


def test_loader_instructions_reference_bad_prefix_rejected():
    from venezia_pipeline_runtime.loader import _validate_step_instructions, LoaderError

    try:
        _validate_step_instructions({"reference": "/abs/x.md"}, "P01.R00.TEST", 0)
    except LoaderError:
        return
    raise AssertionError("LoaderError 가 raise 되어야 함")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK {name}")
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {name}: {e}")
                raise
