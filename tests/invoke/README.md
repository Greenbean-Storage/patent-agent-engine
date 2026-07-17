# tests/invoke

## 목적
스택 없이 5 패키지 (shared · cm · dro · actor · account) 의 로직을 라인 단위로 검증 — 함수·class 동작 + 모듈 간 integration (asyncio Lock concurrency 등). **유일한 라인-커버리지 트랙** (라인 99% 게이트). docker stack 불필요. CM 도 가짜 S3 로 스택 없이 구동 — CM 을 빼지 않는다.

## scope (5 suite)
- **shared suite**: venezia_* 6 패키지 전 모듈 (pipeline_runtime / memory / topology / contracts / logging / deployment)
- **cm suite**: 400.CM/src 전 모듈 (store / chain_store / queue_store / lock / router — 가짜 S3 + ASGITransport)
- **dro suite**: 200.DRO/src 전 모듈 (orchestrator / dispatcher / pipeline_walker / branch_evaluator / event_sse / router)
- **actor suite**: 300.Actor/src 전 모듈 (dispatcher / actor_session / router / llm/* / tools/*)
- **account suite**: 100.Nexus/src 전 모듈 (auth / router / ws_manager / ws_inbound / event_mapper / event_consumer / message_flow)

## 커버리지 설정
omit/exclude 설정은 제품 src/pyproject·shared 가 아니라 **tests/invoke/coveragerc** (`--cov-config`) 에만 둔다. 제품 코드에 검증 흔적 0 — 제품 src/pyproject·shared 에 `# pragma`·`[tool.coverage]` 두지 않는다.

## 호출
```
make invoke                          # 모든 suite
cd tests/invoke && uv run python -m invoke --suite cm
```

## 의존
- `pytest>=8.3.0`
- `pytest-asyncio>=0.24.0`
- 각 컨테이너 venv 에서 ephemeral pytest 실행 (`uv run --directory <pkg> --with pytest/pytest-asyncio/pytest-cov`) — shared 소스만 conftest 가 `sys.path` 주입

## 산출
pytest 표준 출력 (PASSED/FAILED + summary). exit 0 / 1.

## 명명
패키지명 `invoke` 는 pytest 공식 문서 "how to *invoke* pytest" 관용과 `pyinvoke` task-runner 의 의미를 따름. PyPI 의 `invoke` (pyinvoke) 와는 다른 로컬 패키지 — `uv sync` 가 만든 venv 안에서만 동작.
