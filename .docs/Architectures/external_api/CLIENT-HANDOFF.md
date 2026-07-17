# Nexus API — 클라이언트 핸드오프 노트

> **대상**: frontend / 외부 클라이언트 개발자
> **서버**: Nexus 게이트웨이 — 유일한 외부 표면 (모든 client REST + client WebSocket + auth)
> **기준**: 2026-06-24 · 커밋 `70f6a41`. 아래 계약 산출물은 서버가 실제 서빙하는 것과 정확히 일치(검증됨).

## 0. 계약 산출물 (단일 진실 원천)

클라가 소비할 것은 이 3개뿐. 나머지 `.docs/**`(설계·리뷰·이슈 문서)는 내부용 — 핸드오프 대상 아님.

| 표면 | 파일 | 포맷 | 용도 |
|---|---|---|---|
| **REST** | `external_api/openapi.nexus.json` | OpenAPI 3.1 | client 생성·엔드포인트 |
| **WS** | `external_api/asyncapi.yaml` | AsyncAPI 3.0 | WS API 문서 |
| **WS 검증 스키마** | `@contracts/00.dro/websocket-events.json` | JSON Schema | 봉투+payload 런타임 검증 |

**상태 범례**: ✅ LIVE · 🟡 조건부(특정 상태에서만) · 🚧 placeholder(501 미구현) · 🔒 결제게이트(현재 무조건 통과) · ⏳ future(미구현 예정)

---

## 1. 연결 & 인증

- **Base**: `https://<host>/api/v1` · **WS**: `wss://<host>/api/v1/works/{work_id}/thread/stream` (내부망은 `http`/`ws`)
- **AUTH_MODE** (서버 배포 설정 — `GET /health`의 `auth_mode`로 확인):
  - **OPEN** — 인증 불요, 고정 user_id (개발/검증 환경)
  - **SECURE** — 쿠키 인증 강제
- **인증 모델 = httpOnly 쿠키** (토큰은 JS 미접근 — XSS 탈취 차단). 클라가 토큰을 직접 다루지 않음:
  - `nx_access` — 짧은 access 토큰. HttpOnly·`SameSite=Lax`·`Path=/api/v1`·15분. **REST·WS 모두 자동 첨부**.
  - `nx_refresh` — refresh 토큰(회전). HttpOnly·`SameSite=Strict`·`Path=/api/v1/user/auth`·14일.
  - (내부 http 검증 스택은 `Secure` 미부여 토글; 외부 https 종단은 `Secure`.)
- **로그인** (federated OAuth, 3 provider: `google`/`naver`/`kakao`, **PKCE S256**):
  `GET /user/auth/{provider}/authorize`(→ `nx_pkce` 쿠키 + state) → (provider 동의) → `GET .../callback` 이 **`Set-Cookie`(nx_access+nx_refresh, httpOnly) + SPA 라우트로 302**. 토큰을 본문으로 노출하지 않음.
- **세션 유지/복구**:
  - access 만료 → `POST /user/auth/refresh` 가 **silent 회전**(새 nx_access+nx_refresh, 204). 재사용된 refresh·revoked → 서버측 family revoke + **401**(재로그인).
  - `POST /user/auth/logout` → refresh family revoke + 쿠키 clear (멱등 204).
- **CSRF 방어 = SameSite** (access=Lax → cross-site mutation 에 쿠키 미전송; 모든 mutation 이 non-GET). 별도 CSRF 토큰 불요.
- **설계 철칙 — `user_id ⊥ JWT ⊥ provider sub`**: user_id는 우리가 발급한 UUID. 클라가 경로/헤더로 **안 보냄** — 서버가 쿠키 토큰에서 해석(위조 불가). 경로엔 `{work_id}`만, user_id 없음.
- **PII 0**: 이메일/이름 미저장·토큰 미탑재. 표시명은 비-PII `alias`(기본 `발명가-xxxxxx`).
- **수명**: access 15분(회전) · refresh 14일 · WS 소켓 최대 12h **캡 단독**(짧은 access 가 WS 를 끊지 않음 — handshake 시 인증).

---

## 2. REST 표면 (트리: `info` / `user` / `works`)

> 응답에 탐색 링크(`_links`) 없음 (A-9 제거) — 클라는 아래 **고정 URL 템플릿**으로 직접 URL 을 만든다. 모든 non-2xx는 `ErrorEnvelope`(§4).

