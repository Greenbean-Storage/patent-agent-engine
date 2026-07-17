from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema


class ContractError(RuntimeError):
    pass


@dataclass
class ValidationResult:
    valid: bool
    contract: str
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


class ContractLoader:
    """
    @contracts/ 의 JSON Schema·data-model 파일을 런타임에 로드·검증.

    호출부는 contract id(파일명 줄기)만 알면 된다 — 디렉토리 위치는
    rglob으로 자동 탐색. `.schema.json` 우선, `.json` 폴백 (doc-shaped 파일용).
    """

    def __init__(self, contracts_dir: Path | str | None = None) -> None:
        self._dir = Path(contracts_dir) if contracts_dir else _find_contracts_dir()
        self._cache: dict[str, dict] = {}

    @property
    def root(self) -> Path:
        return self._dir

    def load(self, name: str) -> dict:
        """contract id로 schema dict 로드. 없으면 ContractError."""
        if name in self._cache:
            return self._cache[name]

        for ext in (".schema.json", ".json"):
            for path in self._dir.rglob(f"{name}{ext}"):
                schema = json.loads(path.read_text())
                self._cache[name] = schema
                return schema

        raise ContractError(
            f"contract '{name}' not found under {self._dir} (tried .schema.json then .json)"
        )

    def validate(self, name: str, data: Any) -> ValidationResult:
        """
        payload를 contract로 검증. invalid여도 raise 안 함 — 결과 반환.
        엄격 모드는 호출부에서 `if not result: raise ...`로 처리.
        """
        try:
            schema = self.load(name)
        except ContractError as exc:
            return ValidationResult(valid=False, contract=name, errors=[str(exc)])

        validator = jsonschema.Draft7Validator(schema)
        errors = [
            f"{'.'.join(str(p) for p in e.absolute_path) or 'root'}: {e.message}"
            for e in validator.iter_errors(data)
        ]
        return ValidationResult(
            valid=not errors,
            contract=name,
            errors=errors,
        )

    def assert_valid(self, name: str, data: Any) -> None:
        """엄격 검증 — 실패 시 ContractError raise."""
        result = self.validate(name, data)
        if not result:
            raise ContractError(f"contract '{name}' validation failed: " + "; ".join(result.errors))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _find_contracts_dir() -> Path:
    """
    @contracts 디렉토리 자동 탐지.

    1) env CONTRACTS_DIR 우선
    2) 현재 파일 기준 상위로 walk → @contracts 발견
    3) cwd 기준 상위 walk
    """
    env = os.environ.get("CONTRACTS_DIR")
    if env:
        p = Path(env)
        if p.is_dir():
            return p

    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for parent in (start, *start.parents):
            candidate = parent / "@contracts"
            if candidate.is_dir():
                return candidate

    raise ContractError(
        "@contracts directory not found. Set CONTRACTS_DIR env or pass contracts_dir explicitly."
    )
