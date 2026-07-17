# tests/lint

## 목적
200.DRO / 400.CM / 300.Actor / 100.Nexus / shared / tests/* 의 Python 코드(DRO·Actor mocks 포함)를 정적 분석하여 style·suspicious construct·type·security pattern·CVE 검출. **Make 명령 1회로 자동수정+검사 일괄** (별도 format 단계 없음).

## scope
- **ruff** lint + format **자동 적용** (`ruff check --fix` + `ruff format`, write — 각 패키지 `[tool.ruff]` 설정 사용)
- **mypy** type check (per-package)
- **bandit** (코드 보안 패턴: SQL injection, hardcoded secret 등)
- **pip-audit** (의존성 CVE: pyproject.toml + uv.lock)

4 runner 모두 게이트 — 전부 exit 0 이어야 PASS (advisory baseline 없음). auto-fix 불가분(E501 등)만 잔여로 FAIL.

## 호출
```
make lint                       # 4 runner 일괄 (자동수정+검사)
cd tests/lint && uv run python -m lint --runner ruff   # 특정 runner
```

## 의존
- `ruff>=0.8.0`
- `mypy>=1.13.0`
- `bandit>=1.7.0`
- `pip-audit>=2.7.0`

## 산출
runner 별 결과 + aggregate exit code. `make lint` 한 번이 포매팅·자동수정·검사를 모두 수행.

## 참고
pre-commit 은 폐기됨 (`.pre-commit-config.yaml` 삭제) — git hook 강제가 사용자를 실제로 막지 못해 무력. 대신 `make lint` 가 PR 직전·CI·수동 점검의 단일 게이트(자동수정 포함).
