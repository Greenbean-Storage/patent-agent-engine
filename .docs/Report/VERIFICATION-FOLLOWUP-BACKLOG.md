# 검증 후속 backlog

현재 검증 체계가 직접 보장하지 않는 항목만 기록한다.

---

## 1. WS payload schema cross-check

- Stage 10은 outbound event 이름과 channel label만 대조한다.
- Stage 13은 AsyncAPI 자체 meta-schema를 검사한다.
- endpoint `ws_tape`는 수신 frame을 `websocket-events.json`으로 검증하지만, mapper의 모든 가능한
  payload와 AsyncAPI payload field-set이 동일한지는 정적으로 보장하지 않는다.
- `websocket-events.json`의 type별 schema와 AsyncAPI message payload를 정규화해 required,
  properties, additionalProperties, enum/const를 대조하는 stage가 필요하다.

## 2. A3-HARNESS — 정식 재시작(restart) 회귀 시나리오 (기능 검증됨)

- **현재 검증**: DRO 재시작 복구는 **구현·실증됨** — startup `resume_active_chains` 가 실 S3 미완 chain 발견·재개
  (C2 e2e: 재시작 시 미완 chain 17개 재개·스택 healthy), `invoke test_worker.py` 가 재구성/skip 로직 단위 커버.
- **이연된 형태**: 크래시 중간 주입 → 재시작 → chain 완주를 검증하는 **정식 play 회귀 harness**(plan 이 "회귀용 후속" 명시).
- **다음**: play 에 restart 시나리오(chain 중간 DRO kill → 재기동 → trail 완주 assert). + DRO-ROBUSTNESS-BACKLOG 의 in_flight 분기(A-3 divergence)와 연동.

## 3. C3 burst — admission dedup 동시폭주 회귀 시나리오 (기능 검증됨)

- **현재 검증**: dedup 은 `invoke` 4 케이스(drop/proceed/race/find) + 시드-pending e2e(동일 4-tuple spawn → dup 미생성·`spawn_coalesced` 확인)로 검증됨.
- **이연된 형태**: dro:real 동시폭주 e2e (dro:fake 는 재현 불가 — 직접 관측 표면 없음, plan "후속").
- **다음**: dro:real 에서 같은 (session,persona) 동시 spawn 폭주 → 실행중 ≤1 + 대기 ≤1 관측.

## 4. preview 성공경로 통합검증 (잔여 = 커밋 통합 테스트)

- **현재 검증**: preview 로직은 `invoke test_router_output.py`(실 schema 모양 픽스처 —
  dict-title→ko·schema 필드(spec.technical_field/background_art.description/detailed_description)·list claims·마스킹)로 검증.
- **잔여(이연)**: endpoint(또는 probe)에 `seed IOM → preview 200` 성공경로를 **커밋된 통합 테스트**로 추가
  (현 endpoint 는 IOM 미시드→404 documented 만; 성공경로는 dro:real 수동 proof 로만 입증). 다음 검증 리팩토링에서 정식화.

---

> 참고: 코드/강건화 측 이연(재시작 in_flight 분기 A-3 divergence · dispatcher dead-path D-3)은 `DRO-ROBUSTNESS-BACKLOG.md` 에 기록.
