"""venezia_deployment — 검증 knob 배포 구성 (스키마 / 프로파일 / 런타임 read / 제어 CLI).

`venezia_topology` 미러. 컨테이너는 마운트된 `/etc/deployment.yaml`(= profile.stack.yaml)을
`runtime` 으로 read 한다. 스키마는 `@deployment/knobs.yaml`(committed), 현재 값은
`@deployment/profile.stack.yaml`(gitignored, `make deploy` 가 씀).
"""

from __future__ import annotations

from .runtime import auth, engine, kipris, llm, value

__all__ = ["auth", "engine", "kipris", "llm", "value"]
