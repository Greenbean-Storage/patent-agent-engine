# 인터페이스 경계 상세 — 외부↔Nexus · Nexus↔DRO · DRO↔Actor

> 시스템의 "요청 경로(call path)" 3개 경계를 코드 기준으로 상세 정리한 reference.
> 클라이언트 메시지가 게이트웨이(Nexus)로 들어와 오케스트레이터(DRO)를 거쳐 워커(Actor)에 닿는
> 직렬 흐름의 세 이음매를 다룬다.
>
> **범위**: ① 외부 클라이언트 ↔ Nexus, ② Nexus ↔ DRO, ③ DRO ↔ Actor.
> **제외**: CM(`400.CM`)은 직교한 **데이터 평면**이라 본 문서에서 제외 — Nexus/DRO/Actor 가 각자 CM 을
> 호출하지만 그건 별도 경계(별도 문서). 본 문서가 "Actor 는 CM 만 호출한다" 처럼 CM 을 언급할 때는
> 경계 ③ 의 성격을 설명하기 위한 참조일 뿐, CM 표면 자체는 정리 대상이 아니다.
>
> **단일 진실 원천**: 설계도 = `.docs/Architectures/DRC_ARCHITECTURE.md`. 외부 명세 =
> `.docs/Architectures/external_api/{openapi.nexus.json, asyncapi.yaml}`. 내부 계약 =
> `@contracts/00.dro/*`. 본 문서는 그 위에 "경계별 관점"으로 재구성한 reference이며, 코드(`@router`/`@app`
> 데코레이터 전수)와 대조해 작성했다.

---

## 0. 경계 지도

```
                  ┌──────────────── 경계 ① 외부 ↔ Nexus ────────────────┐
   외부 클라이언트 │  REST  /api/v1/...   (쿠키 인증 / AUTH_MODE)           │
   (브라우저/앱)   │  WS    /api/v1/works/{work_id}/thread/stream          │
                  │        (envelope v2 — out 9 / in 2, 쿠키 인증)        │
                  └───────────────────────┬───────────────────────────────┘
                                          ▼
                              ┌────────────────────────┐
                              │   100.Nexus  (:59100)   │  유일한 외부 게이트웨이
                              │  쿠키 인증(access/refresh) │  client REST/WS 전부 소유
                              └────────────┬───────────┘
                  ┌──────────── 경계 ② Nexus ↔ DRO (Nexus 가 양쪽 dial) ──────────┐
                  │  control  Nexus→DRO REST                                       │
                  │           POST /control/spawn   (202)                          │
                  │           POST /control/output  (200, IOM→DOCX)                │
                  │  event    DRO→Nexus per-session SSE                            │
                  │           GET /events/{user_id}/{work_id}                       │
                  │           (RAW 이벤트 8종)                                      │
                  └───────────────────────┬───────────────────────────────────────┘
                                          ▼
                              ┌────────────────────────┐
                              │   200.DRO  (:59200)     │  순수 내부 chain executor
                              │   chain orchestration   │  (session,persona) worker
                              └────────────┬───────────┘
                  ┌──────────── 경계 ③ DRO ↔ Actor (DRO 가 caller) ──────────────┐
                  │  POST /dispatch       (LLM step RT — SSE: started→progress→   │
                  │                        result | error)                        │
                  │  POST /tool/{name}    (tool step RT — 200/404/400/500/503)    │
                  │  503 + Retry-After    (슬롯 포화 — DRO 시간예산 backoff 재시도) │
                  └───────────────────────┬───────────────────────────────────────┘
                                          ▼
                              ┌────────────────────────┐
                              │   300.Actor  (:59300)   │  unified 워커 (P1~P6)
                              └────────────────────────┘

   ※ 세 컨테이너(Nexus/DRO/Actor)는 각자 CM(:59400)을 호출 → 직교 데이터 평면, 본 문서 제외.
```

세 경계의 성격 요약:

| 경계 | 방향 | 채널 | 인증 | envelope |
|---|---|---|---|---|
| ① 외부 ↔ Nexus | 클라이언트 ⇄ Nexus | REST + WebSocket | **JWT (AUTH_MODE: open/secure)** | client envelope v2 |
| ② Nexus ↔ DRO | Nexus → DRO (control) · DRO → Nexus (event) | REST + per-session SSE | 없음 (내부망 신뢰) | RAW 이벤트 v1 |
| ③ DRO ↔ Actor | DRO → Actor (단방향 호출) | REST + dispatch 응답 SSE | 없음 (내부망 신뢰) | dispatch-result / SSE 이벤트 |

---

## 1. 경계 ① — 외부 클라이언트 ↔ Nexus

Nexus 는 **유일한 외부 게이트웨이**. 모든 client REST + client WebSocket 을 단독 서빙하고 JWT 를
발급·검증한다. FastAPI 앱 1개(`100.Nexus/src/main.py`), router 30 REST operation + 1 WS와
`main.py` 의 `/health`를 제공한다. `/health`를 제외한 client REST는 `/api/v1` 하위다.

