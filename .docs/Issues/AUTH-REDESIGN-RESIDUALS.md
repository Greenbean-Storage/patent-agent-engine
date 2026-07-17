# Nexus Auth and Account Follow-ups

현재 인증·계정 표면의 **미해소** 후속 작업만 기록한다.

## 1. OAuth State / PKCE 잔재

- 멀티탭 동시 로그인 시 단일 `nx_pkce` 쿠키를 마지막 탭이 덮어씀 → state별 키잉(서버 저장) 필요 시 후속.
- `nx_pkce` 는 성공 경로에서만 clear — exchange 실패 시 ≤600s(Max-Age) 잔존(state 바인딩+서명+IdP code 단일사용이라 replay 위험 낮음).

## 2. Provider Disconnect 잔재

- 마지막 남은 provider 까지 disconnect 하면 계정이 어느 provider 로도 로그인 불가(고아) — "마지막 provider 차단" 정책은 별도 결정.
- profile.providers **목록** 갱신은 last-write-wins(read-modify-write) — disconnect 와 다른 provider connect 가 겹치면 목록 항목 유실 가능(표시용일 뿐, 보안 권위 원천 = identity 매핑이고 그건 원자 처리). CM-side list 원자연산은 후속.

## 3. Token Lifecycle 잔재

- 회전 grace 는 **직전 1개** jti 만 — 같은 family 3중 이상 동시 갱신 또는 prev 이전 jti 는 보수적 reuse(revoke).
- issuer/audience claim 정책(현재 jti+fid 만).
- 라이브 소켓 revocation 전파(broadcast) 미구현 — logout/refresh family revoke/access 만료가 **이미 열린 WS 소켓**을 즉시 끊지 않음(다음 재연결 시 재인증). 노출은 12h 캡으로 상한.

## 4. Real Provider Verification

Google, Naver, Kakao 각각 SECURE 환경에서 다음을 수동/자동 검증한다.

- public redirect URI
- authorize/callback
- provider profile parser
- identity mint/link/conflict
- disconnect 후 재로그인

`provider_redirect_uri()`가 배포 외부 URL을 사용하도록 topology/proxy 설정을 확인한다.

## 5. Payment

draft build/download의 `X-Payment-Token` 검증은 현재 no-op이다.

- entitlement model
- 402/403 구분
- billing customer opaque reference
- preview 무료 범위

## 6. Account Input Policy

- alias max length와 allowed character policy
- title max length
- account/profile response cache policy
