# CM 처리·동시성 모델 — 현행 분석 + 위험 경고 (강건화 플랜용)

> CM 처리·동시성 모델의 현행 분석 + 강건화 위험. CM 동시성은 현 수준 유지 — §4 위험은 별도 강건화 작업에서 처리. 코드 위치는 현 working tree 기준.

---

## 1. 한 줄 요약 (오해 정정 포함)

- **CM 은 "글로벌 큐로 하나씩 순차 처리"가 아니다.** 요청은 **동시(async)로 처리**되고, **같은 S3 키(객체)에 대한 쓰기만** per-key `asyncio.Lock` 으로 직렬화된다. **다른 키는 병행**.
- "단일 writer"의 뜻 = **S3 에 쓰는 주체가 CM 하나뿐**(DRO·Actor·Nexus 는 전부 CM 경유). ≠ "요청을 한 번에 하나씩 처리".
- `queue_store`(아래)는 **요청 처리 큐가 아니라** 페르소나 RT FIFO **데이터 구조**일 뿐. CM 의 동시성과 무관.
- 결론: **사용자 직관(서로 같은 걸 동시에 쓰는 순간이 거의 없다)은 맞고**, 같은 키를 동시에 써도 단일 CM 프로세스 안에선 per-key Lock 이 막아준다. **단 인스턴스가 2개 이상이 되면 그 보장이 깨진다(§4 위험).**

---

## 2. 실제 처리 모델 (코드)

### 2.1 동시성 = per-key asyncio.Lock

`400.CM/src/lock.py` — `FileLockManager`:

```python
class FileLockManager:
    """resource key 별로 asyncio.Lock 1개. 같은 파일은 직렬, 다른 파일은 병행."""
    def __init__(self): self._locks = defaultdict(asyncio.Lock)
    def lock(self, key): return self._locks[key]
```

- **같은 S3 key** 에 대한 PATCH/write → `async with lock_for(key)` 로 **직렬**(read-modify-write 원자성).
- **다른 key** → **병행**(서로 다른 S3 객체라 race 없음).
- 사용처: `chain_store.py`(chain manifest/RT/trail/agent_state PATCH 6곳), `queue_store.py`(persona queue push/pop 3곳).

### 2.2 "큐"의 정체 — queue_store ≠ 요청 큐

- `400.CM/src/queue_store.py` = `runtime/{persona}/queue.json` (페르소나별 RT FIFO). **DRO 가 push/pop 하는 데이터**일 뿐, CM 이 요청을 그걸로 직렬화하지 않음.
- CM 요청 처리 자체는 **FastAPI/uvicorn async** — 동시 다발 요청을 이벤트 루프에서 concurrent 처리, 충돌 가능 지점만 per-key Lock.

### 2.3 단일 프로세스 전제

- compose 의 `cm` 서비스 1개 + uvicorn 기본 worker 1 → **단일 이벤트 루프**. `asyncio.Lock` 은 **이 프로세스 안에서만** 유효.

---

## 3. 동시성 특성 요약

| 상황                                         | 결과                                   |
| -------------------------------------------- | -------------------------------------- |
| 다른 세션(user/invention)·다른 키 동시 write | **병행** (race 없음) — 멀티유저에 좋음 |
| 같은 키 동시 write (단일 CM)                 | **per-key Lock 으로 직렬** (안전)      |
| 같은 키 동시 write (CM 인스턴스 2개+)        | ⚠️ **직렬 안 됨 → lost update** (§4)   |
| 여러 키에 걸친 작업(트랜잭션)                | ⚠️ **원자성 없음** (키마다 별도 Lock)  |

---

## 4. ⚠️ 동시 접근 위험 (강건화 플랜에서 처리)

1. **다중 CM 인스턴스 시 per-key Lock 무력화** — `asyncio.Lock` 은 in-process. CM 을 수평 확장하거나 uvicorn worker>1 로 띄우면 **같은 키 동시 write 가 직렬화 안 됨 → lost update**. (해결: 분산 락 / S3 조건부 write(If-Match/ETag) / 단일 writer 강제.)
2. **read-modify-write 윈도우** — PATCH(JSON Patch)는 read→수정→write. Lock 밖에서 read 하거나 Lock 경계가 어긋나면 갱신 유실 가능. (현재는 Lock 안에서 수행 — 단일 CM 전제 하 안전.)
3. **크로스-키 비원자성** — 한 논리 작업이 여러 객체(예: manifest + model + trail)를 건드리면 중간 실패 시 부분 반영. 트랜잭션 없음.
4. **Nexus + DRO 동시 writer** — **Nexus 도 CM write**(conversation user turn[Q21], manifest/phase[Q31], media[Q23])하고 **DRO 도 write**(chain/RT/trail/agent_state, 그리고 P01 체인의 assistant turn). 충돌 후보 = **공유 키**:
   - `runtime/00.dro/conversation.json` — Nexus(user turn) + P01 체인(assistant turn) 동시 append 가능 → **단일 CM 의 per-key Lock 이 막아줌(현재 안전)**. 단 다중 CM 면 위험(#1).
   - `manifest.context.yaml` — Nexus(phase) + 체인(status/current_phase) 동시 PATCH 가능성.
   - 대부분의 다른 키(모델·RT·trail)는 writer 가 갈려서 충돌 드묾(사용자 직관과 일치).
5. **append 동시성** — conversation/trail append 가 "read 전체 → 항목 추가 → write 전체"라면 대용량일수록 Lock 점유↑. (append-only 전용 연산/스트리밍이 더 강건.)

---

## 5. 현 결정 + 강건화 이관

- CM 동시성은 단일 CM 프로세스 + per-key Lock 으로 **현 수준 유지** — Nexus/DRO dual-writer 도 단일 CM 안에선 안전.
- 위 §4 위험(특히 #1 다중 인스턴스, #4 dual-writer 공유 키)은 **강건화 작업**으로 이관.
- 강건화 플랜 후보 작업: 다중 CM 대비 분산 락 또는 S3 ETag 조건부 write · append 전용 연산 · 크로스-키 트랜잭션/사가 · uvicorn worker/replica 정책 명시 · 부하/경합 테스트.

---

## 6. 코드 위치

| 파일                        | 역할                                                                      |
| --------------------------- | ------------------------------------------------------------------------- |
| `400.CM/src/lock.py`        | `FileLockManager` — per-key asyncio.Lock                                  |
| `400.CM/src/store.py`       | S3 read/write/patch(boto3) + RFC6902/6901                                 |
| `400.CM/src/chain_store.py` | chain/RT/trail/agent_state PATCH (lock_for 6곳)                           |
| `400.CM/src/queue_store.py` | persona RT FIFO(runtime/{persona}/queue.json) — 데이터 구조(요청 큐 아님) |
| `compose.yaml` (`cm`)       | 단일 인스턴스 · uvicorn worker 1 (per-key Lock 유효 전제)                 |

---

> **요지**: CM 은 글로벌 순차 큐가 아니라 **per-key 락 기반 동시 처리**(다른 키 병행·같은 키 직렬, 단일 프로세스 한정). 사용자 직관대로 Nexus/DRO 가 같은 키를 동시에 칠 일은 드물고, 쳐도 단일 CM 에선 안전. **진짜 위험은 "CM 다중화"와 "공유 키(conversation/manifest) dual-writer"** — 강건화 작업에서 처리.