### 1.1 인증 모델 (AUTH_MODE)

소스 = profile `auth` knob(default `secure`), `auth.py:get_current_user` 가 게이트.

- **OPEN** (`AUTH_MODE=open`) — 토큰 불요. 고정 user_id `00000000-0000-0000-0000-00000000open` 반환
  (`auth.get_current_user`). 로컬/검증용.
- **SECURE** (default) — **httpOnly 쿠키 `nx_access`(자동 첨부)** 의 access JWT(`typ=access`)를 검증해 `sub`→user_id.
  결손/만료/무효 시 401 (`auth.get_current_user`, `APIKeyCookie`). 클라는 토큰을 JS 로 만지지 않음(XSS 차단).
- **토큰 발급 = 콜백 Set-Cookie** — `GET /api/v1/user/auth/{provider}/callback` 이 `nx_access`(짧은 access,
  Lax·Path=/api/v1·15분) + `nx_refresh`(refresh, Strict·Path=/api/v1/user/auth·14일·회전·family revoke)를 심고 SPA 라우트로 **302**.
  `POST .../refresh`(회전) · `POST .../logout`(family revoke) 가 수명 관리. PKCE(S256, `nx_pkce` 쿠키) 적용.
- **user_id ⊥ JWT (설계 철칙)** — user_id 는 어떤 경로에서도 클라이언트가 주지 않는다. access JWT `sub` 또는
  OPEN 고정값으로 **서버가 해석**. provider sub 와도 무관(자체 UUID 발급 + `users/identities/` 매핑, PII 0).
  경로 파라미터로 오는 건 `work_id` 뿐.
- **CSRF = SameSite** (access Lax · refresh Strict). 모든 mutation 이 non-GET → cross-site 쿠키 미전송으로 차단.
- 완전 open(인증 의존성 자체가 없는) 라우트: `/health`, `/api/v1/info/*`, `auth/{authorize,callback,refresh,logout}`.
  나머지는 전부 AUTH_MODE 게이트(SECURE 면 쿠키 필수, OPEN 이면 토큰 없이 통과).

### 1.2 REST 표면 (31 operation, `/health` 포함)

> `쿠키게이트` = AUTH_MODE 게이트(SECURE 면 `nx_access` 쿠키 필수 / OPEN 통과). 출처는 `100.Nexus/src/router.py`(라인은 §부록 표 참조).

| 그룹 | Method · Path | 용도 | 인증 |
|---|---|---|---|
| **info** | `GET /api/v1/info/providers` | 로그인 provider 목록(google/naver/kakao) | open |
| | `GET /api/v1/info/attributions` | OSS·AI·저작권 고지 | open |
| **auth** | `GET /api/v1/user/auth/{provider}/authorize` | OAuth 시작 — authorization URL + CSRF state + `nx_pkce` 쿠키(PKCE) | open |
| | `GET /api/v1/user/auth/{provider}/callback` | OAuth 콜백 — PKCE 검증 → **access+refresh 쿠키 Set-Cookie + SPA 라우트로 302** | open |
| | `POST /api/v1/user/auth/{provider}/connect` | 추가 provider 연결(PKCE; 409=타 user 선점) | 쿠키게이트 |
| | `DELETE /api/v1/user/auth/{provider}` (204) | provider 연결 해제(멱등) | 쿠키게이트 |
| | `POST /api/v1/user/auth/refresh` (204) | refresh 회전 → 새 access+refresh 쿠키. 재사용/만료 → family revoke + 401 | open(쿠키) |
| | `POST /api/v1/user/auth/logout` (204) | refresh family revoke + 쿠키 clear (멱등) | open(쿠키) |
| **account** | `GET /api/v1/user/account` | 내 프로필(user_id/alias/providers, PII-0) | 쿠키게이트 |
| | `GET·PUT /api/v1/user/account/alias` | 별명 조회 / 설정(PUT) | 쿠키게이트 |
| **works(컬렉션)** | `POST /api/v1/user/works` (201) | 새 작업 생성 → work_id | 쿠키게이트 |
| | `GET /api/v1/user/works` | 내 작업 목록(title+progress, 최근순) | 쿠키게이트 |
| **works(진입)** | `GET /api/v1/works/{work_id}` | 가벼운 진입(work_id,title); 하위 자원=고정 URL 템플릿(A-9, D9) | 쿠키게이트 |
| **works/meta** | `GET /api/v1/works/{work_id}/meta` | 작업 상세 메타 | 쿠키게이트 |
| | `PATCH /api/v1/works/{work_id}/meta` | 제목 변경(title_source=user) | 쿠키게이트 |
| **phase** | `GET /api/v1/works/{work_id}/phase` | 단계 상태(discovery/ready/drafting/complete; CMM overall≥0.7→ready) | 쿠키게이트 |
| | `PATCH /api/v1/works/{work_id}/phase` | 단계 진행(본문 없음). 화면상 **`discovery`·`ready` 어느 쪽에서든 → `drafting`**(둘 다 저장 phase=`discovery`, **maturity 게이트 없음**). 매 호출이 `current_phase`+`updated_at` 을 **항상 PATCH** — 이미 `drafting`/`complete`(저장 phase=`drafting`)면 phase 는 불변이지만 `updated_at` 은 갱신됨(**true no-op 아님**). chain 트리거 없음. 응답 `state`=저장 phase. 부록 5 | 쿠키게이트 |
| **thread** | `GET /api/v1/works/{work_id}/thread/messages` | 대화 이력(커서 페이지네이션 before/limit) | 쿠키게이트 |
| **estimate** | `GET /api/v1/works/{work_id}/estimate/roadmap` | UR(로드맵 array) 조회 | 쿠키게이트 |
| | `GET /api/v1/works/{work_id}/estimate/maturity` | CMM 수치(미계산 시 shaped-null) | 쿠키게이트 |
| | `PATCH /api/v1/works/{work_id}/estimate/roadmap/{item_id}` | 로드맵 답변 → 답·status 즉시 기록(CM) + 갱신 항목 반환 + 재평가 chain spawn | 쿠키게이트 |
| **media** | `POST /api/v1/works/{work_id}/media` (201) | presigned 업로드 티켓 발급(브라우저가 S3 직접 POST) | 쿠키게이트 |
| | `GET /api/v1/works/{work_id}/media` | media 목록 | 쿠키게이트 |
| | `GET /api/v1/works/{work_id}/media/{media_id}` | media 메타 + presigned 다운로드 URL | 쿠키게이트 |
| | `DELETE /api/v1/works/{work_id}/media/{media_id}` (204) | media 삭제(멱등) | 쿠키게이트 |
| **output/draft** | `POST /api/v1/works/{work_id}/output/draft` | **docx 빌드 → DRO `POST /control/output` 위임**. IOM 없으면 404 content_not_ready | 쿠키게이트 |
| | `GET /api/v1/works/{work_id}/output/draft/preview` | 마스킹된 미리보기 JSON(무료) | 쿠키게이트 |
| | `GET /api/v1/works/{work_id}/output/draft` | docx 다운로드(결제게이트 = placeholder) | 쿠키게이트 |
| **output/proposal** | `POST .../proposal/build` · `GET .../proposal/preview` · `GET .../proposal/download` | **3종 모두 501 미구현 placeholder**(라우트는 존재) | 쿠키게이트 |
| **system** | `GET /health` | liveness + `auth_mode` | open |

