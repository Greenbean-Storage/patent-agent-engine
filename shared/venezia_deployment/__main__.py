"""make deploy CLI — generic (knobs.yaml 기반).

위치인자:
  init [<knob> <value>...]  — default profile 작성 (+ 선택 override. 예: init llm fake auth open)
  set  <knob> <value>...    — 현 profile 위에 순수 patch
  show | reset | vet        — 출력 / default 초기화 / 검증
(`vet` = profile 검증. make `validate` 타겟·probe `check`/`verify` 와 충돌 회피한 명칭.)
knob 이름/값은 knobs.yaml 로 검증 → knob 추가 시 이 CLI 무수정.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .loader import default_profile, load_knobs, load_profile, validate_profile


def _dump(profile: dict[str, Any]) -> str:
    return yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)


def _write(path: Path, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(profile), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="venezia_deployment")
    p.add_argument("--knobs", default="@deployment/knobs.yaml")
    p.add_argument("--profile", default="@deployment/profile.stack.yaml")
    p.add_argument("action", choices=["init", "show", "reset", "vet", "set"])
    p.add_argument("rest", nargs="*")
    args = p.parse_args(argv)

    knobs = load_knobs(args.knobs)
    profile_path = Path(args.profile)

    def _apply_pairs(profile: dict[str, Any], label: str) -> list[tuple[str, str]]:
        """args.rest 의 <knob> <value> 쌍을 검증·적용. 위반 시 p.error(SystemExit)."""
        if len(args.rest) % 2 != 0:
            p.error(f"{label} 은 <knob> <value> 쌍 필요 (예: {label} actor fake auth open)")
        pairs = list(zip(args.rest[0::2], args.rest[1::2], strict=True))
        for knob, val in pairs:
            spec = knobs.knobs.get(knob)
            if spec is None:
                p.error(f"unknown knob: {knob!r} (valid: {sorted(knobs.knobs)})")
            if val not in spec.values:
                p.error(f"knob {knob}={val!r} not in {spec.values}")
            if not spec.available and val != spec.default:
                p.error(f"knob {knob}={val!r} unavailable (NEXT-PLAN); only {spec.default!r}")
            profile[knob] = val
        return pairs

    if args.action in ("init", "reset"):
        # init = default + (선택) override 쌍; reset = 순수 default.
        profile = default_profile(knobs)
        if args.action == "init" and args.rest:
            _apply_pairs(profile, "init")
            validate_profile(profile, knobs)
        _write(profile_path, profile)
        print(f"✓ profile written: {profile_path}")
        return 0

    if args.action == "show":
        sys.stdout.write(_dump(load_profile(profile_path)))
        return 0

    if args.action == "vet":
        validate_profile(load_profile(profile_path), knobs)
        print(f"✓ profile valid: {profile_path}")
        return 0

    # action == "set" — 순수 patch (현 profile 위에 준 knob 만)
    if not args.rest:
        p.error("set 은 <knob> <value> 쌍 필요 (예: set actor fake auth open)")
    profile = load_profile(profile_path)
    pairs = _apply_pairs(profile, "set")
    validate_profile(profile, knobs)
    _write(profile_path, profile)
    print(f"✓ patched: {', '.join(f'{k}={v}' for k, v in pairs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
