# tests/play

## 목적
docker stack 이 가동된 상태에서 DRO `POST /control/spawn` 으로 chain 1회 trigger + **dual 관측**:
① **CM `trail.jsonl` polling** (진행 실시간 step 출력) ② **DRO per-session RAW SSE** (`GET /events/{u}/{work}` — `raw-sse-event` schema 자동 assert).
dispatch_to 에 따라 spawn 된 후속 chain (P02→P03 등) 자연 BFS follow. stack MODE 자동 감지 → FIXTURE 일 때만 invariants check 자동 호출, PRODUCTION 일 때 skip (SSE 관측·assert 는 모드 무관 항상).

> 실행 '로직'(`play/_run.py`: run_pipeline · trail follow-loop · spawned BFS · poll · detect)은 play 소유. CM 접근·출력·검증 primitive 는 **probe(CM-하네스)** 에서 import (play→probe 단방향). RAW SSE 소비(`play/_sse.py`)는 **play 내부 self-contained** (자체 미니 SSE 파서 — probe 무관, RAW SSE 검증 = play 전용).

## scope
- DRO :59200 internal REST (`POST /control/spawn` — chain 1회 trigger) + **per-session RAW SSE** (`GET /events/{u}/{w}` — replay buffer 없어 trigger **전** 구독, per-(user,work) 키라 spawned chain 도 한 구독이 커버). DRO 는 순수 내부 chain executor — 클라이언트 REST/WS/auth 없음
- CM :59400 GET — `trail.jsonl` polling(chain 진행 실시간 step 출력, `_fetch_trail_raw`) + chain status / RT polling
- **chain dispatch graph BFS** — spawn 된 후속 chain 자연 follow (P02 가 P03/P04/P05/P06 spawn 하면 다 추적)
- probe 를 **CM-하네스로 import**: `probe._pipeline`(setup·CM fetch·rich print·render primitive) + `probe.commands.check`(`verify_chain`, fixture mode 자동 호출)
- **RAW SSE 자동 assert** (`@contracts/00.dro/raw-sse-event.schema.json`, `venezia_contracts.ContractLoader`): 수신 전건 schema 통과 + seq 순단조증가 + ≥1건 수신 + consumer 무예외 — 하나라도 실패 = play FAIL (exit 1). seq gap·first≠1 은 경고 출력만 ("자동검증 가능 = assert, 사람 확인 필요 = 출력")
- **dispatch-result 자동 assert** (`@contracts/00.dro/dispatch-result.schema.json`): 완료된 RT.output 전건 — `{text, structured}` 계약 위반 = play FAIL (raw_asserts ② drift guard, mode 무관)

## 호출
```
make play                                                        # 無인자 = root pipeline 전수 (*.R00.* 순차 + 집계)
make play P03.R00                                                # 단일 chain 실행 (DRO POST /control/spawn)
make play P03.R00 SEED=path/to/iom.json WS_TIMEOUT=1800
```

## 의존
- `httpx>=0.28.0` (DRO /control/spawn + RAW SSE streaming + CM REST: trail / chain / RT polling)
- `click>=8.0` (CLI)
- `rich>=13.0.0` (실시간 step 출력)
- `jsonschema>=4.23.0` (RT output schema 표시 + RAW SSE schema 검증)
- `probe` (CM-하네스 라이브러리 — setup/fetch/print/verify primitive)
- `venezia-shared` (`venezia_deployment.runtime` — profile read 로 stack MODE 감지 · `venezia_contracts.ContractLoader` — raw-sse-event schema)
- docker stack (사전 부팅: `make deploy init llm fake auth open` 후 `make up`. 실 운영은 `make deploy init` 후 `make up`)

## 산출
stdout 실시간 step 출력 (CM trail polling) + raw SSE 요약 (type 히스토그램 · seq range · assert 결과) + chain 완료 후 (fixture mode 자동) invariants 결과. exit 0 / 1.

## stack 부팅과 관계
play 는 pipeline runner 만. stack 부팅·빌드는 별도 utility — `make deploy init [<knob> <value>...]` 로 모드(profile) 설정 후 `make up`(positional 없음). 모드 = `@deployment/profile.stack.yaml` knob(engine/llm/auth/kipris), 컨테이너가 마운트 read(env 아님). pipeline runner 와 본질 무관.

play 는 시작 시 `@deployment/profile.stack.yaml` 를 직접 읽어 현 stack MODE 자동 감지(`venezia_deployment.runtime.llm()`). 수동 `--fixture/--no-fixture` flag 없음.
