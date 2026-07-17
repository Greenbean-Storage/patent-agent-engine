# External Interface Verification Gaps

현재 자동 검증이 hard gate로 보장하지 않는 영역이다.

## 1. Real OAuth

실 provider의 대화형 consent, public redirect URI, callback은 수동 smoke 영역이다.

## 2. dro:real WebSocket Timing

dro:real의 message.reply/model/output timing은 deterministic hard assertion이 아니다. dro:fake tape와
invoke가 mapper branch를 검사하지만 실제 장시간 chain과 reconnect가 결합된 timing은 별도 soak가
필요하다.

## 3. Concurrency

다음 경쟁 조건은 자동 gate가 없다.

- 같은 ETag의 동시 PATCH
- concurrent WS emit 순서
- replay 중 live event
- message send/resend 동시 요청
- slow WebSocket consumer

## 4. Loss and Recovery

다음 loss path는 client resync까지 e2e로 검증하지 않는다.

- DRO SSE disconnect
- raw SSE seq gap
- DRO/Nexus queue overflow
- Nexus restart
- last connection GC 후 reconnect

## 5. Runtime Schema Enforcement

endpoint는 수신 frame을 schema로 검증한다. mapper unit branch의 모든 output이 같은 validator를
통과하는지는 강제하지 않으며 malformed source data negative test가 부족하다.

## 6. Security Controls

rate limit, Origin allowlist, small application payload limit, connection cap이 없어 관련 e2e도 없다.
