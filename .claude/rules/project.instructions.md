---
description: **
applyTo: '**'
---

# Patent AI Agent Engine (DRC)

> 설계 의도 원본: `.docs/Architectures/STATIC_BLOCK_ARCHITECTURE.md`
> DRC 설계도 (현행 단일 진실 원천): `.docs/Architectures/DRC_ARCHITECTURE.md`
> Actor SDK 통합: `.docs/Architectures/AGENT_SDK_DESIGN.md`
> Director 흐름: `.docs/Architectures/DIRECTION_PIPELINE_FLOW.md`, 도면 흐름: `.docs/Features/DRAWING_FLOW.md`

## 목적

특허 출원을 돕는 AI Agent 시스템. 사용자는 내부 구현을 모르고 우리 서비스로 인식함.

## 목표

1. **발명 구체화 → 출원서 작성**까지 일관된 AI 지원
2. **선행기술 조사 및 분석** 자동화
3. **출원 가능성 평가 및 전략** 제안

## 아키텍처 (DRC — Distributed Reasoning Chain)

AI agent 의 사고 흐름을 외부 큐로 분해. RT(Reasoning Task) 단위로 분해된 사고가
큐에 적재되고, Actor 컨테이너는 로직 없는 수동 워커로 RT 를 단위 호출만 수행.
모든 상태는 S3 에 영속화.

### 4 Units / 4 Containers / 6 Personas

| Unit | Container | Port | 역할 |
|------|-----------|------|------|
| Nexus | `100.Nexus` | 59100 | 외부 게이트웨이 단독 — 모든 client REST + client WebSocket + 쿠키 기반 인증(httpOnly access/refresh 회전·PKCE). mypage 영역 (auth + account + work CRUD/metadata) + 모든 client-facing surface (info/user/works/phase/thread/estimate/media). 토큰 발급·검증 단독 |
| DRO  | `200.DRO` | 59200 (단일 포트) | 순수 INTERNAL chain executor. surface = {POST /control/spawn, POST /control/output(docx 빌드, C6), GET /events/{user_id}/{work_id} (SSE), GET /health}. client REST/WS/media/auth/debug-app 없음 |
| CM   | `400.CM`  | 59400 | Context Manager. S3 단일 writer |
| Actor| `300.Actor` | 59300 | unified Actor — P1~P6 전 persona 단일 컨테이너 (수락 집합 = engine.config `personas`, persona 별 동시성 cap = `src/slots.py` 세마포어) |

> **포트 스킴**: 59{container-number} — Nexus 59100, DRO 59200, Actor 59300, CM 59400.

> **표기**: Container 열 = container_name(`docker ps`). DNS 서비스키 = `nexus`/`dro`/`cm`/`actor`, 소스 디렉토리 = `100.Nexus`/`200.DRO`/`400.CM`/`300.Actor`.

**REST 표면 — Nexus 가 client-facing 전부**: Nexus = info/user/works (`/api/v1/info/*` + `/api/v1/user/auth/{provider}/*` + `/api/v1/user/account`(+`/alias`) + `/api/v1/user/works`(생성·목록) + `/api/v1/works/{id}`(진입 인덱스)·`/meta`) + phase·thread·estimate(roadmap/CMM)·media + client WebSocket. DRO = client REST 없음 (internal surface 만: `POST /control/spawn`, `POST /control/output`(docx 빌드, C6 — Nexus output/draft 가 위임), `GET /events/{user_id}/{work_id}` SSE, `GET /health`). Nexus 가 JWT 발급·검증 단독 — DRO 는 auth 없음 (internal-network trust). WS 는 Nexus 소유 (`ws_manager`, `ws_inbound`, `event_consumer`).

**WS `work.progress.data.channel` 6 라벨**: P1→`support` · P2→`analysis` · P3→`research` · P4→`thinking` · P5→`drafting` · P6→`review`. 매핑은 `shared/venezia_contracts/models/dro_api/channels.py:PERSONA_TO_CHANNEL` 한 곳. 메타 (AI 비식별) — AI/LLM/persona/buddy/director 명 외부 노출 금지.