| Method · Path | 상태 | 설명 |
|---|---|---|
| `GET /health` | ✅ | 헬스 + `auth_mode` (무인증) |
| `GET /info/providers` · `/info/attributions` | ✅ | 로그인 provider 목록 · OSS/AI 고지 (무인증) |
| `GET /user/auth/{provider}/authorize` | ✅ | OAuth authorize URL + state (+ `nx_pkce` 쿠키, PKCE S256) |
| `GET /user/auth/{provider}/callback` | ✅ | code 교환(PKCE) → **`Set-Cookie`(nx_access+nx_refresh) + 302 SPA** |
| `POST /user/auth/{provider}/connect` | ✅ | 로그인 상태에서 다른 provider 연결 (code+state, PKCE; 이미 타 user면 409) |
| `DELETE /user/auth/{provider}` | ✅ | 연결 해제 (멱등 204) |
| `POST /user/auth/refresh` | ✅ | access **silent 회전** (새 쿠키 204; 재사용·revoked → family revoke + 401) |
| `POST /user/auth/logout` | ✅ | refresh family revoke + 쿠키 clear (멱등 204) |
| `GET /user/account` | ✅ | 내 정보 (user_id·alias·providers, PII 0) |
| `GET · PUT /user/account/alias` | ✅ | 별명 조회/변경 (ETag·If-Match) |
| `POST /user/works` | ✅ | work 생성 — **201 + Location** (Idempotency-Key) |
| `GET /user/works` | ✅ | 내 works 목록 (최근순) |
| `GET /works/{id}` | ✅ | work 진입점 — 가벼운 식별({work_id, title}). 하위 자원 URL 은 고정 템플릿(아래)으로 직접 구성 |
| `GET · PATCH /works/{id}/meta` | ✅ | 상세/제목 (ETag·If-Match; PATCH=제목 수정) |
| `GET · PATCH /works/{id}/phase` | ✅ | 단계 조회 / 무본문 전이 (discovery→drafting) |
| `GET /works/{id}/thread/messages` | ✅ | 대화 이력 (cursor 페이지네이션 `before=<message_id>`/`limit`; item 에 `id`=work 내 0-based 위치) |
| `GET /works/{id}/estimate/roadmap` | ✅ | 로드맵 항목 목록 |
| `PATCH /works/{id}/estimate/roadmap/{item_id}` | ✅ | **로드맵 답변** (`{value}` = str\|list[str]) — REST 단독 |
| `GET /works/{id}/estimate/maturity` | ✅ | 성숙도(CMM) — 미계산 시 shaped null |
| `POST /works/{id}/media` | ✅ | 업로드 티켓 — **201 + Location** (presigned, S3 직접) |
| `GET /works/{id}/media` · `GET /media/{id}` · `DELETE /media/{id}` | ✅ | 목록 · 메타+다운로드 URL · 삭제(204) |
| `GET /works/{id}/output/draft/preview` | ✅ | 출원서 미리보기 (마스킹 JSON, 무료) ¹ |
| `POST /works/{id}/output/draft` | 🔒🚧 | 출원서 빌드 — §5 참조 |
| `GET /works/{id}/output/draft` | 🔒 | 출원서 다운로드 (docx) — §5 참조 |
| `POST /works/{id}/output/proposal/build` | 🚧 | **501** — §5 |
| `GET /works/{id}/output/proposal/preview` · `/download` | 🚧 | **501** — §5 |
| `WS /works/{id}/thread/stream` | ✅ | client WebSocket — §3 |

¹ preview는 IOM(작성 콘텐츠) 미준비 시 `404 content_not_ready` — IOM 작성 자체가 별도 단계라 현재는 정상 경로.

---

## 3. WebSocket (`/works/{work_id}/thread/stream`)

### 봉투 (envelope v2)
```json
{ "type": "<domain>.<event>", "timestamp": "ISO-8601", "seq": 1, "data": { } }
```
- `type` = `message.*` / `work.*` / `model.*` / `output.*` / `system.*` (bare 금지). `scope`/`subject_id` 없음.
- `seq` = `(user_id, work_id)`별 monotonic — **재연결 replay 커서일 뿐, 순서·전달 보장 아님(best-effort)**. 진실은 REST, 누락 시 REST refresh로 복구.
- unicast ack/error(`message.received`·`system.error`·`system.resync_required`)는 **`seq=0`** (replay 스트림 아님 — since_seq 비교에서 제외).