요청·응답 body 형상은 `shared/venezia_contracts/models/dro_api/{account_api,work_api,document,upload,error}.py`
에 정의된 Pydantic 모델. 정식 명세 = `external_api/openapi.nexus.json`
(OpenAPI 3.1.0, securityScheme=APIKeyCookie(`nx_access`, in:cookie); 콜백은 302 + Set-Cookie 라 typed 응답 없음).

### 1.3 WebSocket — 유일한 client 채널

| 항목 | 내용 | 출처 |
|---|---|---|
| URL | `nexus:59100/api/v1/works/{work_id}/thread/stream?since_seq=N` (스킴 `ws`, 내부망 — 외부 `wss`) | `router.thread_stream` |
| 방향 | 양방향 | |
| 인증 | **httpOnly 쿠키 `nx_access`** 가 handshake(HTTP upgrade)에 자동 첨부. user_id 는 토큰에서 해석(경로에 **없음** — anti-forgery). SECURE 에서 미인증 시 accept 후 `close(4401)`(없는/접근불가 work 는 4404). OPEN 은 쿠키 없이 고정 user_id. (subprotocol bearer 폐지.) 소켓 수명 = 12h 캡 단독(짧은 access exp 에 안 묶임) — cap 도달 시 `close(1001)` going-away | `auth.user_id_from_token`, `router.thread_stream` |
| 라우팅 키 | **(user_id, work_id) WS-key broadcast** (`task_id` 없음) | `ws_manager.WSRegistry` |
| multi-tab | 한 WS-key 에 여러 connection ref-count 공유 | `WSRegistry.add/remove` |
| seq | WS-key 당 monotonic, connection 간 공유 | `WSRegistry.emit_business` |
| replay | WS-key 당 ring buffer maxlen 200. 재접속 `?since_seq=N` 으로 `seq>N` 재전송 | `WSRegistry.replay_since` |
| evict | 버퍼 밖 요청이면 부분재생 대신 `system.resync_required`(seq=0) | `WSRegistry.replay_since` |
| heartbeat | native WebSocket ping/pong (uvicorn keepalive) — app-level 이벤트 없음 | uvicorn 기본 |

연결 라이프사이클: accept 시 `registry.add` + `event_consumer.acquire(user_id, work_id)`(경계 ② SSE 를
ref-count dial). `since_seq>0` 이면 `replay_since`. 인바운드 프레임 → `ws_inbound.handle_inbound`.
disconnect 시 `registry.remove` + `event_consumer.release`(마지막 release 가 SSE consumer task 취소).