### 6 Personas → LLM 매핑

| Persona | 이름 | LLM | 컨테이너 |
|---------|------|-----|---------|
| P1 | Buddy | Gemini 3.1 Pro Preview (Vertex AI) | 300.Actor |
| P2 | Director | Claude Opus 4.7 | 300.Actor |
| P3 | Finder | Gemini 3.1 Pro Preview (Vertex AI) | 300.Actor |
| P4 | Thinker | GPT o3 | 300.Actor |
| P5 | Crafter | Claude Opus 4.7 | 300.Actor |
| P6 | Inspector | Gemini 3.1 Pro Preview (Vertex AI) | 300.Actor |

매핑의 단일 진실 원천: `@deployment/engine.config.yaml` 의 `personas` (sdk/model/fallback_model/effort/max_concurrency — 코드 persona-제로, Actor 는 `src/engine_config.py` 범용 로더로 read, 빌드타임 COPY). Gemini 는 Vertex AI (global endpoint only, service account JSON via AWS Secret).

### 데이터 흐름

```
외부 클라이언트
    │ REST / WebSocket
    ▼
100 Nexus (외부 게이트웨이 단독) ───────────────────────────────────
    │ 0. client REST + client WS 수신 + JWT auth
    │ 0. message_flow → conversation.json user turn write + chain spawn 결정
    │ 0. POST /control/spawn → DRO (control channel)
    │ 0. DRO events SSE 구독 (event channel) → event_mapper (persona→channel + display_status)
    └── WS push → Client (message.received/work.progress/message.reply/work.failed, model.maturity/model.roadmap/output.ready, system.*)
    │ control = Nexus→DRO REST · event = DRO→Nexus per-session SSE (RAW). Nexus 가 양쪽 dial.
    ▼
200 DRO (순수 INTERNAL chain executor) ─────────────────────────────
    │ 1. POST /control/spawn → run_chain(producer): chain 생성 + RT 일괄 push + (session,persona) worker 깨움
    │ 2. (session,persona) 단일 worker 가 큐를 chain-at-a-time 소비 → pipeline 순회 (같은 persona chain 직렬)
    │ 3. step 순회 (병렬 묶음 = asyncio.gather)
    │ 4. RT pop → Actor /dispatch (SSE)
    │ 5. RT output PATCH → 다음 step
    │ 6. chain 종료 → dispatch_to 후속은 run_chain 핸드오프 + RAW event emit
    └── per-session SSE (GET /events/...) → Nexus (RAW: rt_*, chain_completed, error)

300 Actor (모든 persona 공통 단일 코드베이스)
    │ POST /dispatch (body 에 persona — DRO 전달) → persona 슬롯 try-acquire (cap=engine.config, 포화 503+Retry-After)
    │ CM RT GET (body persona dir 직접) → agent_state(vendor 원형 envelope, 컨텍스트 ②) load·native 복원 → LLM SDK 호출 → tool call (in-process)
    │ agent_state PUT (envelope {schema_version,vendor,model,items}) → RT output PATCH → SSE result
    │ POST /tool/{name} → tool registry handler (tool 도 RT — LLM 없는 빠른 경로, rt_id·기록 LLM 동일)

400 CM
    │ users/* + /sessions/{u}/{i}/* — 76 endpoint (users[identity(+delete)/profile/idempotency/refresh-tokens], manifest, runtime/chains/rts, models, drawings, outputs, inputs, patch, admin/active-chains)
    │ /sessions/{u}/{i}/runtime/* — chain runtime (manifest, queue, RT, trail, agent_state, dialog, inputs)
    │ 모든 write 는 file_key 단위 asyncio.Lock 으로 직렬화
```