### server → client (9)
| event | data | 라우팅 | 상태 | 발생 |
|---|---|---|---|---|
| `message.received` | `{correlation_id: string, id: int\|null}` | unicast(송신 소켓) | ✅ | inbound 저장 ack — `correlation_id` echo + 저장된 user turn 메시지 id(`id`). 멱등 재-ack 면 `id=null`. 후속 처리 완료 보장 아님 |
| `message.reply` | `{id: int\|null, text: string\|null}` | broadcast | ✅ | 응대(`support` 채널) 완료 시 1회 (최신 assistant 메시지 id+text; correlation_id 안 실음) |
| `work.progress` | `{display_status{ko,en?}, channel, phase?}` | broadcast | ✅ | 작업 단계 시작마다. **현재 채널 = `support`·`analysis` 만** |
| `work.progress` (채널 `research`/`thinking`/`drafting`/`review`) | 동일 | broadcast | ⏳ | 나머지 4 채널 작업은 아직 미발생 (§5) |
| `work.failed` | `{message, channel?}` | broadcast | ✅ | 처리 실패 — message는 **사용자 안전 일반 문구**(내부 식별자 비노출) |
| `model.maturity` | `{overall_score, scores{clarity,completeness,potential}, weights}` | broadcast | 🟡 | `analysis` 채널 작업 완료 + 모델 존재 시 |
| `model.roadmap` | `{count}` | broadcast | 🟡 | `analysis` 채널 작업 완료 시 (변경 신호 → 클라가 roadmap 재조회) |
| `output.ready` | `{document_id, filename, size_bytes, preview_url?, download_url?}` | broadcast | 🟡 | docx 빌드 완료 시만 (§5) |
| `system.resync_required` | `{reason}` | unicast | 🟡 | 재연결 시 replay 버퍼 소실 → 클라 REST refresh |
| `system.error` | `{code: ErrorCode, message}` | unicast(caller) | ✅ | 잘못된 inbound 프레임 (§4 ErrorCode 동일 어휘) |

### client → server (1, strict)
| action | data | 비고 |
|---|---|---|
| `message.send` | `{content: string(non-empty), correlation_id: string}` | 대화 전송. `correlation_id` = 클라 생성 멱등키(메시지당 고유, 예 UUID). **재시도는 같은 값으로 재send** → 서버가 멱등 dedup(새 turn 0, 원결과 재-ack). 같은 id·다른 content → `system.error(conflict)`. 범위 = work. 잉여 키/형식 위반 → `system.error(validation_failed)` |

> 프레임 = `{action, data}`만. 재전송은 별도 액션이 아니라 **같은 correlation_id 로 message.send 재송신**. **로드맵 답변은 WS 아님** → REST `PATCH .../estimate/roadmap/{item_id}`.

### 연결 거부 / 재연결
- **close code**: `4401`(인증 실패·토큰 만료) · `4404`(없는/접근불가 work) · `1001`(정기 12h 수명 cap 도달 = going-away, 같은 토큰 재연결). **4403 안 씀** — work 존재 여부 비노출 위해 둘 다 4404 단일.
- **heartbeat**: native WS ping/pong (app-level `system.ping/pong` 없음).
- **재연결**: `?since_seq=N` → `seq>N`만 replay. 버퍼 소실/evict/seq-reset 시 `system.resync_required` → **REST refresh로 복구**. (`since_seq=0` = fresh.)

---

## 4. 공통 규약

- **work_id** = 외부=내부 단일 식별자 (구 `invention_id` 폐기).
- **고정 URL 템플릿** (A-9: HAL `_links` 폐지 — 응답에 탐색 링크 없음). 하위 자원은 `work_id` 로 직접 조립: `…/works/{id}/meta` · `/phase` · `/thread/messages` · `/thread/stream`(WS) · `/estimate/roadmap` · `/estimate/maturity` · `/output/draft` · `/media`. (`GET /works/{id}` 는 가벼운 진입 — 식별만, 탐색 링크 없음.)
- **Idempotency-Key** (헤더) — `POST /user/works`·`POST .../media` 재시도 안전. 동일 키 진행 중 → `409`.
- **ETag / If-Match (필수)** — alias·meta 수정은 `If-Match` **필수**(낙관적 동시성, A-10). 무헤더 → `428` precondition required, 낡은 버전 → `412`. 먼저 GET 으로 응답 `ETag`(=자원 버전) 받아 그대로 `If-Match` 로 전송.
- **media presigned** — 바이트는 **서버 미경유**: 업로드=브라우저가 S3 직접 POST, 다운로드=presigned GET URL(본문, redirect 아님).
- **메타 비식별** — `work.progress.data.channel` 6 라벨: `support`/`analysis`/`research`/`thinking`/`drafting`/`review`. 내부 역할·모델 식별자 외부 노출 0. `work.failed.message`도 sanitize.

