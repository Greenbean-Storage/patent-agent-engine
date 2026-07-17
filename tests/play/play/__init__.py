"""play — 검증 track 6.

docker stack 이 가동된 상태에서 DRO control(`POST /control/spawn`)로 pipeline 1회 trigger +
CM trail.jsonl polling 으로 진행 관찰. 실행 '로직'(`play/_run.py`)이 probe 를 CM-하네스로 import.
dispatch_to 에 따라 spawn 된 후속 chain (P02→P03 등) 자연 BFS follow. stack MODE
자동 감지(profile) → FIXTURE 일 때만 invariants check 자동 호출. Make: `make play P{NN}.R{NN}`.
"""

__version__ = "0.1.0"
