# Nexus External API Follow-ups

외부 REST와 WebSocket의 **미해소** 후속 작업 index다.

## REST

- atomic If-Match: `REST-NORMALIZATION-RESIDUALS.md`
- OAuth state/disconnect/token 잔재: `AUTH-REDESIGN-RESIDUALS.md`
- media idempotency/presigned lifecycle/CORS: `MEDIA-RESIDUALS.md`
- proposal 501
- payment gate
- work subtree 404/error code 통일
- roadmap answer partial failure 복구
- phase state machine 정합화

## WebSocket

- ordered seq cursor (WS 이벤트 순서 보장 — 현재 best-effort)
- replay/live join race
- DRO SSE gap/drop resync
- resumable message processing (spawn 실패 재개 — W5)
- slow socket isolation
- rate/frame/connection/Origin controls
- single-process deployment invariant
- shared broker/state for scale-out

## Output

`POST /output/draft`는 현재 존재하는 IOM을 DOCX로 동기 변환한다. IOM 생성 workflow와 drafting
pipeline의 제품 흐름은 별도 작성 단계 설계 대상이다.

`output/proposal/{build,preview,download}`는 501이다.

## Notifications

현재 WS catalog에는 account/IOM multi-device sync event가 없다. 이 기능을 도입하려면 REST read
resource, event type, refresh algorithm을 함께 설계한다.