### 1.4 클라이언트 envelope v2

server→client push 의 공통 봉투(`WSRegistry.emit_business`):

```
{
  type,        # 이벤트 종류 (아래 9종, <domain>.<event> 네임스페이스)
  timestamp,   # date-time
  seq,         # WS-key 당 monotonic (since_seq replay 키)
  data         # type 이 결정하는 페이로드
}
```

required = `[type, timestamp, seq, data]`. `scope`·`subject_id` 없음(연결이 work별). additionalProperties=false.
정의 = `asyncapi.yaml`(EnvelopeBase) + `@contracts/00.dro/websocket-events.json`.

### 1.5 WS 이벤트 — 아웃바운드 9종

이벤트는 **best-effort 알림** — 진실은 CM, 누락/순서역전 시 client 가 REST refresh 로 복구한다.
RAW(경계 ②)→client 변환은 Nexus `event_mapper` 가 수행(§2.5).

| type | data 핵심 | 라우팅 | 발생 조건 |
|---|---|---|---|
| `message.received` | `{correlation_id, id}` | 송신 소켓 unicast | acceptance ack — correlation_id echo + 저장된 user turn 메시지 id(`id`=work 내 0-based 위치). 같은 correlation_id 재send(멱등) 면 원 id 재-ack, in_flight 동시중복이면 id=null |
| `message.reply` | `{id, text}` | broadcast | P01 chain 완료 시 CM conversation 최신 assistant turn id+snapshot. Admission coalescing 때문에 inbound 메시지와 1:1 cardinality는 보장하지 않음(correlation_id 안 실음) |
| `work.progress` | `{display_status:{ko,en?}, channel, phase?}` | broadcast | **모든 RT 시작 시**(RAW `rt_started`→매핑). channel = persona→6라벨. `phase` 선택 |
| `work.failed` | `{message, channel?}` | broadcast | work 처리 실패(RAW `rt_error`/`error`→매핑). message = 사용자 안전 문구(메타 비식별), raw 는 log |
| `model.maturity` | `{overall_score, scores, weights}` (closed) | broadcast | RAW `chain_completed[persona=2]` 시 Nexus 가 CM 에서 CMM fetch(DRO가 직접 발행하지 않음) |
| `model.roadmap` | `{count}` | broadcast | RAW `chain_completed[persona=2]` 시 Nexus 가 CM 에서 UR fetch(DRO가 직접 발행하지 않음; client 는 `GET …/estimate/roadmap` 재조회) |
| `output.ready` | `{document_id, filename, size_bytes, preview_url?, download_url?}` | broadcast | RAW `output_ready`(`POST /control/output` 완료) 매핑 |
| `system.resync_required` | `{reason}` | 해당 소켓 | replay 버퍼 evict / 빈 버퍼 재연결 / seq reset |
| `system.error` | `{code(ErrorCode), message}` | 송신 소켓 unicast | inbound 검증 실패 / 잘못된 JSON |

> **메타 비식별 — 6 채널 라벨**: `work.progress.data.channel` 은 persona 를 가린 라벨 6종.
> P1→`support` · P2→`analysis` · P3→`research` · P4→`thinking` · P5→`drafting` · P6→`review`.
> 단일 소스 = `shared/venezia_contracts/models/dro_api/channels.py:PERSONA_TO_CHANNEL`(14-21).
> AI/LLM/persona/buddy/director 명은 외부 노출 금지.

### 1.6 WS 이벤트 — 인바운드 1종

`ws_inbound.handle_inbound` 처리(strict 검증, `additionalProperties:false`). 모두 client→server. 위반(잉여 키·미지 action·data 비-object) → `system.error(validation_failed, ErrorCode)`.

| action | data | 동작 |
|---|---|---|
| `message.send` | `{content, correlation_id}` | `correlation_id` = 클라 멱등키. 신규면 `message_flow.handle_message` → conversation user turn write + chain spawn + `message.received{correlation_id,id}` ack(unicast) + 멱등 store 확정. 같은 correlation_id 재send = 원결과 재-ack(새 turn/spawn 0, CM idempotency store `claim`/`put`), 같은 id·다른 content = `system.error(conflict)`. 범위 = work. media 는 work-level REST 자원이며 WS 메시지 payload에 결합하지 않는다. |

> 재전송은 별도 액션이 아니라 **같은 correlation_id 로 message.send 재송신**(서버 멱등 dedup).

> roadmap 답변은 WS action 이 아니라 REST `PATCH .../estimate/roadmap/{item_id}` 단독. `ping` 은 native WebSocket ping/pong.

### 1.7 에러 envelope / 미구현

- REST 에러 = 타입드 `ErrorEnvelope`(`errors.install(app)`). 코드: `validation_failed`(422),
  `work_not_found`(404), `not_found`(404), `content_not_ready`(404), `document_not_ready`(404),
  `not_implemented`(501).
