"""venezia_contracts logic 모델 — maturity(alias/range) + channels(persona→label)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))

from venezia_contracts.models.dro_api import channels  # noqa: E402
from venezia_contracts.models.dro_api.maturity import (  # noqa: E402
    MaturityResponse,
    MaturityScores,
)


def test_maturity_scores_raw_cm_alias():
    s = MaturityScores(
        clarity=0.9, completeness=0.7, potential=0.6
    )
    assert (s.clarity, s.completeness, s.potential) == (0.9, 0.7, 0.6)


def test_maturity_scores_populate_by_name():
    s = MaturityScores(clarity=0.5, completeness=0.4, potential=0.3)
    assert (s.clarity, s.completeness, s.potential) == (0.5, 0.4, 0.3)


def test_maturity_scores_range():
    with pytest.raises(ValidationError):
        MaturityScores(
            clarity=1.5, completeness=0.5, potential=0.5
        )


def test_maturity_response():
    r = MaturityResponse(
        overall_score=0.8,
        scores={
            "clarity": 0.9,
            "completeness": 0.7,
            "potential": 0.6,
        },
        weights={"clarity": 0.3},
    )
    assert r.overall_score == 0.8
    assert r.scores.clarity == 0.9
    assert r.weights["clarity"] == 0.3


def test_maturity_response_extra_allowed():
    r = MaturityResponse(
        overall_score=0.5,
        scores={
            "clarity": 0.1,
            "completeness": 0.1,
            "potential": 0.1,
        },
        rationale="extra field allowed",
    )
    assert r.weights is None


def test_channels():
    assert channels.channel_for_persona(1) == "support"
    assert channels.channel_for_persona(2) == "analysis"
    for p in range(1, 7):
        assert channels.channel_for_persona(p) == channels.PERSONA_TO_CHANNEL[p]
    assert channels.CHANNEL_LABELS == frozenset(channels.PERSONA_TO_CHANNEL.values())
    with pytest.raises(KeyError):
        channels.channel_for_persona(99)
