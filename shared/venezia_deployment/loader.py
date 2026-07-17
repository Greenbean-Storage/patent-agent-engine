"""knobs.yaml(스키마) / profile.stack.yaml(현재 값) 로드 + 검증."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .model import KnobsSchema

PROFILE_VERSION = 1


def load_knobs(path: str | Path) -> KnobsSchema:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"knobs.yaml not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return KnobsSchema.model_validate(data)


def default_profile(knobs: KnobsSchema) -> dict[str, Any]:
    """전 knob 을 default 값으로 채운 평면 profile (version + knob:value)."""
    prof: dict[str, Any] = {"version": PROFILE_VERSION}
    for name, spec in knobs.knobs.items():
        prof[name] = spec.default
    return prof


def load_profile(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"profile.stack.yaml not found: {p} — run: make deploy init")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"profile.stack.yaml 최상위가 mapping 아님: {p}")
    return data


def validate_profile(profile: dict[str, Any], knobs: KnobsSchema) -> None:
    """평면 profile 을 knobs 스키마로 strict 검증 — 위반 시 ValueError."""
    if profile.get("version") != PROFILE_VERSION:
        raise ValueError(f"profile version {profile.get('version')!r} != {PROFILE_VERSION}")
    for key, val in profile.items():
        if key == "version":
            continue
        spec = knobs.knobs.get(key)
        if spec is None:
            raise ValueError(f"unknown knob in profile: {key!r}")
        if val not in spec.values:
            raise ValueError(f"knob {key}={val!r} not in {spec.values}")
        if not spec.available and val != spec.default:
            raise ValueError(f"knob {key}={val!r} unavailable (NEXT-PLAN); only {spec.default!r}")
    missing = set(knobs.knobs) - (set(profile) - {"version"})
    if missing:
        raise ValueError(f"profile missing knobs: {sorted(missing)}")