### ErrorEnvelope — REST 모든 non-2xx
```json
{ "error": { "code": "<ErrorCode>", "message": "...", "details": { } } }
```
`details`는 있을 때만 포함. **WS 는 shape 가 다름(B4)** — `system.error` 는 WS 봉투(`{type,timestamp,seq,data}`)의 `data` 안에 **bare `{code, message}`**(상위 `error` 래퍼·`details` 없음). REST·WS 는 **같은 `ErrorCode` 어휘**를 쓰되 형태는 다르다.

**클라가 switch할 `ErrorCode`** (client-reachable):
`unauthorized` · `not_found` · `validation_failed` · `conflict` · `precondition_required` · `internal` · `not_implemented` · `work_not_found` · `document_not_ready` · `content_not_ready`.
(enum의 `rate_limited`는 Actor 내부 503 포화 전용 — DRO 재시도라 client 미도달. `pipeline_ambiguous`/`pipeline_unknown`은 디버그 전용.)

---

## 5. ⚠️ 아직 안 되는 것 — placeholder / future (핸드오프 핵심)

> 데드코드 아님. 라우트·계약은 존재하되 백엔드 로직이 후속 마일스톤. 클라는 아래대로 기대.

| 표면 | 상태 | 클라가 기대할 것 |
|---|---|---|
| `POST·GET·* /output/proposal/*` (3) | 🚧 **501** | `501 not_implemented` 고정. 경량 제안서 빌드/미리보기/다운로드는 후속 마일스톤. **버튼 비활성 권장**. |
| `POST /output/draft` (빌드) | 🔒🚧 | 동기 200 body = `{document_id, filename, size_bytes}` (WS `output.ready` 와 **동일 필드명** — A-7 REST/WS 대칭). (1) **IOM 작성 workflow + 장시간 비동기 job 모델 미구현**(IOM 미준비면 빌드가 `404 content_not_ready`), (2) `document_id` **단일 `draft` 고정**(다중 출력은 ⏳future), (3) 결제게이트 `_require_payment`는 현재 **무조건 통과**(🔒 placeholder). |
| `GET /output/draft` (다운로드) | 🔒 | docx 바이트 반환. 결제게이트 현재 통과(`X-Download-Gate: placeholder` 헤더). 미생성 시 `404 document_not_ready`. **향후 entitlement 미충족 시 `402` 예정**. |
| WS `work.progress` 채널 `research`/`thinking`/`drafting`/`review` | ⏳ future | P3~P6 페르소나 미spawn → **현재 미발생**. 매핑 코드는 이미 존재 — 작성 단계 활성화 시 즉시 흐름. 현재 보이는 채널은 `support`·`analysis`만. |
| WS `model.maturity` / `model.roadmap` | 🟡 조건부 | **SECURE + ENGINE_MODE=FULL + 모델 존재** 시에만. 개발(OPEN/smalltalk)·빈 모델이면 미발생 — 클라는 REST `estimate/*`를 진실로. |
| WS `output.ready` | 🟡 조건부 | `output/draft` **빌드를 호출했을 때만**. 일반 대화 흐름에선 미발생(정상). |

### 핸드오프 시 권장
1. **`GET /health`로 `auth_mode` 먼저 확인** (OPEN/SECURE에 따라 토큰 부착 분기).
2. **WS는 보강일 뿐 — 진실은 REST.** 이벤트 누락/`system.resync_required` 시 해당 REST(`thread/messages`·`estimate/*`)로 refresh.
3. **placeholder/future 표면은 UI에서 비활성/숨김** 처리 (proposal, 빌드/결제 흐름은 백엔드 진척에 맞춰 점진 활성).
4. 에러는 HTTP status 말고 **`ErrorCode` enum으로 분기** (REST·WS 동일 어휘).