- `output/proposal/{build,preview,download}` 3종은 **항상 501**(라우트 존재, 로직 진입 전 raise). 미구현 예정 기능.
- `output/draft`(다운로드, GET) 의 결제게이트(`X-Payment-Token`)는 **no-op placeholder**. `X-Download-Gate: placeholder` 헤더.

---

## 2. 경계 ② — Nexus ↔ DRO

DRO 는 **순수 내부 chain executor** — client REST/WS/auth/media/debug 가 전부 없다. 표면은
정확히 4개(단일 포트 59200, 단일 앱). 그 중 본 경계는 **control 2개 + event SSE 1개**(`/health` 제외).
**두 채널 모두 Nexus 가 dial** 한다(control 은 Nexus→DRO 호출, event 는 Nexus 가 DRO 의 SSE 를 구독).

### 2.1 control 채널 — Nexus → DRO REST

#### 2.1.1 `POST /control/spawn` — chain 실행 요청 (`200.DRO/src/router.py:control_spawn`)

| 항목 | 내용 |
|---|---|
| 용도 | Nexus 가 chain 실행을 요청. DRO `run_chain` facade 가 RT enqueue + (session,persona) worker 깨움. pipeline_id 를 short-form(`P{NN}.R{NN}`)→full 로 resolve + **존재 사전 검증(fail-loud)** 후 202 |
| 요청 body | `{user_id, work_id, pipeline_id, chain_id, persona(int 1-6), trigger?}`. 핵심 5필드 필수. `chain_id` 는 **Nexus 가 발급**. `trigger` 기본 `{kind:"control_spawn"}` |
| 응답 | **202** `{chain_id}` · 400 validation_failed · 409 pipeline_ambiguous · 404 pipeline_unknown |
| 인증 | 없음(내부망 신뢰). user_id 는 평문(JWT 아님) |
| 계약 | `@contracts/00.dro/control-spawn-request.schema.json`(required 5, additionalProperties=false) + `control-spawn-response.schema.json`(`{chain_id}`) |

#### 2.1.2 `POST /control/output` — docx 빌드 (`200.DRO/src/router.py:control_output`)

| 항목 | 내용 |
|---|---|
| 용도 | IOM → 출원서 `draft.docx` **동기 변환**. chain/pipeline/RT/worker 없음(AI 없는 단발 경로). CM IOM(+도면 manifest) fetch → `PatentDocxGenerator().generate()` in-process → CM outputs `draft.docx` upload → RAW `output_ready` **1건 발사**. Nexus `output/draft`(빌드, POST) 가 이걸 위임 |
| 요청 body | `{user_id, work_id, variant}`. 3필드 필수. `variant` 는 `'draft'` 만(그 외 400; proposal 은 Nexus 층에서 501) |
| 응답 | **200** `{document_id:'draft', filename:'draft.docx', size_bytes}` · 400 validation_failed · 404 content_not_ready(IOM None — 구체화 미완) |
| 비고 | 동기 응답 = 빌드 확인. WS `output.ready` 알림은 event 채널로 별도(async, best-effort) |

### 2.2 event 채널 — DRO → Nexus per-session SSE (`200.DRO/src/router.py:works_events`)

| 항목 | 내용 |
|---|---|
| Path | `GET /events/{user_id}/{work_id}` |
| dial 주체 | **Nexus `event_consumer`** — client WS-key 당 1개 ref-count 로 구독(`event_consumer.py`). SSE 끊기면 1.0s 마다 재접속(refcount>0 동안) |
| 형식 | `text/event-stream`(Cache-Control:no-cache, X-Accel-Buffering:no). 프레임 = `event: <type>\ndata: <json>\n\n`(ensure_ascii=False) |
| broker | `event_sse.py` — per-(user_id, work_id) asyncio.Queue maxsize 1000(overflow=oldest-drop), seq monotonic per key. **replay 버퍼 없음**(그건 Nexus ws_manager 소유). 구독자 없으면 best-effort drop |
| RAW 봉투 | `{type, user_id, work_id, persona(1-6\|null), seq, timestamp, payload, step?}`. `chain_id`/`rt_id` 는 payload 안(Nexus 가 클라에 비노출) |

#### RAW 이벤트 8종 (계약 = `@contracts/00.dro/raw-sse-event.schema.json`, type enum)

| RAW type | 발생처 | 비고 |
|---|---|---|
| `rt_enqueued` | `orchestrator._enqueue_all_rts` | RT 큐 push(LLM·tool 모두 — tool=RT 통일) |
| `rt_started` | Actor SSE `started` → `rt_`+type | step display_status 동반 |
| `rt_progress` | Actor SSE `progress` 파생 | |
| `rt_result` | Actor SSE `result` / tool RT 결과(`orchestrator._exec_tool_call`) | |
| `rt_error` | LLM/tool RT 실패 | Nexus 가 `work.failed` 로 매핑 (사용자 안전 메시지) |
| `chain_completed` | `worker._drive_chain` | payload `{chain_id}` — `reply`/`model.*` 의 트리거 |
| `output_ready` | `router.control_output` | `{document_id, filename, size_bytes}` |
| `error` | `worker._drive_chain` | Nexus 가 `work.failed` 로 매핑 |

