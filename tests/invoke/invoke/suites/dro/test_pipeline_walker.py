"""200.DRO pipeline_walker — load_pipeline 전수 + resolver + fail-loud (test_smoke 이관)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "200.DRO"))
sys.path.insert(0, str(ROOT / "shared"))


def _all_pipelines() -> list[Path]:
    return sorted((ROOT / "@pipelines").rglob("*.pipeline.json"))


def _reload_src() -> None:
    os.environ["PIPELINES_DIR"] = str(ROOT / "@pipelines")
    for mod in [m for m in list(sys.modules) if m == "src" or m.startswith("src.")]:
        del sys.modules[mod]


def test_dro_pipeline_walker_load_all_p():
    _reload_src()
    from src.pipeline_walker import load_pipeline

    loaded = 0
    failed = []
    for f in _all_pipelines():
        pid = f.name.removesuffix(".pipeline.json")
        try:
            p = load_pipeline(pid)
            assert p.get("pipeline_id") == pid, f"mismatch: {pid}"
            loaded += 1
        except Exception as e:  # noqa: BLE001
            failed.append(f"{f.name}: {e}")
    assert not failed, "load failed:\n  " + "\n  ".join(failed)
    assert loaded >= 21, f"expected >=21, loaded={loaded}"


def test_pipeline_walker_resolve_pipeline_id():
    _reload_src()
    from src.pipeline_walker import (
        AmbiguousPipelineId,
        list_pipelines,
        resolve_pipeline_id,
    )

    assert (
        resolve_pipeline_id("P03.R00.PRIOR_ART_SEARCH_ANALYZE")
        == "P03.R00.PRIOR_ART_SEARCH_ANALYZE"
    )
    assert resolve_pipeline_id("P03.R00") == "P03.R00.PRIOR_ART_SEARCH_ANALYZE"
    try:
        resolve_pipeline_id("P03")
    except AmbiguousPipelineId as e:
        assert len(e.candidates) >= 2
    else:
        raise AssertionError("expected AmbiguousPipelineId for 'P03'")
    try:
        resolve_pipeline_id("P99.R99")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for 'P99.R99'")
    lst = list_pipelines()
    assert len(lst) >= 21
    assert all("pipeline_id" in p and "persona" in p for p in lst)


def test_pipeline_walker_rejects_legacy_keys():
    sys.path.insert(0, str(ROOT / "200.DRO"))
    for mod in [m for m in list(sys.modules) if m.startswith("src.pipeline_walker")]:
        del sys.modules[mod]
    from src.pipeline_walker import _assert_no_legacy_keys

    with __import__("pytest").raises(RuntimeError, match="pipeline_id"):
        _assert_no_legacy_keys({"pipeline_id": "X", "steps": []}, Path("/tmp/t"))
    with __import__("pytest").raises(RuntimeError, match="type"):
        _assert_no_legacy_keys(
            {"description": "x", "common": {}, "steps": [{"type": "llm_task"}]},
            Path("/tmp/t"),
        )


def test_pipeline_walker_rejects_cross_persona_tool():
    sys.path.insert(0, str(ROOT / "200.DRO"))
    for mod in [m for m in list(sys.modules) if m.startswith("src.pipeline_walker")]:
        del sys.modules[mod]
    from src.pipeline_walker import _assert_no_cross_persona_tools

    with __import__("pytest").raises(RuntimeError, match="kipris"):
        _assert_no_cross_persona_tools(
            {"steps": [{"effective_llm_tools": ["kipris.search_prior_art"]}]}, Path("/tmp/t")
        )
    # self-chain fetch_* 만 통과 (no raise)
    _assert_no_cross_persona_tools(
        {"steps": [{"effective_llm_tools": ["fetch_dialog", "fetch_step_output"]}]},
        Path("/tmp/t"),
    )


def _fresh_walker():
    """src.pipeline_walker 를 깨끗이 재import (모듈 캐시 + 내부 cache 리셋)."""
    sys.path.insert(0, str(ROOT / "200.DRO"))
    sys.path.insert(0, str(ROOT / "shared"))
    os.environ["PIPELINES_DIR"] = str(ROOT / "@pipelines")
    for mod in [m for m in list(sys.modules) if m == "src" or m.startswith("src.")]:
        del sys.modules[mod]
    import src.pipeline_walker as pw  # noqa: E402

    return pw


def test_pipeline_walker_legacy_keys_nested_list_bad_keys():
    """steps[idx][sidx] 가 dict + 구설계 step 키 → RuntimeError (nested list 분기)."""
    pw = _fresh_walker()
    with __import__("pytest").raises(RuntimeError, match=r"steps\[0\]\[1\]"):
        pw._assert_no_legacy_keys(
            {
                "description": "x",
                "steps": [[{"instructions": {"inline": "ok"}}, {"sub_pipeline": "X"}]],
            },
            Path("/tmp/t"),
        )


def test_pipeline_walker_legacy_keys_nested_list_legacy_instructions():
    """nested list 안 dict 의 instructions 가 list (구 형식) → RuntimeError (line 104)."""
    pw = _fresh_walker()
    with __import__("pytest").raises(RuntimeError, match="legacy instructions: list"):
        pw._assert_no_legacy_keys(
            {"description": "x", "steps": [[{"instructions": ["a", "b"]}]]},
            Path("/tmp/t"),
        )


def test_pipeline_walker_legacy_keys_nested_list_non_dict_subitem_skipped():
    """nested list 안 비-dict subitem 은 건너뜀 (no raise)."""
    pw = _fresh_walker()
    # nested list 안 string subitem — isinstance(sub, dict) False → skip
    pw._assert_no_legacy_keys(
        {"description": "x", "steps": [["not-a-dict", {"instructions": {"inline": "ok"}}]]},
        Path("/tmp/t"),
    )


def test_pipeline_walker_legacy_keys_top_level_non_dict_step_skipped():
    """steps[idx] 가 dict/list 둘 다 아니면 continue (line 107)."""
    pw = _fresh_walker()
    # string step → not list, not dict → line 107 continue, no raise
    pw._assert_no_legacy_keys(
        {"description": "x", "steps": ["bare-string-step"]},
        Path("/tmp/t"),
    )


def test_pipeline_walker_legacy_instructions_string_form():
    """instructions 가 string (구 형식) → RuntimeError."""
    pw = _fresh_walker()
    with __import__("pytest").raises(RuntimeError, match="legacy instructions: string"):
        pw._assert_no_legacy_instructions(
            {"instructions": "old style prompt"}, Path("/tmp/t"), "steps[0]"
        )


def test_pipeline_walker_legacy_instructions_object_ok():
    """instructions 객체 형태 / None → no raise."""
    pw = _fresh_walker()
    pw._assert_no_legacy_instructions(
        {"instructions": {"reference": "@pipelines/x.md"}}, Path("/tmp/t"), "steps[0]"
    )
    pw._assert_no_legacy_instructions({}, Path("/tmp/t"), "steps[0]")


def test_pipeline_walker_cross_persona_non_dict_step_skipped():
    """effective_llm_tools 검사에서 비-dict step 은 continue (line 120)."""
    pw = _fresh_walker()
    # 비-dict step → line 120 continue, no raise
    pw._assert_no_cross_persona_tools(
        {"steps": ["not-a-dict", {"effective_llm_tools": ["fetch_dialog"]}]},
        Path("/tmp/t"),
    )


def test_pipeline_walker_cross_persona_dict_tool_form():
    """llm_tools 항목이 dict {name:...} 형태일 때 name 추출 후 검증."""
    pw = _fresh_walker()
    with __import__("pytest").raises(RuntimeError, match="cross-persona"):
        pw._assert_no_cross_persona_tools(
            {"steps": [{"llm_tools": [{"name": "kipris.search"}]}]}, Path("/tmp/t")
        )
    # dict 형태 + allowlist 통과
    pw._assert_no_cross_persona_tools(
        {"steps": [{"llm_tools": [{"name": "fetch_outputs"}]}]}, Path("/tmp/t")
    )


def test_pipeline_walker_index_rejects_non_p_filename(tmp_path):
    """_index 가 P{NN} 규칙 위반 *.pipeline.json 발견 시 RuntimeError (line 137)."""
    pw = _fresh_walker()
    bad = tmp_path / "bogus.pipeline.json"
    bad.write_text("{}", encoding="utf-8")
    pw.settings.PIPELINES_DIR = str(tmp_path)
    with __import__("pytest").raises(RuntimeError, match="non-P"):
        pw._index()


def test_pipeline_walker_coerce_nested_list_parallel_group():
    """_coerce_to_orchestrator 가 nested list 를 병렬 group 으로 변환 (line 167)."""
    pw = _fresh_walker()
    out = pw._coerce_to_orchestrator(
        {
            "pipeline_id": "P01.R00.X",
            "persona": 1,
            "steps": [
                [{"instructions": {"inline": "a"}}, {"tool": "t"}, "skip-non-dict"],
                {"tool": "single"},
            ],
            "persona_prompt": "PROMPT",
        }
    )
    assert out["pipeline_id"] == "P01.R00.X"
    # 첫 step 은 list (병렬 group), 비-dict subitem 은 제외 → 2개
    assert isinstance(out["steps"][0], list)
    assert len(out["steps"][0]) == 2
    # instructions 있는 step 은 system_prompt 주입됨
    assert out["steps"][0][0]["system_prompt"] == "PROMPT"
    # tool step (instructions 없음) 은 system_prompt 미주입
    assert "system_prompt" not in out["steps"][0][1]
    # id 자동 부여 (str(idx))
    assert out["steps"][0][0]["id"] == "0"
    assert isinstance(out["steps"][1], dict)


def test_pipeline_walker_parallel_bundle_honors_explicit_ids():
    """정적 병렬 묶음 sub 는 명시 id 를 honor (C5/D-6 — 같은 부모 idx 공유라 충돌 방지 필수)."""
    pw = _fresh_walker()
    out = pw._coerce_to_orchestrator(
        {
            "pipeline_id": "P02.R00.X",
            "persona": 2,
            "steps": [
                {"tool": "t0", "id": "0"},
                [
                    {"instructions": {"inline": "a"}, "id": "2"},
                    {"instructions": {"inline": "b"}, "id": "3"},
                    {"instructions": {"inline": "c"}, "id": "4"},
                ],
            ],
            "persona_prompt": "P",
        }
    )
    assert out["steps"][0]["id"] == "0"  # 단일 step 명시 id 보존
    bundle = out["steps"][1]
    assert isinstance(bundle, list)
    # 명시 id honor — setdefault 가 부모 idx(=1) 로 덮어쓰지 않음 → 3개 유일 (충돌 없음)
    assert [s["id"] for s in bundle] == ["2", "3", "4"]


def test_pipeline_walker_load_pipeline_cache_hit():
    """load_pipeline 이 _pipeline_cache hit 시 즉시 반환 (line 188)."""
    pw = _fresh_walker()
    sentinel = {"pipeline_id": "P_CACHED", "steps": []}
    pw._pipeline_cache["P_CACHED"] = sentinel
    got = pw.load_pipeline("P_CACHED")
    assert got is sentinel


def test_pipeline_walker_load_pipeline_not_found():
    """index 에 없는 pipeline_id → FileNotFoundError (line 194)."""
    pw = _fresh_walker()
    with __import__("pytest").raises(FileNotFoundError, match="P77.R77.NOPE"):
        pw.load_pipeline("P77.R77.NOPE")


def test_pipeline_walker_list_pipelines_reindexes_when_cache_none():
    """_index_cache 가 None 이면 list_pipelines 가 재인덱싱 (line 238)."""
    pw = _fresh_walker()
    pw._index_cache = None
    lst = pw.list_pipelines()
    assert len(lst) >= 21
    assert all("pipeline_id" in p for p in lst)


def test_pipeline_walker_list_pipelines_load_error_branch():
    """load_pipeline 실패 pid 는 error 필드로 기록 (lines 243-245)."""
    pw = _fresh_walker()
    # 존재하지 않는 파일을 가리키는 index 항목 주입 → load_pipeline 이 예외 → error 분기
    pw._index_cache = {"P88.R88.BROKEN": Path("/nonexistent/P88.R88.BROKEN.pipeline.json")}
    lst = pw.list_pipelines()
    assert len(lst) == 1
    entry = lst[0]
    assert entry["pipeline_id"] == "P88.R88.BROKEN"
    assert entry["persona"] is None
    assert entry["description"] == ""
    assert "error" in entry and entry["error"]