**Actor 끼리는 직접 통신하지 않는다.** 모든 dispatch 는 DRO 가 중재.
**Actor 는 CM 만 호출**하며 (RT read/agent_state read-write/trail append, composer 의 inject_context 가 cm:// 경로 직접 fetch),
DRO 를 호출하지 않는다.

### 핵심 데이터 원칙

1. **IOM 소유권 (장기 원칙)**: 오직 P2 Director(Claude)만 IOM(invention-object-model.json)을 쓴다. DRO·다른 페르소나·frontend 직접 수정 금지. **현재**: P02.R00 (구체화 단계 임시 chain) 은 CDS/CMM/UR 만 갱신하고 IOM 은 read-only. 정식 P02.R99 (미구현 target) 활성화 시점부터 P02 가 IOM patch.
2. **사용자 입력 흐름**: 모든 입력(채팅·구조화) → `runtime/00.dro/conversation.json` (Nexus `message_flow` 가 user turn write + P01 chain 이 assistant turn append) → director 가 conversation 읽고 (현재) CDS/CMM/UR 갱신, (활성화 시) IOM 반영. DRO 는 IOM 을 직접 patch 하지 않고 user turn 도 쓰지 않는다.
3. **Nexus 의 user-driven 동시 spawn**: 사용자 메시지 1건 → Nexus `message_flow` 가 **`POST /control/spawn` 으로 P01.R00 + P02.R00 chain spawn 을 DRO 에 트리거** (DRO 가 RT enqueue). P01(응대) 은 사용자에게 즉시 응답 + conversation 누적, P02(Director, 현재 R00) 는 conversation 보고 CDS/CMM/UR 갱신. P02 동시 spawn 여부 = `ENGINE_MODE` (Nexus config). P01 ↔ P02 직접 dispatch 통신 없음.
4. **P01 self-contained**: 응대 페르소나(P01)의 모든 chain 은 자기 작업 + CM 영속 저장(conversation.json) + exit. 다른 페르소나로 dispatch 하지 않음.
5. **AI 판단 우선**: 무엇을 IOM 에 쓸지는 Claude(director)가 결정. 사용자 입력은 raw 재료.
6. **RT 1개 = 1 작업단위** (LLM 1회 invocation **또는** tool 1회 호출 — 모든 step 이 RT, tool=RT 통일 N-7): LLM step 의 SDK 내부 function calling (self-chain `fetch_*` allowlist) 루프는 1개 RT 안에서 진행. cross-persona 호출은 chain dispatch (P02→P03/P04/P05/P06) 또는 Nexus 의 user-driven spawn(DRO admission dedup 후 실행) 으로만.
7. **persona 별 동시성 cap**: Actor 는 persona 별 동시 요청 한도(engine.config `max_concurrency`)를 `src/slots.py` 세마포어로 집행 — `/tool` 은 별도 풀. 포화 즉시 503+`Retry-After` ≠ 실패: DRO 가 시간예산 안에서 backoff 재시도 지속. CM 큐 장부 = rt_id 별 lease (release 는 본인 것만, 만료 lazy 제거).
8. **(session,persona) 단일 worker 가 chain-at-a-time 소비**: 파이프라인을 쌓아두지 않음. producer(`run_chain`)가 spawn 시 RT 들을 `runtime/{persona}/queue.json` (RT 큐) 에 push, (session,persona) 당 단일 worker(`200.DRO/src/worker.py`)가 큐를 chain-at-a-time 소비 → 같은 (session,persona) 의 chain A + chain B 는 **직렬** (A 끝나야 B). 다른 persona=다른 worker, 다른 session 도 병렬 (P01+P02 동시 enqueue 는 다른 persona 라 여전히 평행). 병렬 step fan-out(nested list)은 한 chain 안 동시 RT. race 자료는 file-key asyncio.Lock 으로 처리.

### Shared Storage 구조 (DRC)

```
s3://venezia-bucket/sessions/{user_id}/{work_id}/
├── manifest.context.yaml             # 세션 정체성·status·current_phase
│
├── runtime/                          # 모든 런타임 + 페르소나 누적 + DRO 자료
│   ├── manifest.runtime.yaml         # chain 인덱스
│   ├── 00.dro/                       # DRO 자체 자료 (queue/chain 없음)
│   │   └── conversation.json         # 사용자-시스템 대화 (Nexus message_flow user turn + P01 assistant turn)
│   ├── 01.buddy/queue.json + {chain_id}/...
│   ├── 02.director/queue.json + analysis.json + decisions.json
│   │   + evaluation.json + workspace.json + {chain_id}/...
│   ├── 03.finder/queue.json + research.json + rejection-cases.json + {chain_id}/...
│   ├── 04.thinker/queue.json + {chain_id}/...
│   ├── 05.crafter/queue.json + {chain_id}/...
│   └── 06.inspector/queue.json + evaluation.json + {chain_id}/...
│
│   각 {chain_id}/ 안:
│     manifest.json  trail.jsonl  rts/{rt_id}.json  agent_state.json
│
├── models/                           # AI 산출 정량 모델
│   ├── manifest.models.yaml
│   ├── invention-object-model.json   # IOM (writer: P02)
│   ├── concept-maturity-model.json   # CMM (writer: P02 via maturity.compute tool, P-C)
│   ├── concept-discovery-stack.json  # CDS (writer: P02 via staging.save tool, P-C — 모델 아님, 사용자 말 7 필드 누적)
│   └── user-roadmap.json             # UR (writer: P02 via roadmap.persist tool, P-D — top-level JSON array)
│
├── drawings/                         # AI 산출 도면
│   ├── manifest.drawing.yaml
│   └── {drawing_id}/{numerals,dl,figure}.json
│
├── outputs/                          # 최종 산출물
│   ├── manifest.outputs.yaml
│   └── draft.docx                    # writer: DRO POST /control/output (docx_generator.py, C6 배선). Nexus output/draft 가 위임
│
└── media/                            # 사용자 업로드 (work 레벨, presigned S3 직접 — 메시지/chain 무관, 장부 없음)
    └── {media_id}.{ext}              # 브라우저가 presigned POST 로 S3 직접 업로드. writer: 브라우저
```

**단일 truth source**: `shared/venezia_memory/scaffolding.yaml`. 모든 컴포넌트는 `venezia_memory` 의 key builder 호출. 직접 literal 금지.

### REST 엔드포인트 요약 (client REST 전부 Nexus + DRO internal)

> 모든 client-facing REST + WS 가 Nexus 단독. 트리 = info/user/works. 현행 SoT = `external_api/openapi.nexus.json` (Nexus-only) + `asyncapi.yaml`. user_id ⊥ JWT, AUTH_MODE(OPEN|SECURE).

| 컨테이너 | 묶음 | Path (op) |
|---|---|---|
| Nexus `:59100` | info | `GET /api/v1/info/{providers,attributions}` |
| Nexus | auth | `GET /api/v1/user/auth/{provider}/{authorize,callback}` · `POST .../connect` · `DELETE /api/v1/user/auth/{provider}` · `POST /api/v1/user/auth/refresh`(회전) · `POST /api/v1/user/auth/logout` |
| Nexus | account | `GET /api/v1/user/account` · `GET·PUT /api/v1/user/account/alias` |
| Nexus | works(컬렉션) | `POST /api/v1/user/works`(생성·**201**+`Location`) · `GET /api/v1/user/works`(목록) |
| Nexus | works(진입) | `GET /api/v1/works/{work_id}` (가벼운 진입 {work_id,title}; 하위 자원 = 고정 URL 템플릿, A-9·D9) |
| Nexus | works/meta | `GET·PATCH /api/v1/works/{work_id}/meta` |
| Nexus | phase | `GET·PATCH .../phase` (PATCH=무본문 전이, 서버가 로직 보유) |
| Nexus | thread | `GET .../thread/messages` · `WS .../thread/stream` (쿠키 인증) |
| Nexus | estimate | `GET .../estimate/roadmap` · `PATCH .../estimate/roadmap/{item_id}`(답변) · `GET .../estimate/maturity` |
| Nexus | output | `POST .../output/draft`(빌드·200 동기 placeholder — 빌드 기능 미구현) · `GET .../output/draft`(다운로드·결제게이트) · `GET .../output/draft/preview` · proposal/* = 501 placeholder |
| Nexus | media | `POST .../media`(업로드 티켓·**201**+`Location`) · `GET .../media`(목록) · `GET .../media/{media_id}`(메타+다운로드 URL) · `DELETE .../media/{media_id}` (presigned S3 직접 — 바이트 서버 미경유, work 레벨·메시지 무관) |
| DRO `:59200` | internal | `POST /control/spawn` · `POST /control/output` (docx 빌드, C6) · `GET /events/{user_id}/{work_id}` (SSE) · `GET /health` |

(work_id = 외부 이름 = 내부 work_id. proposal·결제게이트 = placeholder. dev/test pipeline trigger = DRO `POST /control/spawn` 직접 호출.)

### WebSocket events (Nexus client 채널, envelope v2)

URL = `nexus:59100/api/v1/works/{work_id}/thread/stream?since_seq=N` (스킴 `ws` — 내부망, 외부 표면은 `wss` 종단). 인증 = httpOnly 쿠키 `nx_access` 가 handshake 에 자동 첨부(OPEN 이면 토큰 없이). user_id 는 경로에 없음 — Nexus 가 쿠키에서 해석. WS 라우팅 = (user_id, work_id) WS-key broadcast (multi-tab ref-counted, `event_consumer`). DRO SSE 의 RAW event 를 Nexus `event_mapper` 가 매핑 (persona→channel + display_status). 라우팅은 (user_id, work_id) WS-key 만.

**양방향**:
- server → client push (envelope v2 `{type, timestamp, seq, data}` — scope/subject_id 없음. 모든 type 은 `<domain>.<event>` 네임스페이스, bare 금지)
- client → server inbound action (`message.send {content, correlation_id}` 단일 — strict 검증, `ws_inbound.py`. `correlation_id`=클라 멱등키, 재시도는 같은 id 재send → 서버 멱등 dedup. 별도 resend 액션 없음)

**이벤트 9종** (이벤트는 best-effort 알림 — 진실은 CM, 누락 시 client refresh 로 복구, #15):
- `message.received` — 저장 완료 ack (data `{correlation_id, id}` — correlation_id echo + 저장된 user turn 메시지 id; 송신 소켓 unicast). `task_id` 없음 (id=메시지 id, work 내 0-based 위치)
- `message.reply` — P01 응대 답장 (data `{id, text}` — 최신 assistant turn 메시지 id+텍스트; **메시지당 1회** — Nexus 가 chain 완료[persona=1] 시 CM conversation 최신 assistant turn 에서 생성. correlation_id 안 실음)
- `work.progress` — RT lifecycle (data: `display_status{ko,en?}` + `channel`; **모든 RT 시작 시** 발생, persona→channel)
- `work.failed` — work 처리 실패 (data `{message, channel?}`; 사용자 안전 메시지 — 메타 비식별. rt_error/error 매핑, broadcast)
- `model.maturity` — CMM push (Nexus 가 chain_completed[persona=2] 시 CM 에서 CMM fetch 로 생성, **DRO 미발사** #12; data closed `{overall_score, scores, weights}`)
- `model.roadmap` — 변경 신호 (Nexus 가 chain_completed[persona=2] 시 CM 에서 UR fetch 로 생성, **DRO 미발사** #12; client 가 `GET .../estimate/roadmap` 재조회)
- `output.ready` — docx 빌드 완료
- `system.resync_required` / `system.error` — 인프라 (heartbeat 는 native WS ping/pong, app-level `system.ping/pong` 없음)

**`work.progress.data.channel` 6 라벨** (메타 AI 비식별 — persona/buddy/director 노출 금지):
`support` (P1) · `analysis` (P2) · `research` (P3) · `thinking` (P4) · `drafting` (P5) · `review` (P6). 매핑 = `shared/venezia_contracts/models/dro_api/channels.py:PERSONA_TO_CHANNEL` 한 곳.

**내부 RAW event** (DRO→Nexus per-session SSE, envelope v1): `rt_enqueued / rt_started / rt_progress / rt_result / rt_error / chain_completed / error` raw — Nexus `event_mapper` 가 외부 envelope v2 로 변환.

스키마: `@contracts/00.dro/websocket-events.json` + `.docs/Architectures/external_api/asyncapi.yaml` (AsyncAPI 3.0, servers/host = Nexus `nexus:59100`).

### Tool Registry (Actor 공유)

`300.Actor/src/tools/` 페르소나 무관 공유 라이브러리. **DRO tool step** 으로 호출되는 도구들 — `POST /tool/{name}` 으로 DRO 가 직접 호출. LLM agent 의 native function calling tool (`llm_tools`) 과는 별개. KIPRIS 자체는 외부 API/데이터 소스이고, 그 wrapper 가 도구.

| Tool | 설명 |
|------|------|
| `kipris.search_patents` | KIPRIS 검색 (queries list 받아 병렬 호출) |
| `kipris.get_patent_detail` | KIPRIS 특허 상세 조회 |
| `drawing.render` | 도면 코드 (PlantUML / OpenSCAD / schemdraw) → 이미지 |
| `cm.save_drawing_artifacts` | CM 에 도면 산출물 (numerals / DL / figure) 저장 |
| `knowledge.load_rejections_section` | IPC 기준 거절 패턴 Section guide 로드 |
| `media_classifier.classify` | 멀티미디어 입력 분류 (현 pipeline 미참조 — P01.R00 step 0 이 Gemini multimodal 로 직접 분석) |
| `media_processor.image_describe` / `document_describe` / `audio_describe` | 멀티미디어 → 설명 (현 pipeline 미참조) |
| `staging.save` | CDS PUT (P02.R00 step 1) |
| `maturity.compute` | CMM 가중 합산 + PUT (P02.R00 step 5). `model.maturity` WS 는 Nexus 가 chain 완료 시 CM fetch 로 생성 (DRO 미발사, #12) |
| `roadmap.persist` | UR top-level array PUT (P02.R00 step 7). `model.roadmap` WS 는 Nexus 가 chain 완료 시 CM fetch 로 생성 (DRO 미발사, #12) |
| `cm.append_conversation` | conversation assistant turn append (P01.R00 step 2) |

> **KIPRIS RAG 는 도구가 아니라 chain dispatch graph** — P03 Finder 의 R00 → R01 → R02 → R11 로 분해. 5단계 파이프라인의 역할 분담:

| 분해된 chain (pipeline_id) | 역할 |
|------|------|
| P03.R00.PRIOR_ART_SEARCH_ANALYZE | 발명 분석, 검색 쿼리 생성 |
| P03.R01.SEARCH_AND_REFLECT       | KIPRIS 병렬 검색 + 커버리지 평가 + 재검색 분기 (self-recursion) |
| P03.R02.POST_REFLECT             | 청구항 대비표 + 신규성/배타성 합성 |
| P03.R11.EVALUATE_NOVELTY         | 발명-prior_art 비교 + claim chart + synthesis |

## Tech Stack

1. 표준 준수 — 커뮤니티 표준 라이브러리 우선
2. 최신 도구 우선

| 영역 | 기술 | 비고 |
|------|------|------|
| Framework | FastAPI | Python 3.14+ |
| Package Manager | **uv** | pip/poetry 대체 |
| Storage | AWS S3 | CM (400.CM) 가 단일 writer, boto3 직접 |
| Validation | Pydantic v2 | |
| Inter-container | HTTP + SSE | 큐 기반 |
| LLM (P2/P5) | **Claude Opus 4.7** | `claude-agent-sdk` |
| LLM (P1/P3/P6) | **Gemini 3.1 Pro Preview (Vertex AI)** | `google-adk` + `google-genai`. global endpoint only. service account JSON via AWS Secret. |
| LLM (P4) | **GPT o3** | `openai-agents` |
| LLM fallback | Gemini → `gemini-3-flash-preview` | rate-limit/cost 대응. Vertex 동일 endpoint. |
| Document | **python-docx** | DRO `docx_generator.py` — C6 에서 `POST /control/output` 으로 배선 (IOM→docx→CM upload→output.ready) |
| Tools | plantuml / openscad / schemdraw / chromadb | Actor 이미지 의존성 |

### LLM 호출 모드 (Actor `LLM_MODE` — profile `llm` knob, env 아님)

소스 = `@deployment/profile.stack.yaml` 의 `llm` knob (real=PRODUCTION · fake=FIXTURE, **default = real**).
로컬은 `make deploy set llm fake` (또는 `init … llm fake`).

| 모드 | 설명 |
|------|------|
| `FIXTURE` (llm:fake) | `FIXTURE_PATH/{pipeline_id}/{step_id}.json` replay — 로컬 dev / 회귀 테스트 |
| `PRODUCTION` | 실 SDK 호출 (Claude / Gemini Vertex / OpenAI). EC2 IAM role 환경에서만. AWS Secrets Manager 가 모든 credential 의 단일 source |

flow 인프라 테스트는 FIXTURE 가 더 정확.

**`ENGINE_MODE`** (P01-only vs P01+P02) = Nexus config. Nexus 가 사용자 메시지마다 P01 만 spawn 할지 P01+P02 둘 다 spawn 할지 결정.

## Pipeline 포맷 (P{NN}) — 단일 진실 원천

**모든 *.pipeline.json 은 `P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json`**. `W{NN}` / `step.type` / `step.next` / `parallel_task` / `sequential_conditional` / `api_call` / `http_response` / `sub_pipeline` / `agentic_llm_loop` 키는 **허용 안 됨** — `pipeline_walker._assert_no_legacy_keys` 가 발견 시 fail-loud(RuntimeError).

### 4-layer Cascading

```
GLOBAL.json (@pipelines/_shared/)
  → P{NN}.COMMON.json (persona)
    → pipeline.common
      → step
```

머지 항목: `inject_context` / `recommended_context` / `fragments` / `llm_tools`. 같은 name + 같은 source 가 두 layer 중복 = validator error.

### Step 타입 (단 2종)

| step | 조건 | 동작 |
|------|------|------|
| LLM step | `instructions` 키 존재 | composer 가 prompt 합성 → Actor SDK 호출 |
| tool step | `tool` 키 존재 | DRO 직접 `POST /tool/{name}` (LLM 없음). **tool 도 RT** — rt_id·`rts/{rt_id}.json` 기록·`rt_*` 이벤트가 LLM step 과 동일 (tool=RT 통일, N-7) |

### instructions 객체 형태

`instructions` 는 **객체** — 안에 `inline` (string) **XOR** `reference` (string, `@pipelines/.../*.md` path) 중 정확히 1개. 거의 모든 LLM step 은 `reference` 사용 — pipeline.json 옆 체인 디렉토리 (`@pipelines/{NN}.{persona}/P{NN}.R{NN}/{step_slug}.md`) 에 표준 markdown 으로 분리.

```json
{
  "instructions": {
    "reference": "@pipelines/01.buddy/P01.R00/assess.md"
  }
}
```

Actor 의 composer (`300.Actor/src/composer.py:_resolve_instructions_reference`) 가 read → prompt 의 `[TASK]` 섹션에 markdown 그대로 dump. lru_cache 로 hot read. `list[str]` / `string` 형식은 허용 안 됨 — loader + `_assert_no_legacy_instructions` 가 발견 시 fail-loud(RuntimeError).

### chain dispatch graph

`sub_pipeline` 은 허용 안 됨. 마지막 step 의 `output_contract` 의 `dispatch_choice` (integer enum) → `dispatch_to.actions[choice]` 의 pipeline_id 들이 다음 chain. self-recursion 으로 loop. `dispatch_to: null` 또는 빈 actions = exit.

### LLM 의 llm_tools — self-chain 한정

cross-persona 도구 금지 (Actor 끼리 직접 통신 금지). 허용:
`fetch_dialog` / `fetch_step_output` / `fetch_drawing` / `list_drawings` / `fetch_outputs` / `fetch_conversation`.

cross-persona 호출은 **dispatch_to 그래프로만**. `_assert_no_cross_persona_tools` 가 fail-loud.

### list nesting = 정적 병렬

`steps: [..., [s1, s2, s3], ...]` 의 nested list 가 fan-out group (asyncio.gather).