### 2.3 RAW → client WS 매핑 (Nexus `event_mapper`)

경계 ② 의 RAW(v1) 를 경계 ① 의 client envelope v2 로 변환하는 한 곳
(`100.Nexus/src/event_mapper.py:handle_raw_event`):

| RAW (경계 ②) | → client WS (경계 ①) | 변환 |
|---|---|---|
| `rt_started` | `work.progress` | display_status(ko required, en fallback) + channel = `PERSONA_TO_CHANNEL[persona]`(default support) |
| `chain_completed` [persona=1] | `message.reply` | CM `get_conversation`(dict `{messages}`) 최신 assistant turn 의 id(=위치)+text |
| `chain_completed` [persona=2] | `model.maturity` + `model.roadmap` | Nexus 가 CM 에서 CMM/UR fetch(있을 때만 발사) |
| `output_ready` | `output.ready` | Nexus 가 preview_url/download_url 합성 |
| `rt_error` / `error` | `work.failed` | 사용자 안전 sanitize 메시지 + channel (broadcast); raw 는 log |
| `rt_enqueued`·`rt_progress`·`rt_result` | (없음) | 내부 관측만 — client 비노출 |

**핵심 비대칭**: `model.maturity`/`model.roadmap` 은 **DRO 가 발사하지 않는다**. DRO 의 RAW 에는 그
신호가 없고, Nexus 가 `chain_completed[persona=2]` 를 보고 CM 을 fetch 해 client 이벤트를 합성한다.
(그래서 CM 이 비어있는 dro:fake 경로에서는 이 두 이벤트가 안 나간다.)

### 2.4 spawn 트리거 흐름 + admission 코얼레싱

- 사용자 메시지 1건(`message.send`) → Nexus `message_flow.handle_message`:
  conversation user turn write + manifest `/last_activity_at` patch → DRO `control_spawn`
  **P01.R00.CHAT_CONVERSATION(persona 1, 항상)**, `ENGINE_MODE==FULL` 이면 **P02.R00.CONCEPT_MATURITY(persona 2)**
  도 spawn. P01↔P02 직접 통신 없음(둘 다 conversation 만 공유).
- **admission 코얼레싱**: Nexus 는 항상 forward + conversation append. DRO 가 `run_chain` 진입에서
  `(user_id, work_id, persona, pipeline_id)` 4-tuple 로 **완전 대기중(미실행)인 동일 건**이 있으면 그 spawn 을
  버린다(대기건이 최신 conversation 으로 한 번에 판단 — 메시지는 append-only 라 유실 아님). → (session,persona)
  당 실행중 ≤1 + 대기 ≤1.

---

## 3. 경계 ③ — DRO ↔ Actor

**DRO 가 caller, Actor 가 server.** 단방향 — Actor 는 DRO 를 역호출하지 않는다(Actor 는 CM 만 호출, §3.6).
DRO `dispatcher.py` 가 outbound client. Actor 표면은 `/dispatch`·`/tool/{name}`·`/health`(본 경계는 앞 둘).
Actor 끼리 직접 통신 금지 — cross-persona 협력은 chain dispatch graph 또는 Nexus user-driven spawn 으로만.

### 3.1 `POST /dispatch` — LLM step RT 실행 (`300.Actor/src/router.py:dispatch_endpoint`)

| 항목 | 내용 |
|---|---|
| 호출 | DRO 가 LLM step(=`instructions` 키 step)마다 1회. `200.DRO/src/dispatcher.py:dispatch_to_actor`가 SSE 를 stream + parse |
| 요청 body | `{chain_id, rt_id, user_id, work_id, persona}`. 전부 필수 + persona non-null(아니면 400). persona int 캐스팅 후 그 슬롯 try-acquire |
| 응답 | **200 `text/event-stream`**(아래 이벤트 순서). 400(식별자 결손). **503 `'busy'` + `Retry-After:1`**(persona 풀 포화) |
| 인증 | 없음(내부망 신뢰) |

#### dispatch SSE 이벤트 순서 (`300.Actor/src/dispatcher.py:handle`, serializer `sse.event`)

```
started   {rt_id, actor_id}                                   # 무조건 첫 이벤트
progress  {phase:"llm_call_started", tools_loaded:[...],      # LLM SDK 호출 직전 1회
           fetch_tools:[...], media_parts:[{idx,mime,bytes}]}
result    <dispatch-result>                                   # agent_state PUT + RT output PATCH(done) 후
```

실패 경로는 `error {message}` 단일 종료 이벤트(이후 result 없음):
- persona 미수락 — `"persona N not handled by this actor"`
- RT 부재 — `"RT <rt_id> not found for persona N"`
- composer 키 결손 / 기타 예외 — `str(e)`

#### dispatch-result 계약 (`@contracts/00.dro/dispatch-result.schema.json`)

