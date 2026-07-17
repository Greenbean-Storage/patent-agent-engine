"""invoke 의 pytest test suite 들 — path-scoped (패키지 venv 별 99% 게이트).

shared/   — shared/venezia_* (pipeline_runtime / memory / topology / contracts / logging)
cm/       — 400.CM/src (가짜 S3 + ASGITransport, 스택 없는 CM 로직 검증)
dro/      — 200.DRO/src
actor/    — 300.Actor/src
account/  — 100.Nexus/src

invoke = 유일한 라인-커버리지 트랙(5 패키지). omit/exclude = tests/invoke/coveragerc.
"""
