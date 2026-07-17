# DRO 강건화 backlog (failsafe / 폴백 — 나중에)

> DRO **위험·강건화 backlog** (미착수). 강건화 단계에서 처리.

## 알려진 갭

- **DRO↔Actor 네트워크/타임아웃 재시도 없음** — 지금 DRO↔Actor 사이 연결 끊김·타임아웃(`httpx.RequestError`/`TimeoutException`)은 재시도 없이 즉시 `ActorError` → chain failed. **일시 장애인데 한 번에 실패** 처리됨. → 일시 분류 + backoff 재시도 추가 여지. (LLM API 자체의 5xx/429 는 Actor adapter 가 이미 재시도하지만, DRO↔Actor 구간은 안 함.)
- **미완 RT 의 append 부작용 정리(#16)** — 재시작 시 미완 RT 의 append 형 부작용(대화·trail)을 실제로 지우는 구현. 강건 구현 필요.
- **일시/영구 경계 정밀화** — 무엇을 일시로 볼지(현재 unknown 은 보수적 retryable). 오분류 위험.
- **재시작 시 in_flight RT 처리 (A-3 divergence)** — 재시작 시 `worker._rehydrate_done_steps` 가 `state=='done'` 만 복원하고, in_flight RT(Actor 가 끝냈으나 DRO 가 `state=done` patch 전 크래시한 경우)는 재dispatch(재실행)한다. A-3 결정은 "RT.output 존재 시 done 간주(skip)" 였으나 그 분기 미구현. 정상 flow 가 output+state=done 을 1회 원자 patch 라 in_flight 창이 좁아 위험 낮음(비멱등 step 만 영향). → 재시작 시 `output 존재 + state=in_flight → done 간주` 분기 추가 여지.
- **dispatcher loaded_tools dead-path (C7 D-3)** — `300.Actor/src/dispatcher.py` 의 `@register` lookup 경로가 현재 0 파이프라인 사용(모든 fetch_* 는 self-chain allowlist). 무해한 미사용 경로 — 정리 또는 future opt-in 시 활용.
- (추가 항목은 발생 시 여기에 누적.)

## 실패 모델 (정의 — #17)

- **일시(transient)**: 5xx · 429 rate-limit · 네트워크 끊김 → Actor LLM adapter 가 backoff 재시도(`300.Actor/src/llm/retry.py` `_RetryableLLMError`).
- **영구/구조적(permanent)**: 401/403/400 · 콘텐츠 차단 · 잘못된 입력 · 파이프라인 오류 · 분기값(dispatch_choice) 오류 · 스키마 못 맞춤 → fail-loud, 재시도 X(`_PermanentLLMError`).
- 포화(503)는 실패 아님 — 시간예산 backoff 재시도(#8).

## 운영 관점 (향후 운영 리팩토링)
- **파이프라인 hot-reload / A/B 배포 / 임시 서버** — 운영중 파이프라인 갱신용. 현재는 재배포(풀 rebuild)로만 반영(#20). 운영 단계에서 필요 시 도입.