`result` 이벤트 = 완료된 RT output. `{text:string, structured:object|array|null}`. required=`[text, structured]`,
additionalProperties=false. 실 ActorSession · FixtureSession · mock-actor 모두 동일 shape. orchestrator 가
이 값을 RT.output 으로 PATCH(경계 외 — CM). play 트랙이 drift-guard 로 검증.

### 3.2 `POST /tool/{tool_name:path}` — tool step RT 실행 (`300.Actor/src/router.py:tool_endpoint`)

| 항목 | 내용 |
|---|---|
| 호출 | DRO 가 tool step(=`tool` 키 step)마다 직접 호출(LLM 없는 빠른 경로, tool=RT). `:path` 라 `kipris.search_patents` 같은 점 이름 가능 |
| 요청 body | `{"params": {...}}`(params 기본 `{}`, dict 강제) + 선택 `{rt_id, chain_id, persona, user_id, work_id}`(RT 기록용, 결손 시 no-op) |
| 응답 | **200** `{status:"success", result}` · **404** `{error_type:"not_found"}`(미등록 tool) · **400** `{error_type:"bad_params"}`(params non-dict / handler TypeError) · **500** `{error_type:"exception"}` · **503** `{status:"busy"}` + `Retry-After:1`(tool 풀 포화) |
| 동시성 | **dispatch 와 별도 풀**(`engine.config tools.max_concurrency`) |
| 비고 | 성공 시 RT 레코드(`rts/{rt_id}.json`)에 tool output 기록(`_record_tool_rt`, best-effort, CM patch_rt) |

> tool registry(`@register`, 19종 — `/health` 에 노출)는 경계 ③ 의 본문은 아니지만 호출 대상: kipris(2) /
> drawing(4) / roadmap·maturity·staging / cm(2) / knowledge / document / vision(2) / media_processor(3) / media_classifier.
> self-chain `fetch_*` 7종은 이 registry 가 아니라 `/dispatch` 시 LLM native function tool 로 동적 생성(별개 레이어).

### 3.3 동시성 계약 (포화 ≠ 실패)

`300.Actor/src/slots.py` 가 집행:

- **persona 별 dispatch 풀** cap = `engine.config personas.{id}.max_concurrency`. **tool 풀** cap =
  `tools.max_concurrency`(dispatch 와 비공유). counter-type, asyncio.Lock 보호, non-blocking try_acquire —
  `inflight >= cap` 이면 즉시 False.
- 포화 시 **HTTP 503 + `Retry-After: 1`**(`/dispatch` body=`'busy'` plain, `/tool` body=`{status:'busy'}`).
- **포화는 실패가 아니다** — 재시도는 **DRO 의 책임**:
  `200.DRO/src/dispatcher.py:dispatch_with_retry`
  가 시간예산(`DISPATCH_RETRY_BUDGET_S`) 안에서 지수 backoff(상한 `BUSY_BACKOFF_MAX_S`, 30s)로 재시도 지속.
  Actor 는 즉시 거절만.

### 3.4 미등록 persona vs 포화 (다른 경로)

- **등록된 persona 가 포화** → 503 + Retry-After(DRO backoff 재시도).
- **engine.config 에 없는 persona** → `try_acquire_persona` 가 RuntimeError → router 가 catch(acquired=None)
  → **그래도 200 SSE 스트림을 열고** `error` 이벤트(`"persona N not handled by this actor"`) 방출. 즉 503 아님.

### 3.5 dispatch 처리 흐름 (`300.Actor/src/dispatcher.py:handle`)

```
started 방출 → persona 수락 검사 → CM get_rt(없으면 SSE error)
→ get_agent_state + parse(vendor 원형 envelope, legacy 평문은 fail-loud)
→ composer 키(inject_context_spec | persona_prompt) 필수(없으면 RuntimeError→SSE error)
→ available_tools→handler + fetch_tools(선언된 llm_tools 만) + multimodal Parts 수집
→ progress(llm_call_started) → create_llm_session(persona) → compose_prompt
→ append_trail(llm_input_prepared) → sess.run(...)
→ put_agent_state → patch_rt(state="done") → result 방출
```

### 3.6 Actor 는 CM 만 호출 (DRO 역호출 없음)

경계 ③ 은 **단방향**이다. Actor 는 RT read / agent_state read-write / trail append / composer 의 `cm://`
fetch 를 위해 **CM 만** 호출하고, DRO 를 호출하지 않는다. (Actor↔CM 은 직교 데이터 평면 — 본 문서 제외.)

---

## 4. 단대단(端到端) 흐름 예시 — 사용자 메시지 1건

