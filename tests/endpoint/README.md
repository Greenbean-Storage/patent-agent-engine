# tests/endpoint

## 목적
docker stack 의 Nexus (SOLE external gateway) 가 가동된 상태에서 외부 API 표면 (REST + WS) 을 phase 단위로 호출하여 응답 contract (status code / shape / error envelope / WS envelope v2) 검증. 외부 사용자 관점의 진짜 e2e. DRO 는 순수 내부 chain executor 이고 클라이언트 REST/WS 를 제공하지 않음.

**dual-scope**: endpoint 는 DRO 가 real 이든 mock 이든 같은 코드로 Nexus client 표면만 검증. profile 의 `dro` knob 만 read —
- `dro:real` (full-e2e) — `message.reply`는 real chain 타이밍이라 warn, `ws_tape`는 skip-pass.
- `dro:fake` (mock-dro tape player) — `message.reply` hard assert + `ws_tape` 포괄 suite(`tests/data/dro-tapes`)로 event mapper를 결정적으로 검증. `model.maturity`/`model.roadmap`은 Nexus가 CM에서 생성하며 dro:fake CM은 빈값이므로 invoke·dro:real이 담당한다.

## scope (phase 단위, 11 phase — 새 트리 info/user/works, OPEN 모드 기준)
- `health` — `GET /health` (Nexus·DRO): `auth_mode`/`engine_mode`/`llm_mode`, 두 컨테이너 일치
- `info` — `GET /api/v1/info/{providers,attributions}`
- `account` — `GET /user/account` + `GET·PUT /user/account/alias` (PII 0 — email/name 부재)
- `works` — `POST /user/works` + `GET /user/works` + `GET·PATCH /works/{id}/meta`
- `auth` — `GET /user/auth/{google,naver,kakao}/authorize` (URL+state, 실 IdP 미호출) · unknown provider 404
- `work_resources` — Nexus `GET·PATCH phase` · `thread/messages` · `estimate/{GET roadmap, maturity}` · `PATCH estimate/roadmap/{item_id}` · `media`(POST · 목록 · GET {id} · {id} DELETE)
- `output` — draft build/download/preview + proposal placeholder와 output error contract
- `ws` — WS `thread/stream`: `message.send`(correlation_id 멱등)→`message.received`(unicast, `{correlation_id,id}`) · 같은 correlation_id 재send 멱등 무에러 · envelope v2 `{type,timestamp,seq,data}`(scope/subject_id 없음) · chain 구동 이벤트 work.progress/message.reply/work.failed (dro:fake = hard / dro:real = warn)
- `ws_tape` — **포괄 tape suite** (dro:fake 전용, dro:real 이면 skip-pass) — playlist 전 인덱스 순차: i번째 message.send → tape `expected`(client_events/forbidden/work.progress 채널) assert
- `error_envelope` — 404 `work_not_found` + 422 `validation_failed`
- `secure` — SECURE 전용 (무토큰→401 · 토큰→200 · WS subprotocol) — OPEN 이면 skip

## 호출 (인터페이스: positional = 대상, `VAR=` = 옵션, 모드 = 스택 속성)
```
make endpoint                 # 無인자 = 전 phase 전수
make endpoint health          # 특정 phase 만 (복수 가능)
make endpoint ws_tape         # tape suite 전수 sweep (dro:fake 스택)
make endpoint ws_tape TAPE=P01.R00.CHAT_CONVERSATION/02-rt-error-message   # 그 tape 만
make endpoint call REST="GET /api/v1/info/providers"           # 단건 REST (탐색/디버그)
make endpoint call WS='message.send {"content":"안녕하세요"}'   # 단건 WS 송신 + 수신 (correlation_id 자동주입)
```
dro:fake 레시피: `make deploy set dro fake && make up` → `make endpoint` (복귀 `make deploy set dro real && make up`).

## 의존
- `httpx>=0.28.0` · `websockets>=13.0` · `pyjwt>=2.13.0` (SECURE phase JWT mint) · `venezia-shared` (`venezia_deployment.runtime.value("dro")` — knob 감지)
- docker stack (Nexus :59100 + DRO :59200 가동; AUTH OPEN — `make deploy init llm fake auth open` 후 `make up`)

## 산출
stdout phase 별 PASS/FAIL + coverage 매트릭스(scope 반영) + aggregate exit code. exit 0 / 1.

## play 와 차이 (단위 vs 통합)
- **play = 단위 채널.** pipeline 실행 (無인자 = root 전수, DRO `POST /control/spawn` 직접) + dual 관측 (CM trail polling + DRO RAW SSE schema assert). stack MODE 자동 감지.
- **endpoint = 통합검증.** 외부 클라이언트인 척 Nexus 의 REST+WS contract 호출, 클라이언트가 겪는 **모든** 동작(전체 chain 구동 WS 이벤트 포함)을 직접 커버. 통합검증은 단위 통과분을 빼지 않음 — 커버리지를 play 에 위임하지 않는다.

## NEXT-PLAN
- **유저여정 시나리오 1급 재편** (사용자 확정 — 비범위): 현행 검증 단위 = 기능영역 phase + 케이스단위 tape. phase 들의 합성이 유저 여정(가입→works→대화→산출)을 커버하지만 시나리오라는 1급 개념은 없음 — 필요 시 별도 청크에서 재편.
- 미검증 표면 로드맵: 작성(drafting) 단계 백엔드(P05 Crafter + IOM writer) 구현 시 4 thinking 채널·output.ready 성공경로 커버 (현재 `future`).
