"""invoke — 검증 track 3.

CM / DRO / Actor / Nexus / shared(venezia_*) 의 모듈 단위 함수·class 동작
+ 모듈 간 integration 검증. docker stack 불필요. 각 suite 는 해당 컨테이너 venv 에서
ephemeral `pytest` 로 호출. Make: `make invoke`.
"""

__version__ = "0.1.0"
