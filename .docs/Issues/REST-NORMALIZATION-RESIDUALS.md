# Nexus REST Current Follow-ups

현재 REST 계약의 **미해소** 후속 작업만 기록한다.

## 1. Atomic ETag

alias/meta의 If-Match는 필수(무헤더 428·stale 412, A-10)이나 비교와 CM write가 별도 단계다.
하나의 **조건부 atomic operation**으로 만든다.

- 위치: `100.Nexus/src/router.py`, `400.CM/src/router.py`
- 검증: 같은 ETag 동시 요청 중 하나만 성공

## 2. Draft Job Model

현재 `POST /output/draft`는 기존 IOM을 DOCX로 동기 변환한다. 장시간 비동기 작성/변환으로 확장할
때는 202, job resource, Idempotency-Key, polling 상태를 함께 도입한다.

## 3. Pagination

works/media/roadmap pagination 정책 (thread는 `before=<message_id>` 커서로 정합됨 — A-4).

## 4. Idempotency Record Lifecycle

- completed record TTL/GC
- media request fingerprint
- expired presigned ticket refresh
- side effect 후 record finalize 실패 복구

## 5. Proposal

`output/proposal/{build,preview,download}`는 모두 501이다. 구현 시 draft와 별도 resource,
media type, payment policy, output.ready variant를 정의한다.
