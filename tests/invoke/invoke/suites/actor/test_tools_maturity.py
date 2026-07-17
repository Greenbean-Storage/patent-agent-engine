"""maturity.compute 전수 (invoke 단위) — 300.Actor/src/tools/maturity/__init__.py.

대상 handler: maturity.compute — 3 지표 7 sub-score 가중 합산 (deterministic) +
concept-maturity-model.json (CMM) PUT (mock cm). WS push 는 DRO 책임이라 이 모듈에 없음 —
tool 은 계산 + CM PUT + payload 반환만.

검증:
  - 가중치 invariant: WEIGHTS 합 = 1.0, 각 SUB_WEIGHTS dict 합 = 1.0 (코드 const 자체)
  - score = sum(sub × sub_weight), overall = sum(score × weight), round(.,2) 정확값
  - CMM PUT body 가 올바른 인자(user_id/work_id/payload)로 한번 불림 + aclose finally
  - _validate_score 의 [0,1] 범위 가드 (purpose/components/sequence/.../effect 각각)
  - user_id/work_id 가드 + 3 sub-dict 필수 가드
  - rationale 누락 시 빈 문자열 fallback
  - _client() 가 settings.CM_URL 로 CMClient 생성 (마지막 미커버 라인)

전략: 모듈의 `_client()` 를 monkeypatch 해 AsyncMock CMClient 반환 — HTTP/config 우회.
put_concept_maturity_model 호출 인자를 진짜 assert.

async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))
sys.path.insert(0, str(ROOT / "shared"))

from src.tools import get as tool_get  # noqa: E402
from src.tools import maturity as mat  # noqa: E402

_U = "user-uuid-12345678"
_INV = "inv-uuid-87654321"

# 완전 채워진 3 sub-score dict (모든 테스트 base).
_CLARITY = {"purpose": 0.8, "components": 0.6, "rationale": "clear"}
_COMPLETE = {"sequence": 0.5, "causality": 0.4, "embodiment": 0.9, "rationale": "complete"}
_POTENTIAL = {"differentiation": 0.7, "effect": 0.3, "rationale": "novel"}


@pytest.fixture
def mock_cm(monkeypatch):
    """`_client()` 가 AsyncMock CMClient 를 반환하도록 교체. test 가 mock 을 직접 검사."""
    fake = AsyncMock()
    monkeypatch.setattr(mat, "_client", lambda: fake)
    return fake


@pytest.fixture
def topology_env(monkeypatch):
    """settings.CM_URL 는 venezia_topology 가 topology.yaml 을 읽어 derive — host 에선
    TOPOLOGY_FILE env 필요. @deployment/topology.yaml 을 가리키고 lru_cache 초기화."""
    import venezia_topology as vt

    monkeypatch.setenv("TOPOLOGY_FILE", str(ROOT / "@deployment" / "topology.yaml"))
    vt._load.cache_clear()
    yield
    vt._load.cache_clear()


def _run_compute(mock_cm, **overrides):
    """3 sub-dict + ids 로 compute 실행 (overrides 로 개별 교체)."""
    kwargs = {
        "clarity": overrides.get("clarity", dict(_CLARITY)),
        "completeness": overrides.get("completeness", dict(_COMPLETE)),
        "potential": overrides.get("potential", dict(_POTENTIAL)),
        "user_id": overrides.get("user_id", _U),
        "work_id": overrides.get("work_id", _INV),
    }
    return asyncio.run(mat.compute(**kwargs))


# ── const invariants ────────────────────────────────────────────────────────────


def test_weights_sum_to_one():
    assert round(sum(mat.WEIGHTS.values()), 10) == 1.0


def test_sub_weights_each_sum_to_one():
    for indicator, subs in mat.SUB_WEIGHTS.items():
        assert round(sum(subs.values()), 10) == 1.0, indicator


def test_weights_and_sub_weights_keys_align():
    assert set(mat.WEIGHTS) == set(mat.SUB_WEIGHTS)


# ── registry ──────────────────────────────────────────────────────────────────


def test_handler_registered():
    assert tool_get("maturity.compute") is mat.compute


# ── _client() (config 경유, 마지막 미커버 라인) ─────────────────────────────────


def test_client_builds_cmclient(monkeypatch, topology_env):
    """_client() 가 settings.CM_URL 로 CMClient 를 만든다."""
    from src.config import settings

    captured: dict[str, str] = {}

    class _FakeCM:
        def __init__(self, base_url: str) -> None:
            captured["base_url"] = base_url

    monkeypatch.setattr(mat, "CMClient", _FakeCM)
    out = mat._client()
    assert isinstance(out, _FakeCM)
    assert captured["base_url"] == settings.CM_URL


# ── _validate_score (순수) ───────────────────────────────────────────────────────


def test_validate_score_passes_bounds():
    assert mat._validate_score("x", 0.0) == 0.0
    assert mat._validate_score("x", 1.0) == 1.0
    assert mat._validate_score("x", 0.5) == 0.5


def test_validate_score_coerces_int_to_float():
    out = mat._validate_score("x", 1)
    assert out == 1.0
    assert isinstance(out, float)


def test_validate_score_below_zero_raises():
    with pytest.raises(ValueError, match=r"x out of range \[0,1\]: -0.1"):
        mat._validate_score("x", -0.1)


def test_validate_score_above_one_raises():
    with pytest.raises(ValueError, match=r"y out of range \[0,1\]: 1.5"):
        mat._validate_score("y", 1.5)


# ── happy path: 정확한 가중 합산 + CMM PUT ──────────────────────────────────────


def test_compute_exact_weighted_math(mock_cm):
    out = _run_compute(mock_cm)

    # clarity = 0.8*0.4 + 0.6*0.6 = 0.32 + 0.36 = 0.68
    # completeness = 0.5*0.3 + 0.4*0.3 + 0.9*0.4 = 0.15 + 0.12 + 0.36 = 0.63
    # potential = 0.7*0.5 + 0.3*0.5 = 0.35 + 0.15 = 0.50
    assert out["scores"]["clarity"] == 0.68
    assert out["scores"]["completeness"] == 0.63
    assert out["scores"]["potential"] == 0.50

    # overall = 0.68*0.30 + 0.63*0.45 + 0.50*0.25
    #         = 0.204 + 0.2835 + 0.125 = 0.6125 → round 2 = 0.61
    assert out["overall_score"] == 0.61


def test_compute_returns_full_structure(mock_cm):
    out = _run_compute(mock_cm)
    assert out["weights"] == mat.WEIGHTS
    assert out["sub_weights"] == mat.SUB_WEIGHTS
    assert out["sub_scores"] == {
        "clarity": {"purpose": 0.8, "components": 0.6},
        "completeness": {"sequence": 0.5, "causality": 0.4, "embodiment": 0.9},
        "potential": {"differentiation": 0.7, "effect": 0.3},
    }
    assert out["rationales"] == {
        "clarity": "clear",
        "completeness": "complete",
        "potential": "novel",
    }
    # return payload 은 last_updated 를 노출하지 않음 (CMM body 에만 들어감).
    assert "last_updated" not in out


def test_compute_puts_cmm_with_full_payload(mock_cm):
    out = _run_compute(mock_cm)
    mock_cm.put_concept_maturity_model.assert_awaited_once()
    args = mock_cm.put_concept_maturity_model.await_args.args
    assert args[0] == _U
    assert args[1] == _INV
    body = args[2]
    # CMM body 는 return payload + last_updated 를 포함.
    assert body["overall_score"] == out["overall_score"]
    assert body["scores"] == out["scores"]
    assert body["sub_scores"] == out["sub_scores"]
    assert body["weights"] == mat.WEIGHTS
    assert body["sub_weights"] == mat.SUB_WEIGHTS
    assert body["rationales"] == out["rationales"]
    assert isinstance(body["last_updated"], str) and body["last_updated"]
    mock_cm.aclose.assert_awaited_once()


def test_compute_zero_scores_overall_zero(mock_cm):
    out = _run_compute(
        mock_cm,
        clarity={"purpose": 0.0, "components": 0.0},
        completeness={"sequence": 0.0, "causality": 0.0, "embodiment": 0.0},
        potential={"differentiation": 0.0, "effect": 0.0},
    )
    assert out["overall_score"] == 0.0
    assert out["scores"] == {
        "clarity": 0.0,
        "completeness": 0.0,
        "potential": 0.0,
    }


def test_compute_full_scores_overall_one(mock_cm):
    out = _run_compute(
        mock_cm,
        clarity={"purpose": 1.0, "components": 1.0},
        completeness={"sequence": 1.0, "causality": 1.0, "embodiment": 1.0},
        potential={"differentiation": 1.0, "effect": 1.0},
    )
    assert out["scores"]["clarity"] == 1.0
    assert out["overall_score"] == 1.0


def test_compute_missing_rationale_defaults_empty(mock_cm):
    out = _run_compute(
        mock_cm,
        clarity={"purpose": 0.5, "components": 0.5},
        completeness={"sequence": 0.5, "causality": 0.5, "embodiment": 0.5},
        potential={"differentiation": 0.5, "effect": 0.5},
    )
    assert out["rationales"] == {
        "clarity": "",
        "completeness": "",
        "potential": "",
    }


def test_compute_non_string_rationale_coerced(mock_cm):
    out = _run_compute(
        mock_cm,
        clarity={"purpose": 0.5, "components": 0.5, "rationale": 42},
    )
    assert out["rationales"]["clarity"] == "42"


# ── id 가드 ───────────────────────────────────────────────────────────────────


def test_compute_missing_user_id_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        _run_compute(mock_cm, user_id=None)
    mock_cm.put_concept_maturity_model.assert_not_awaited()
    mock_cm.aclose.assert_not_awaited()


def test_compute_missing_work_id_raises(mock_cm):
    with pytest.raises(ValueError, match="user_id/work_id missing"):
        _run_compute(mock_cm, work_id="")
    mock_cm.aclose.assert_not_awaited()


# ── sub-dict 필수 가드 ───────────────────────────────────────────────────────────


def test_compute_missing_clarity_raises(mock_cm):
    with pytest.raises(ValueError, match="all 3 sub-score dicts required"):
        _run_compute(mock_cm, clarity=None)
    mock_cm.put_concept_maturity_model.assert_not_awaited()


def test_compute_missing_completeness_raises(mock_cm):
    with pytest.raises(ValueError, match="all 3 sub-score dicts required"):
        _run_compute(mock_cm, completeness=None)


def test_compute_missing_potential_raises(mock_cm):
    with pytest.raises(ValueError, match="all 3 sub-score dicts required"):
        _run_compute(mock_cm, potential=None)


def test_compute_empty_dict_treated_as_missing(mock_cm):
    """빈 dict 는 falsy → 'all 3 required' 가드에 걸림 (KeyError 전에)."""
    with pytest.raises(ValueError, match="all 3 sub-score dicts required"):
        _run_compute(mock_cm, clarity={})


# ── _validate_score 가 compute 안에서 범위 위반 잡음 ──────────────────────────────


def test_compute_clarity_out_of_range_raises(mock_cm):
    with pytest.raises(ValueError, match="clarity.purpose out of range"):
        _run_compute(mock_cm, clarity={"purpose": 1.4, "components": 0.5})
    mock_cm.put_concept_maturity_model.assert_not_awaited()


def test_compute_completeness_out_of_range_raises(mock_cm):
    with pytest.raises(ValueError, match="completeness.embodiment out of range"):
        _run_compute(
            mock_cm,
            completeness={"sequence": 0.5, "causality": 0.5, "embodiment": -0.2},
        )


def test_compute_potential_out_of_range_raises(mock_cm):
    with pytest.raises(ValueError, match="potential.effect out of range"):
        _run_compute(
            mock_cm,
            potential={"differentiation": 0.5, "effect": 9.9},
        )


# ── PUT 실패해도 finally aclose ───────────────────────────────────────────────────


def test_compute_closes_on_cm_error(mock_cm):
    mock_cm.put_concept_maturity_model.side_effect = RuntimeError("cm down")
    with pytest.raises(RuntimeError, match="cm down"):
        _run_compute(mock_cm)
    mock_cm.aclose.assert_awaited_once()