```
[경계 ①] client → Nexus  WS message.send {content:"..."} 
                          ← message.received ack
[Nexus]   message_flow: conversation user turn write(CM) 
[경계 ②] Nexus → DRO  POST /control/spawn P01.R00 (persona 1)  → 202
                       (ENGINE_MODE=FULL 이면 P02.R00 persona 2 도)
[DRO]     run_chain: RT 큐 push, (session,1) worker 깨움
[경계 ②] DRO → Nexus  SSE rt_enqueued, rt_started ...
[경계 ①] Nexus → client  WS work.progress {channel:"support", display_status}
[경계 ③] DRO → Actor  POST /dispatch {chain_id,rt_id,...,persona:1}
[Actor]               started → progress → result {text,structured}   (CM agent_state PUT / RT PATCH)
[경계 ③] (tool step 이면) DRO → Actor  POST /tool/cm.append_conversation → 200
[DRO]     chain 종료
[경계 ②] DRO → Nexus  SSE chain_completed {chain_id} (persona 1)
[Nexus]   event_mapper: CM conversation 최신 assistant turn fetch
[경계 ①] Nexus → client  WS message.reply {text:"..."}   (P01 chain 완료 기준)
```

P02(구체화, persona 2) 가 함께 돌면 `chain_completed[persona=2]` 시 Nexus 가 CM 에서 CMM/UR fetch →
`model.maturity` / `model.roadmap` 를 추가로 push(§2.3).

---

## 5. 계약·명세 SoT 인덱스 (경계별)

| 경계 | 표면 | 명세 |
|---|---|---|
| ① REST | Nexus client REST | `external_api/openapi.nexus.json`(OpenAPI 3.1.0) |
| ① WS | Nexus client WebSocket | `external_api/asyncapi.yaml`(AsyncAPI 3.0, host `nexus:59100`) + `@contracts/00.dro/websocket-events.json`(envelope v2 + 이벤트) |
| ① 채널 라벨 | persona→channel 6라벨 | `shared/venezia_contracts/models/dro_api/channels.py:PERSONA_TO_CHANNEL` |
| ② control | spawn/output | `@contracts/00.dro/control-spawn-request.schema.json` · `control-spawn-response.schema.json` |
| ② event | RAW SSE | `@contracts/00.dro/raw-sse-event.schema.json`(type enum 8종) |
| ③ dispatch | result 이벤트 | `@contracts/00.dro/dispatch-result.schema.json` |
| 공통 | health | `@contracts/_shared/health.schema.json` |

> DRO 는 client REST 표면이 없으므로 OpenAPI 스펙이 없다(경계 ②/③ 은 내부 계약
> `@contracts/00.dro/*` 로만 규정).

---

## 6. 검증 매핑 (각 경계를 어느 track 이 검증하나)

| 경계 | 주 검증 track | 무엇을 |
|---|---|---|
| ① 외부↔Nexus | **endpoint**(통합) | 외부 클라이언트인 척 Nexus REST+WS 11 phase 전수. `ws_tape` 35 case(dro:fake 전용)로 P01/P02 playlist 조합과 event mapper 분기를 결정적으로 검증 |
| ② Nexus↔DRO | **play**(단위) + endpoint | play 가 DRO `POST /control/spawn` 직접 트리거 + DRO RAW SSE 검증(raw-sse-event schema·monotonic seq·≥1건). endpoint 가 RAW→client 매핑까지 |
| ③ DRO↔Actor | **enact**(격리 게이트) | harness 가 DRO 역할 대행 — `POST /dispatch` SSE 계약 + `POST /tool` 200/404/400/500 + concurrency(503+Retry-After) + errors(4 SSE-error 경로). 5/5 시나리오 게이트 |
| ①②③ 정적 | **validate** | openapi/asyncapi/websocket-events 3-way 정합 + 계약 스키마 |
| ①②③ 로직 | **invoke** | 스택 없이 각 컨테이너 로직 라인 99%(event_mapper 매핑, dispatcher backoff, slots 포화 등) |

---

## 부록 — 현재 phase 전이 규칙

`PATCH …/phase`는 매 호출마다 manifest를 PATCH한다:
`current_phase ← ("drafting" if 저장값=="discovery" else 저장값)`과 `updated_at ← now()`.
따라서 저장 phase가 이미 `drafting`이어도 `updated_at`은 갱신된다.

`GET …/phase`의 `ready`는 maturity에서 계산한 표시 상태이며 저장값은 `discovery`다. 그러므로
`discovery`와 `ready` 모두 maturity gate 없이 `drafting`으로 전진한다. 이미 `drafting` 또는
`complete`이면 phase는 불변이다. PATCH 응답 `state`는 전이 후 저장 phase이며 GET의 표시 상태를
재계산하지 않는다.

### 부록 표 — Nexus REST 라우트 라인 인덱스 (`100.Nexus/src/router.py`)

providers · attributions · auth/{authorize,callback,connect} · auth DELETE ·
account(GET) · account/alias(GET·PUT) · works(POST 생성·GET 목록) · meta(GET·PATCH) ·
phase(GET·PATCH) · thread/messages · estimate/roadmap(GET) · estimate/roadmap/{item_id}(PATCH) ·
estimate/maturity · media(POST·GET) · media/{media_id}(GET·DELETE) · output/draft(POST·GET) ·
output/draft/preview · output/proposal/{build,preview,download}(501) · thread/stream(WS) · /health.
(정확한 위치는 `100.Nexus/src/router.py` 데코레이터 참조.)
