# DRC Architecture (Distributed Reasoning Chain)

> 본 문서는 DRC 의 **현행 단일 진실 원천** 설계도. 모든 코드 (DRO / CM / Actor / validator) 가 이 문서의 정의대로 작동. 설계 의도 원본 (수정 금지) 은 `STATIC_BLOCK_ARCHITECTURE.md`. 페르소나별 도메인 흐름은 `DIRECTION_PIPELINE_FLOW.md` (Director), `../Features/DRAWING_FLOW.md` (도면), 구체화 단계 (P02.R00.CONCEPT_MATURITY + CDS/CMM/UR + roadmap 답변(REST)) 통합 reference 는 `../Features/CONCEPT_MATURITY_FLOW.md`, SDK 통합은 `AGENT_SDK_DESIGN.md`. 알려진 잔재 issue 는 `../Issues/DIRECTOR-R00-RESIDUALS.md`.

---

## 1. 개요

DRC 는 AI agent 의 사고 흐름 (reasoning chain) 을 **외부 큐로 분해** 하는 아키텍처. 각 사고 단위 (RT, Reasoning Task) 는 큐에 적재되고, Actor 컨테이너는 **로직 없는 수동 워커** 로 RT 를 단위 호출만 수행. 모든 상태 (큐 · 체인 · RT 입출력 · agent_state) 는 S3 에 영속화.

**한 줄 핵심**: AI 가 스스로 루프를 돌지 않고, 큐에 적재된 RT 를 외부에서 단위 호출. Actor 끼리 직접 통신 금지 — cross-persona 협력은 (1) **Nexus 의 user-driven spawn** (사용자 메시지 → P01.R00 + P02.R00 평행, Nexus `message_flow` 가 결정·forward / DRO 는 admission dedup 후 실행 — D-7) 또는 (2) **chain dispatch graph** (P02 → P03/P04/P05/P06 같이 자기 chain 의 dispatch_to 로 다음 chain trigger) 로 표현. 진행 상황 추적·재시도·확장이 자연스럽게 가능.

**Fail-loud 정책**: W{NN}, step.type, sub_pipeline, parallel_task, sequential_conditional, api_call, http_response, agentic_llm_loop, error_handling 등의 키는 허용 안 됨 — 들어오면 즉시 `RuntimeError`. 5 위치에서 검출 (§8).

---

## 2. 용어

| 용어                            | 정의                                                                                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Session**                     | (user_id, work_id) 쌍. 사용자가 한 발명을 지속적으로 진행하는 단위. 장기 보관.                                                   |
| **Chain**                       | pipeline 1회 실행. 사용자 메시지 1개 → entry pipeline 1회 실행 = 1 chain. spawned chain 들도 각자 별도 chain.                                                        |
| **chain_id**                    | chain 의 uuid.                                                                                                                        |
| **RT (Reasoning Task)**         | chain 안의 Actor 1회 호출 단위. = LLM 1회 invocation.                                                                                 |
| **rt_id**                       | RT 의 uuid.                                                                                                                           |
| **Persona**                     | DRC 6 역할 (P1 Buddy, P2 Director, P3 Finder, P4 Thinker, P5 Crafter, P6 Inspector).                                                  |
| **Actor**                       | 수동 워커 컨테이너. unified 단일 컨테이너 (`300.Actor`, :59300) — P1~P6 전 persona 수락 (수락 집합 = engine.config `personas`). RT 마다 어떤 persona 든 처리 가능, persona 별 동시성 cap = `src/slots.py` 세마포어.                                             |
| **DRO**                         | Distributed Reasoning Orchestrator. **순수 내부 chain executor** (외부 창구 아님 — 그건 Nexus). chain orchestration + 큐 produce/consume + chain dispatch graph 진행. 표면 = `POST /control/spawn` + `POST /control/output`(docx 빌드, C6) + `GET /events/...` SSE + `GET /health`.                                                      |
| **CM**                          | Context Manager. S3 단일 writer.                                                                             |
| **RT 큐 (페르소나 큐, Persona Queue)** | 페르소나별 RT FIFO (`runtime/{persona}/queue.json`, 6개 — P1~P6 각 1개). RT 큐는 (session,persona) 단일 worker 가 chain-at-a-time 소비 (같은 persona chain 직렬; 다른 persona·다른 session 은 병렬). producer(`run_chain`)가 spawn 시 RT 들을 큐로 push, worker 가 pop, Actor 는 HTTP 로 호출 받음. race 자료는 file-key Lock. |
| **Agent State**               | vendor 원형 envelope `{schema_version, vendor, model, items}` — thinking/tool_use/tool_result 포함 풀충실도 (컨텍스트 ②). 같은 chain 안의 같은 persona RT 끼리 native 복원으로 이어짐. `runtime/{persona}/{chain_id}/agent_state.json` 에 영속화 (포맷 상세 = AGENT_SDK_DESIGN).                              |
| **Composer**                    | Actor 의 prompt 합성기. RT.input 의 cascading 결과 (persona_prompt + inject_context_spec + recommended_context_spec + fragments + instructions + dispatch_choice_guide) 를 single-text prompt 1개로 합성. RT.input.prompt / system_prompt 는 항상 빈 문자열. |
| **dispatch_choice**             | 마지막 step 의 `output_contract` schema 의 integer enum 필드. `dispatch_to.actions[dispatch_choice]` 가 next chain 결정.                              |
| **Tool**                        | DRO direct tool step (`POST /tool/{name}`, LLM 없는 빠른 경로) 또는 Actor SDK 의 self-chain function calling (`fetch_*` allowlist 만). cross-persona 도구 금지. |

---

## 3. Unit / Container / Persona 구조

### 4 Units / 4 Containers / 6 Personas

| Unit | Container | Port | 역할 |
|------|-----------|------|------|
| Nexus | `100.Nexus` | 59100 | **유일한 외부 게이트웨이** — 모든 client REST + client WebSocket + 쿠키 기반 인증(httpOnly access/refresh 발급·검증·회전·PKCE). mypage (auth + account + work CRUD/metadata) + phase·thread·estimate·output·media. ws_manager · event_mapper · ws_inbound · message_flow · event_consumer · dro_client 소유. media = presigned S3 직접(바이트 미경유). |
| DRO  | `200.DRO` | 59200 (single) | **순수 내부 chain executor.** chain orchestration · 큐 produce/consume · chain dispatch graph. 표면 = `POST /control/spawn` + `POST /control/output`(docx 빌드, C6) + `GET /events/...` (SSE) + `GET /health` 뿐. client REST/WS/media/auth/debug-app 없음. |
| CM   | `400.CM`  | 59400 | Context Manager. S3 단일 writer. |
| Actor| `300.Actor` | 59300 | unified Actor — P1~P6 전 persona 단일 컨테이너 (수락 집합 = engine.config `personas`, persona 별 동시성 cap = `src/slots.py` 세마포어). |

> **표기**: Container 열 = container_name(`docker ps`). DNS 서비스키 = `nexus`/`dro`/`cm`/`actor`, 소스 디렉토리 = `100.Nexus`/`200.DRO`/`400.CM`/`300.Actor`.

**외부 표면 = Nexus 단독** (info/user/works/phase/thread/estimate/media): Nexus 가 모든 client-facing REST + client WebSocket 을 서빙 — `/api/v1/info/*` + `/api/v1/user/auth/{provider}/*` + `/api/v1/user/account`(+`/alias`) + `/api/v1/user/works`(생성·목록) + `/api/v1/works/{id}`(진입 인덱스)·`/meta` + phase·thread·estimate(roadmap/CMM)·output(draft/proposal)·media·WS 전부. DRO 는 client REST 를 서빙하지 않는다. JWT 는 Nexus 가 발급·검증.

**내부 채널 (Nexus ↔ DRO)**: (1) **control** — Nexus → DRO REST `POST /control/spawn {user_id, work_id, persona, pipeline_id, chain_id}` → 202; (2) **event** — DRO → Nexus per-session SSE (`GET /events/...`, RAW event). Nexus 가 두 채널 모두 dial. Nexus 의 `event_mapper` 가 persona→channel + display_status 변환.

### 6 Personas → LLM 매핑

| Persona | 이름 | LLM (primary) | LLM (fallback) | 컨테이너 |
|---------|------|---------------|----------------|---------|
| P1 | Buddy | gemini-3.1-pro-preview (Vertex AI) | gemini-3-flash-preview | 300.Actor |
| P2 | Director | claude-opus-4-7 | claude-opus-4-7 (same-model retry) | 300.Actor |
| P3 | Finder | gemini-3.1-pro-preview (Vertex AI) | gemini-3-flash-preview | 300.Actor |
| P4 | Thinker | o3 (OpenAI) | o3 (same-model retry) | 300.Actor |
| P5 | Crafter | claude-opus-4-7 | claude-opus-4-7 (same-model retry) | 300.Actor |
| P6 | Inspector | gemini-3.1-pro-preview (Vertex AI) | gemini-3-flash-preview | 300.Actor |

매핑의 단일 진실 원천: `@deployment/engine.config.yaml` 의 `personas` (sdk/model/fallback_model/effort/llm_settings/max_concurrency — **코드 persona-제로**, Actor 는 `src/engine_config.py` 범용 로더가 빌드타임 COPY 된 `/app/engine.config.yaml` 을 기동 시 read. 스키마 = `@deployment/engine-config.schema.json`, 검증 = validate stage 12 + persona-id 정합 게이트). Gemini 는 Vertex AI global endpoint only. 인증은 service account JSON (AWS Secret) → `GOOGLE_APPLICATION_CREDENTIALS` ADC.

---

## 4. 데이터 흐름

```
외부 클라이언트
    │ 모든 REST + WebSocket (단일 게이트웨이)
    ▼
100 Nexus (:59100) ────────────────────────────────────────────────────────────
    │ info / auth / account / works / phase / thread / estimate / output / media + client WS
    │ 쿠키(access/refresh) 발급·검증·회전·PKCE, ws_manager(client WS 레지스트리·seq·replay), event_mapper(persona→channel),
    │ ws_inbound(message.send 단일·멱등 correlation_id, strict), message_flow(user turn write + chain spawn)
    │   → CM 직접 호출 (CM_URL) + DRO 내부 호출
    │
    │  control: POST /control/spawn {user_id,work_id,persona,pipeline_id,chain_id} → 202
    │  event:   GET /events/... (per-session SSE, RAW event) — event_consumer 가 소비 → WS push
    ▼
200 DRO (:59200, internal only) ────────────────────────────────────────────────
    │ 1. spawn 수신 → run_chain: entry chain 생성 + RT 큐 push (producer) + (session,persona) worker 깨움
    │ 2. (session,persona) 단일 worker 가 RT 큐를 chain-at-a-time 소비 (같은 persona chain 직렬; 다른 persona=다른 worker=병렬)
    │ 3. pipeline 의 step 순회
    │    · LLM step (`instructions` 키): RT 생성 → 페르소나 큐 push → pop → Actor /dispatch (SSE)
    │      ↳ Actor 의 composer 가 RT.input 의 cascading 결과를 single-text prompt 로 합성
    │      ↳ SDK 호출 → agent_state PUT (CM) → RT output PATCH → SSE result
    │    · tool step (`tool` 키): DRO 가 직접 Actor `POST /tool/{name}` 호출 (LLM 없음)
    │    · step list nesting (`[s1, s2, s3]`): asyncio.gather 정적 병렬
    │ 4. 마지막 step 의 output 의 `dispatch_choice` (integer enum) → `dispatch_to.actions[choice]` 의 pipeline_id 들이 next chain (spawned)
    │ 5. 각 spawned chain 마다 새 chain_id + 새 agent_state. run_chain 으로 그 persona 큐에 enqueue + worker 깨움 (핸드오프 — 같은 persona 면 이 worker 의 다음 loop, 다른 persona 면 그 worker)
    │ 6. chain 종료 → DRO 가 RAW event 를 per-session SSE 로 emit
    └── (RAW event SSE) → Nexus event_consumer → event_mapper → WS push (envelope v2, port 59100)
            → message.received / work.progress (`channel:support|analysis|…`) / message.reply / work.failed
            → model.maturity / model.roadmap   (model.* 는 Nexus 가 chain 완료 시 CM fetch 로 생성 — DRO 미발사, #12)
            → output.ready   (DRO 가 control/output docx 빌드 완료 시 RAW output_ready 발사 → event_mapper 매핑, C6 — chain 흐름과 별개 단발 경로)
            → system.resync_required / system.error   (heartbeat 는 native WS ping/pong — app-level system.ping/pong 없음)

300 Actor (모든 persona 공통 단일 코드베이스)
    │ POST /dispatch (SSE 스트림, body = {chain_id, rt_id, user_id, work_id, persona})
    │  └─ persona 슬롯 try-acquire (cap = engine.config max_concurrency, src/slots.py) → 포화 즉시 503+Retry-After → DRO 가 시간예산 backoff 재시도 (포화 ≠ 실패)
    │  └─ CM RT GET (body 의 persona dir 에서 직접) → agent_state load → composer (compose_prompt) → LLM SDK 호출
    │       └─ SDK 의 function calling (self-chain `fetch_*` allowlist 만)
    │  └─ agent_state PUT → RT output PATCH → SSE result
    │ POST /tool/{name} (DRO direct, LLM 없음)
    │  └─ tool registry handler 호출 (kipris / drawing / vision / document)

400 CM
    │ /sessions/{u}/{i}/* — manifest.context + models + drawings + outputs
    │ /sessions/{u}/{i}/runtime/* — DRC endpoints (00.dro + 페르소나 sub-folder + chain 자료)
    │ 모든 write 는 file_key 단위 asyncio.Lock 으로 직렬화
```

**Actor 끼리 직접 통신 안함.** cross-persona 협력은 (a) Nexus 의 user-driven spawn (예: 사용자 메시지 → P01.R00 + P02.R00 평행 — Nexus 가 결정·forward, DRO 가 admission dedup 후 실행) 또는 (b) chain dispatch graph (자기 chain 이 끝나면서 다음 페르소나 chain trigger, 예: P02 → P05 도면 작업) 로만. **P01 같은 응대 페르소나의 chain 은 self-contained — 다른 페르소나로 dispatch 하지 않음** (응대 결과는 conversation.json 으로만 누적, 다른 페르소나가 알아서 소비).

**Admission 코얼레싱 (D-1, C3)** — 연속(빠른) 메시지가 같은 분석(P02)을 동시 다발로 띄우면 산출물 lost-update 가 발생할 수 있어 admission 으로 합침. **합치는 건 메시지가 아니라 동일 chain spawn** — Nexus 는 항상 forward(상태 0)·conversation append, DRO 가 `run_chain` 진입에서 `(user_id, work_id, persona, pipeline_id)` 4-tuple 로 **완전 대기중(status=pending, 한 칸도 실행 전)인 동일 건이 있으면 그 spawn 을 버림**(대기건이 자기 차례에 최신 conversation 으로 한 번에 판단 — 메시지는 conversation append-only 라 유실 아님). → (session,persona) 당 실행중 ≤1 + 대기 ≤1. 버린 spawn 은 무신호(RAW 0)+흡수 chain trail 1줄. 상태=CM/S3·판정=DRO(in-process admission 잠금). dispatch_to 후속도 같은 경로(pipeline_id 다르면 평상시 no-op).
**Actor 는 CM 만 호출** (RT read/agent_state read-write/trail append/composer 의 cm:// fetch). DRO 는 호출 안함.

---

## 5. S3 Storage 구조 (P-A v3)

**단일 truth source**: `shared/venezia_memory/scaffolding.yaml` (YAML 트리). 모든 컴포넌트는 `venezia_memory` 의 key builder 함수만 사용 (직접 literal 금지).

```
s3://venezia-bucket/sessions/{user_uuid}/{invention_uuid}/
├── manifest.context.yaml             # 세션 정체성·status·current_phase
│
├── runtime/                          # 모든 런타임 + 페르소나 누적 + DRO 자료
│   ├── manifest.runtime.yaml         # chain 인덱스 (페르소나 무관 root)
│   │
│   ├── 00.dro/                       # DRO 자체 자료 (페르소나 X, queue/chain 없음)
│   │   └── conversation.json         # 사용자-시스템 대화 누적 (user turn = Nexus message_flow, assistant turn = P01 save tool)
│   │
│   ├── 01.buddy/                     # P01 Buddy
│   │   ├── queue.json                # RT 큐 ((session,persona) worker 가 chain-at-a-time 소비)
│   │   └── {chain_id}/
│   │       ├── manifest.json         # chain 메타
│   │       ├── trail.jsonl           # 이벤트 로그
│   │       ├── rts/{rt_id}.json
│   │       └── agent_state.json
│   │
│   ├── 02.director/                  # P02 Director (누적 dialog 다수)
│   │   ├── queue.json
│   │   ├── analysis.json decisions.json evaluation.json workspace.json
│   │   └── {chain_id}/...
│   │
│   ├── 03.finder/                    # P03 Finder
│   │   ├── queue.json
│   │   ├── research.json rejection-cases.json
│   │   └── {chain_id}/...
│   │
│   ├── 04.thinker/                   # P04 Thinker (누적 dialog 없음, chain 자료만)
│   │   ├── queue.json
│   │   └── {chain_id}/...
│   │
│   ├── 05.crafter/                   # P05 Crafter
│   │   ├── queue.json
│   │   └── {chain_id}/...
│   │
│   └── 06.inspector/                 # P06 Inspector (도면 검수)
│       ├── queue.json
│       ├── evaluation.json           # P02 의 evaluation 과 별개 schema
│       └── {chain_id}/...
│
├── models/                           # AI 산출 (정량 모델)
│   ├── manifest.models.yaml
│   ├── invention-object-model.json   # IOM (writer: P02, 구체화 단계엔 read-only)
│   ├── concept-maturity-model.json   # CMM (writer: P02 via maturity.compute tool)
│   ├── concept-discovery-stack.json  # CDS (writer: P02 via staging.save tool — 모델 아님, 사용자 말 7 필드 누적)
│   └── user-roadmap.json             # UR (writer: P02 via roadmap.persist tool — top-level JSON array)
│
├── drawings/                         # AI 산출 도면
│   ├── manifest.drawing.yaml
│   └── {drawing_id}/{numerals,dl,figure}.json
│
├── outputs/                          # 최종 산출물
│   ├── manifest.outputs.yaml
│   └── draft.docx                    # writer: DRO POST /control/output (docx_generator.py, C6 배선됨). Nexus output/draft 표면 → DRO 위임
│
└── media/                            # 사용자 업로드 (work 레벨, presigned S3 직접 — 메시지/chain 무관, 장부 없음)
    └── {media_id}.{ext}              # 브라우저가 presigned POST 로 S3 직접 업로드. writer: 브라우저
```

**핵심 원칙**:
- **RT 큐 — chain-at-a-time 소비**: RT 큐는 (session,persona) 단일 worker 가 *chain-at-a-time* 소비 (같은 persona chain 직렬; 다른 persona·다른 session 은 병렬). 파이프라인 쌓아두지 않음 — producer(`run_chain`)가 spawn 시 RT 들 큐로 push, worker 가 깨어 소비.
- **conversation 의 writer 는 분담** — user turn 은 Nexus `message_flow`, assistant turn 은 P01 chain 의 save tool step. 둘 다 `00.dro/conversation.json` 에 영속 (multimodal 입력 포함).
- **chain 자료는 페르소나 sub-folder 안** — `runtime/{persona}/{chain_id}/...`. CM 의 모든 chain 함수 시그니쳐에 `persona` 인자.
- **race 자료는 file-key asyncio.Lock** (`400.CM/src/lock.py`) — 같은 persona chain 은 단일 worker 가 직렬화하나, 병렬 step fan-out(`asyncio.gather`)·다른 session 의 같은 persona 는 동시 RT 가 가능 → CM write race 를 Lock 으로 처리.

---

## 6. Pipeline 포맷 P{NN}

### 6.1 파일명

`P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json` — **파일명 = source of truth**. 내부 `pipeline_id` 필드는 허용 안 됨 — `_assert_no_legacy_keys` 가 발견 시 RuntimeError. `pipeline_walker._index()` 가 `@pipelines/` 디렉토리 재귀 스캔 시 non-P{NN} 파일 발견하면 RuntimeError.

- **P{NN}** — Persona 번호 (01~06)
- **R{NN}** — Role 번호 (R00 = entry, R10~ = sub 흐름)
- **{UPPER_SNAKE}** — 의미 이름 (대문자 + underscore)

### 6.2 4-layer Cascading

각 step 의 `inject_context` / `recommended_context` / `fragments` / `llm_tools` 가 4 layer 머지:

```
GLOBAL.json (@pipelines/_shared/)
  → P{NN}.COMMON.json (persona 별)
    → pipeline.common (pipeline 최상위)
      → step
```

같은 name + 같은 source 가 두 layer 에 중복되면 validator error. 다른 source 면 OK. 머지 구현은 `shared/venezia_pipeline_runtime/loader.py:load_pipeline_cascaded`.

### 6.3 step 타입 (단 2종)

| step | 조건 | 동작 |
|------|------|------|
| LLM step | `instructions` 키 존재 (객체) | composer 가 prompt 합성 → Actor SDK 호출 |
| tool step | `tool` 키 존재 | DRO 직접 `POST /tool/{name}` (LLM 없음). **tool 도 RT** — rt_id·기록·`rt_*` 이벤트가 LLM step 과 동일 (tool=RT 통일, N-7) |

둘 다 없거나 둘 다 있으면 `orchestrator._run_one_step` 가 `RuntimeError`.

**`instructions` 객체 형태** — `inline` (string) **XOR** `reference` (string, `@pipelines/.../*.md` path) 중 정확히 1개. 거의 모든 LLM step 은 `reference` 사용 — pipeline.json 옆 체인 디렉토리 (`@pipelines/{NN}.{persona}/P{NN}.R{NN}/{step_slug}.md`) 에 표준 markdown 으로 분리. composer 가 Actor 측에서 read (`@pipelines/` prefix → `_resolve_instructions_reference` + lru_cache) → prompt 의 `[TASK]` 섹션에 markdown 그대로 dump. `instructions` 의 `list[str]` / `string` 형식은 허용 안 됨 — 발견 시 `loader._validate_step_instructions` + `pipeline_walker._assert_no_legacy_instructions` 가 fail-loud.

### 6.4 list nesting = 정적 병렬

```json
"steps": [s0, [s1, s2, s3], s4]
```

nested list 안의 step 들은 `asyncio.gather` 로 동시 실행 (정적 fan-out group). 같은 persona 의 LLM step 들이라면 같은 chain 의 agent_state 를 공유 — race condition 가능성은 step 단위 작업 크기에서 낮음. **dormant 아니라 활성** — P02.R00.CONCEPT_MATURITY 의 채점 step 2/3/4 (`score_clarity` / `score_completeness` / `score_potential`) 가 정적 병렬 묶음 (독립 채점 동시; Actor P02 cap=2 라 2씩, D-6). validate stage 15 가 이 묶음 형태를 검증.

### 6.5 chain dispatch graph

마지막 step (또는 list nesting 의 마지막 group 의 마지막 step) 의 `output_contract` schema 에 `dispatch_choice` (integer enum) 필드가 있으면 그 값이 인덱스. `dispatch_to.actions[dispatch_choice]` 의 pipeline_id list 가 다음 chain 들 (병렬 spawn).

```json
"dispatch_to": {
  "actions": [
    [],                                          // choice=0 → exit
    ["P03.R00.PRIOR_ART_SEARCH_ANALYZE"],        // choice=1 → 1 chain
    ["P02.R10.DIRECTOR_GAP_ANALYSIS",
     "P02.R11.PATENT_EVALUATION"]                // choice=2 → 2 chains
  ],
  "max_self_recursion": 3                        // optional, self-recursion 가드
}
```

- `dispatch_to: null` 또는 빈 actions = chain 그래프 종료 (exit).
- self-recursion 가능 (`max_self_recursion` 가드) — 같은 pipeline 자기 호출.
- cross-persona 호출은 **dispatch_to 그래프로만**. Actor 끼리 직접 통신 금지.

resolve 구현: `200.DRO/src/dispatch_resolver.py:resolve_dispatch` (DRO 단독 소비).

### 6.6 llm_tools — self-chain allowlist

LLM step 의 SDK function calling 에 등록 가능한 tool 은 다음 7개 allowlist 만:

```
fetch_dialog, fetch_step_output, fetch_drawing,
list_drawings, fetch_outputs, fetch_conversation
```

cross-persona 도구 (예: `kipris.search_patents` 가 P02 의 llm_tools 에 들어가는 경우 등) 는 **금지**. 발견 시 `pipeline_walker._assert_no_cross_persona_tools` 가 RuntimeError. cross-persona 호출은 dispatch_to 그래프로만.

### 6.7 허용 안 되는 키

`pipeline_walker._assert_no_legacy_keys` 가 raw JSON 파일 로드 직후 검사. 발견 시 RuntimeError:

- top-level: `pipeline_id`, `version`, `$schema`, `entry`, `metadata`, `error_handling`
- step: `type`, `id`, `next`, `system_prompt`, `input`, `priority_context_references`, `available_tools`, `output_schema`, `context_manager_reads`, `mode`, `over`, `item_var`, `task`, `tasks`, `bind_results`, `timeout_per_item`, `on_error`, `branches`, `service`, `action`, `calls`, `response_map`, `sub_pipeline`

step.type 5종 + 분기/루프 메커니즘은 chain dispatch graph + step list nesting 으로 표현.

---

## 7. Composer (Actor 의 single-text prompt 합성)

Actor `300.Actor/src/dispatcher.py` 가 RT 의 input 받으면 `300.Actor/src/composer.py:compose_prompt` 호출 (Actor 단독 소비):

```
single_prompt = compose_prompt(
    persona_prompt=rt_input["persona_prompt"],
    inject_context=rt_input["inject_context_spec"],        # cm://invention_object_model, cm://concept_discovery_stack, cm://concept_maturity_model, cm://conversation, cm://user_roadmap, cm://dialogs/<persona_int>.<name>, @knowledge/<key>
    recommended_context=rt_input["recommended_context_spec"],
    fragments=rt_input["fragments"],                       # 4-layer cascading 결과
    instructions=rt_input["instructions"],                 # {inline: ...} XOR {reference: "@pipelines/.../*.md"}
    dispatch_choice_guide=rt_input["dispatch_choice_guide"],  # 마지막 step 이면 dispatch_choice 의 enum 의미 설명
    knowledge_root=Path("/app/@knowledge"),
    pipelines_root=Path("/pipelines"),                     # instructions.reference resolve 용
    cm_fetch=async_cm_fetch_resolver,
)
```

`cm://` 경로 resolve (P-E: RFC 6901 JSON Pointer 표준) — `cm://<resource>` (root 전체) 또는 `cm://<resource>/sub/path` (RFC 6901 slash pointer). 지원 resource: `invention_object_model` / `concept_discovery_stack` / `concept_maturity_model` / `conversation` / `user_roadmap` / `dialogs/<persona_int>.<name>[.json]` (단축 표기, 실제 path `runtime/<persona_dir>/dialog/<name>.json`). 모든 부분 read 는 서버측 `?pointer=/path` query 로 forward (client-side walk 코드 자체 없음, validate stage 6 가 dot-path 발견 시 fail). `@knowledge/` resolve — 정적 자산. `@pipelines/` resolve — `instructions.reference` 의 MD 파일 read (lru_cache).

RT.input.prompt 와 system_prompt 는 **항상 빈 문자열**. composer 가 합성한 single-text 만 SDK 에 전달.

---

## 8. Fail-loud 정책 (5 위치)

| 위치 | 검사 | 위반 시 |
|------|------|---------|
| `200.DRO/src/pipeline_walker.py:_index()` | non-P{NN} 파일명 (`@pipelines/**/*.pipeline.json` 중 패턴 불일치) | `RuntimeError` |
| `pipeline_walker._assert_no_legacy_keys(raw, file)` | 파일 raw JSON 의 legacy key (§6.7) | `RuntimeError` (file path + key 명시) |
| `pipeline_walker._assert_no_cross_persona_tools(cascaded, file)` | cascading 결과의 `effective_llm_tools` 에 self-chain 외 도구 | `RuntimeError` (도구명 + step idx + allowlist) |
| `200.DRO/src/orchestrator.py:_run_one_step` | step 이 `instructions` / `tool` 둘 다 없거나 둘 다 있음 | `RuntimeError` |
| `300.Actor/src/dispatcher.py:handle` | RT.input 에 composer 키 (`inject_context_spec` / `persona_prompt`) 둘 다 없음 | `RuntimeError` |

unit test: `tests/invoke/invoke/suites/dro/test_pipeline_walker.py::test_pipeline_walker_rejects_legacy_keys` + `test_pipeline_walker_rejects_cross_persona_tool`.

**런타임 fail-loud + 자동복구 (C2)** — 위 5 위치는 *정적·구조* 검사. 런타임 실행 실패는 `worker._drive_chain` 이 일괄 처리:
- **A-5**: chain 진입(get_chain/persona 검증/active patch) 포함 **모든 실패가 chain=failed + 내부 `error` RAW**. `_drain_chain_pending` 이 잔여 RT 도 failed 마킹.
- **A-6**: dispatch 분기 실패는 done 위장하지 않고 chain=failed. 단 **dispatch_choice 는 output_contract 의 required·정수·[0,len-1] enum 으로 SoT 강제**(validate stage 3) → LLM 이 범위 밖을 못 내므로 분기 실패는 *발생 불가화*(핸들링이 아니라 제거).
- **A-3 자동복구**: DRO 재시작 시 `worker.resume_active_chains` 가 CM `GET /admin/active-chains`(전 세션 미완 chain 스캔)로 끊긴 chain 을 찾아 재개 — 완료(done) step 은 CM 레코드로 복원해 skip, 안 끝난 step 은 무조건 재실행. 사용자 무활동에도 자동 완주 ("무조건 동작").
- **사용자 표면**: 내부는 fail-loud(진실 기록), 사용자에겐 실패 비노출 — 자동복구 또는 "재시도 중" 류 부드러운 텍스트(Nexus event_mapper 의 config 선언, C4). DRO 는 내부 `error` RAW 까지.

---

## 9. RT lifecycle

### 9.1 사전 push (관측성)

`orchestrator._enqueue_all_rts` 가 chain 진행 시작 전 **모든 step(LLM·tool)의 RT** 를 persona queue 에 push (tool=RT 통일, N-7 — tool step 도 rt_id·`rts/{rt_id}.json` 기록·`rt_enqueued/started/result` 이벤트가 LLM 과 동일). trail 에 `rt_enqueued` event 기록 + DRO 가 RAW `rt_enqueued` 를 per-session SSE 로 emit. Nexus 의 `event_mapper.handle_raw_event` 가 `rt_*` RAW event 를 `work.progress` (channel 라벨 포함 — **모든 RT 시작 시** 발생) 로 매핑해 client WS 로 push. (진행 루트 ⊥ 답장 루트 — tool RT 진행 이벤트는 `message.reply` 와 무관. `message.reply` 는 Nexus 가 P01 chain 완료 시 CM conversation 최신 assistant turn snapshot으로 생성하며 admission coalescing 시 inbound message와 1:1이 아니다.)

### 9.2 step 순회

```python
for step in steps:
    if isinstance(step, list):  # 정적 병렬 group
        await asyncio.gather(*[_run_one_step(sub) for sub in step])
    else:
        await _run_one_step(step)
```

`_run_one_step`:
- `instructions` 키: `_dispatch_llm_step` → persona queue pop (mismatch 시 새 RT 생성) → Actor `/dispatch` → output 받음
- `tool` 키: `_exec_tool_call` → `substitute_placeholders(step.params, context)` → Actor `/tool/{name}` 직접 호출

step 결과는 `context["steps"][step.id] = output` 으로 저장. step.id 는 `_coerce_to_orchestrator` 가 자동 부여 (str(idx) — "0", "1", "2", ...).

### 9.3 placeholder 치환

dot-notation only. bracket indexing 미지원. 구현: `200.DRO/src/branch_evaluator.py:substitute_placeholders` + `_resolve`.

지원 경로:
- `$.inputs.{user_id,work_id,chain_id}` — orchestrator 가 항상 박는 시스템 메타 (그 외 키 금지)
- `$.steps.<id>.<key>` — 같은 chain 의 이전 step output
- `$.parent_outputs.<parent_step_id>.<key>` — spawn 된 chain 에서 부모 chain 의 step output 참조
- `$.user_input.<key>` — spawn trigger 의 사용자 payload (`POST /control/spawn` body `trigger.user_input`. 현행 Nexus message_flow 는 trigger 최소화 — 내용은 CM conversation 으로 전달)
- `$.<inject_name>.<path>` — tool step 의 `inject_context` 가 cm:// 로 사전 fetch 한 데이터

### 9.4 dispatch 마무리

chain 의 마지막 step 끝나면 `resolve_dispatch(pipeline_id, dispatch_to, last_step_output, ancestor_pipeline_ids)` 호출 → next pipeline_id list. 각각 새 chain spawn = `run_chain` facade 호출 (`create_chain` + producer RT enqueue + 그 persona worker 깨움 — 인라인 실행 X, 핸드오프). next chain 의 trigger 에는 (a) `spawned_from`(parent chain_id), (b) `parent_outputs`(부모 `context["steps"]` 통째), (c) `ancestor_pipeline_ids` 가 박힘 — child 는 `$.parent_outputs.*` placeholder 로 부모 step output 접근. `max_self_recursion` 가드는 ancestor 가 사용.

---

## 10. 외부 REST Endpoints + WebSocket Events

> 표준 명세는 `.docs/Architectures/external_api/{openapi.nexus.json, asyncapi.yaml}` (Step 4). 외부 OpenAPI spec 은 Nexus 단독 (`openapi.nexus.json`) — DRO 가 client REST 를 서빙하지 않으므로 DRO OpenAPI spec 은 없음. asyncapi servers/host = Nexus (host `nexus`, port 59100). 본 §10 은 요약 + reference.

### 10.1 외부 REST 표면 = Nexus 단독 — info/user/works/phase/thread/estimate/media

> work_id = 세션/작업 식별자 (외부·내부 단일 명칭). user_id ⊥ JWT, AUTH_MODE(OPEN|SECURE). proposal·결제게이트 = placeholder. **모든 client-facing REST 는 Nexus `:59100` 단독** — DRO 는 client REST 를 서빙하지 않는다 (내부 `POST /control/spawn` + `POST /control/output` + `GET /events/...` SSE 뿐). Nexus output/draft 라우트가 docx 빌드를 DRO `POST /control/output` 으로 위임 (C6).

| 컨테이너 | 묶음 | Path |
|---|---|---|
| Nexus `:59100` | info | `GET /api/v1/info/{providers,attributions}` |
| Nexus | auth | `GET /api/v1/user/auth/{provider}/{authorize,callback}` · `POST .../connect` · `DELETE /api/v1/user/auth/{provider}` · `POST /api/v1/user/auth/refresh`(회전) · `POST /api/v1/user/auth/logout` |
| Nexus | account | `GET /api/v1/user/account` · `GET·PUT /api/v1/user/account/alias` |
| Nexus | works(컬렉션) | `POST /api/v1/user/works`(생성·**201**+`Location`) · `GET /api/v1/user/works`(목록) |
| Nexus | works(진입) | `GET /api/v1/works/{work_id}` (가벼운 진입 {work_id,title}; 하위 자원=고정 URL 템플릿, A-9) |
| Nexus | works/meta | `GET·PATCH /api/v1/works/{work_id}/meta` |
| Nexus | phase | `GET·PATCH .../phase` (PATCH=무본문 전이, 서버가 로직 보유) |
| Nexus | thread | `GET .../thread/messages` · `WS .../thread/stream` (쿠키 인증) |
| Nexus | estimate | `GET .../estimate/roadmap` · `PATCH .../estimate/roadmap/{item_id}`(답변) · `GET .../estimate/maturity` |
| Nexus | output | `POST .../output/draft`(현재 IOM→DOCX 동기 변환, 200) · `GET .../output/draft`(다운로드·결제게이트) · `GET .../output/draft/preview` · proposal/* = **501 placeholder** |
| Nexus | media | `POST .../media`(업로드 티켓·**201**+`Location`) · `GET .../media`(목록) · `GET .../media/{media_id}`(메타+다운로드 URL) · `DELETE .../media/{media_id}` (presigned S3 직접 — 바이트 서버 미경유, work 레벨·메시지 무관) |
| DRO `:59200` (internal only) | control / event | `POST /control/spawn {user_id,work_id,persona,pipeline_id,chain_id}` → 202 · `POST /control/output {user_id,work_id,variant}` → 200 `{document_id,filename,size_bytes}` (IOM→DOCX) · `GET /events/{user_id}/{work_id}` (per-session SSE) · `GET /health` |

WS URL = `nexus:59100/api/v1/works/{work_id}/thread/stream?since_seq=N` (스킴 `ws` — 내부망, 외부 표면은 `wss` 종단). 인증 = httpOnly 쿠키 `nx_access` 가 handshake 에 자동 첨부 (OPEN 이면 토큰 없이 고정 user_id). user_id 는 경로에 없음 — 서버가 쿠키에서 해석. 수명 = 12h 캡 단독(짧은 access 가 WS 조기 종료 안 함) — cap 도달 시 close 1001(going-away), 인증 실패 4401·없는 work 4404.

> dev/test pipeline trigger 는 DRO `POST /control/spawn` 직접 호출.

### 10.2 WebSocket 채널 (Nexus client WS 단일 채널)

**client 채널** (Nexus port `59100`, envelope v2 — `{type, timestamp, seq, data}`, scope/subject_id 없음, 외부 client). WS routing 은 `(user_id, work_id)` WS-key broadcast. 모든 type 은 `<domain>.<event>` 네임스페이스(bare 금지). 페이로드에 task_id 없음:

9종. 이벤트는 **best-effort 알림** — 진실은 CM, client refresh 로 복구 (#15):

| Type | Data 핵심 | 라우팅 |
|---|---|---|
| `message.received` | `{correlation_id, id}` (acceptance ack — correlation_id echo + 저장된 user turn 메시지 id; in_flight 재-ack 면 id=null; 후속 chain 완료 보장 아님) | 송신 소켓 unicast |
| `message.reply` | `{id, text}` (P01 chain 완료 시 최신 assistant turn 메시지 id+snapshot; admission coalescing 시 inbound와 1:1 아님 — correlation_id 안 실음) | broadcast |
| `work.progress` | `{display_status:{ko,en?}, channel, phase?}` (**모든 RT 시작 시**) | broadcast |
| `work.failed` | `{message, channel?}` (work 처리 실패 — 사용자 안전 메시지, 메타 비식별) | broadcast |
| `model.maturity` | `{overall_score, scores:{clarity,completeness,potential}, weights?}` — Nexus 가 chain_completed[persona=2] 시 CM 에서 CMM fetch (**DRO 미발사**, #12) | broadcast |
| `model.roadmap` | `{count}` (client 가 GET /roadmap 재조회) — Nexus 가 chain_completed[persona=2] 시 CM 에서 UR fetch (**DRO 미발사**, #12) | broadcast |
| `output.ready` | `{document_id, filename, size_bytes, preview_url?, download_url?}` | broadcast |
| `system.resync_required` | `{reason}` — replay buffer evict / 빈 버퍼 재연결 / seq reset 시 | 해당 소켓 |
| `system.error` | `{code(ErrorCode), message}` — 잘못된 inbound 프레임 | 송신 소켓 unicast |

**inbound action** (client WS, **1종**, strict 검증): `message.send` (`{content, correlation_id}`). `correlation_id` = 클라 생성 멱등키(메시지당 고유) — 재시도는 같은 값으로 재send 하면 서버가 멱등 dedup(새 turn/spawn 0, 원결과 재-ack). 같은 id·다른 content = `system.error(conflict)`. 범위 = work. (별도 `message.resend` 액션 없음.) 위반(잉여 키·미지 action·data 비-object) → `system.error(validation_failed, ErrorCode)`. media 는 work-level REST 자원으로 메시지 payload와 독립.

**메시지 id** = work 내 0-based 위치(시퀀스) — conversation 은 append-only 라 위치가 안정 커서. 저장하지 않고 API/WS 경계에서 파생(마이그레이션 0). `GET …/thread/messages` 페이징 커서 `before=<message_id>`, history item·`message.received.id`·`message.reply.id` 동일 어휘.

**`work.progress.data.channel` 6 라벨** (메타 AI 비식별): `support` (P1) · `analysis` (P2) · `research` (P3) · `thinking` (P4) · `drafting` (P5) · `review` (P6). 매핑은 `shared/venezia_contracts/models/dro_api/channels.py:PERSONA_TO_CHANNEL` 한 곳 — Nexus `event_mapper` 가 DRO RAW event 를 받아 적용.

**내부 RAW event** (DRO → Nexus per-session SSE, 외부 비노출):
`rt_enqueued / rt_started / rt_progress / rt_result / rt_error / chain_completed / output_ready / error`.
Nexus event_mapper 가 client envelope v2 로 변환 (`rt_started` → `work.progress`,
chain_completed[persona=1] → `message.reply`, chain_completed[persona=2] → CM fetch 로
`model.maturity`/`model.roadmap`, `rt_error`/`error` → `work.failed`, `output_ready` → `output.ready`).

**heartbeat / replay**: heartbeat = native WebSocket ping/pong (uvicorn keepalive) — app-level `system.ping/pong` 없음. ring buffer maxlen 200 per `(user_id, work_id)` (Nexus ws_manager). `since_seq>0`이면 seq>N replay를 시도한다. 마지막 connection 해제 시 key를 GC하므로 단일 connection 재접속은 보통 빈 버퍼 resync다. evict·빈 버퍼·seq reset 시 `system.resync_required`.

**존재하지 않는 event/필드**: `message.delta` · `iom.updated` · `account.updated` · `settings.updated` · `system.ping`/`system.pong`(native 사용) · 모든 event 의 `task_id`·`scope`·`subject_id` 필드 (websocket-events.json + asyncapi.yaml 기준).

스키마: `@contracts/00.dro/websocket-events.json` + `.docs/Architectures/external_api/asyncapi.yaml` (AsyncAPI 3.0, servers/host = Nexus `nexus:59100`). 구체화 단계 흐름 reference: `../Features/CONCEPT_MATURITY_FLOW.md`.

---

## 11. CM Endpoints (400.CM)

76 endpoint (400.CM/src/router.py 의 `@router.*` decorator 기준 — `users/idempotency` 4종[get/put/claim/delete], `users/refresh-tokens` 3종[put/rotate/revoke]+identity delete[C1] 포함). 핵심 그룹:

- `/sessions/{u}/{i}/runtime` (POST = 신규 chain, GET = chain 인덱스)
- `/sessions/{u}/{i}/runtime/00.dro/conversation` (GET) + `.../append` (POST)
- `/sessions/{u}/{i}/runtime/{persona}/queue` (GET / push / pop(+lease_ttl_s) / release(rt_id)) — 장부 = `pending[] + leases{rt_id}` (rt_id 별 lease, 만료 lazy 제거)
- `/sessions/{u}/{i}/runtime/{persona}/dialog/{name}` (GET/PUT/PATCH, 페르소나 누적 dialog)
- `/sessions/{u}/{i}/runtime/{persona}/{chain_id}` (GET/PATCH)
- `/sessions/{u}/{i}/runtime/{persona}/{chain_id}/trail` (GET / POST append)
- `/sessions/{u}/{i}/runtime/{persona}/{chain_id}/rts` (POST 생성)
- `/sessions/{u}/{i}/runtime/{persona}/{chain_id}/rts/{rt_id}` (GET/PATCH)
- `/sessions/{u}/{i}/runtime/{persona}/{chain_id}/agent_state` (GET/PUT)
- `/sessions/{u}/{i}/media/presign-put` (POST) + `/media/presign-get` (POST) + `/media` (GET) + `/media/{media_id}` (DELETE) — presigned 발급·목록·삭제 (work 레벨)
- `users/identities/{provider}/{sub}` (GET/PUT) + `users/profiles/{u}/profile` (GET/PUT/PATCH, `updated_at` 스탬프) + `users/idempotency/{u}/{key_hash}` (GET/PUT/`claim`(POST)/DELETE — D6 멱등 영속, sessions 밖 user 루트)

모든 write 는 file_key 단위 `asyncio.Lock` 으로 직렬화 (`400.CM/src/lock.py`).

---

## 12. Tool Registry (Actor 공유)

`300.Actor/src/tools/` 페르소나 무관 공유 라이브러리. DRO direct (tool step) 또는 Actor SDK function calling 으로 호출.

**DRO tool step** 으로 호출되는 도구 — `POST /tool/{name}` 으로 DRO 가 직접 호출. LLM agent 의 native function calling tool (= `llm_tools`) 과는 별개. KIPRIS API 자체는 외부 데이터 소스이고, 그 wrapper 가 도구. KIPRIS RAG 는 chain dispatch graph 로 분해 (§13 참고).

| Category | Tool | 설명 | 호출처 |
|----------|------|------|------|
| kipris | `search_patents` | KIPRIS 검색 (queries list 병렬 호출) | P03.R01.step1 |
| kipris | `get_patent_detail` | KIPRIS 특허 상세 조회 | P03.R11.step1 |
| drawing | `render` | 도면 코드 (PlantUML / OpenSCAD / schemdraw) → 이미지 | P05.R10.step0 |
| cm | `save_drawing_artifacts` | 도면 artifacts (numerals / DL / figure) CM 저장 | P02.R13.step0 |
| knowledge | `load_rejections_section` | IPC 기준 거절 패턴 Section guide 로드 | P02.R10.step1 |
| media_classifier | `classify` | 멀티미디어 입력 분류 | P01.R00.step0 |
| media_processor | `image_describe` / `document_describe` / `audio_describe` | 멀티미디어 → 설명 | P01.R10/R20/R21.step0 |
| staging | `save` | CDS PUT (사용자 말 7 필드 누적, P-C) | P02.R00.step1 |
| maturity | `compute` | 가중 합산 + CMM PUT (DRO 미발사 — Nexus 가 chain 완료[persona=2] 시 CM 에서 CMM fetch 로 `model.maturity` 생성, #12) | P02.R00.step5 |
| roadmap | `persist` | UR top-level array PUT (DRO 미발사 — Nexus 가 chain 완료[persona=2] 시 CM 에서 UR fetch 로 `model.roadmap` 생성, #12) | P02.R00.step7 |
| cm | `append_conversation` | conversation assistant turn append (P01 save) | P01.R00.step2 |

llm_tools 의 self-chain `fetch_*` 7종은 위 tool registry 와 별도 (composer 가 inject_context 로 처리 + SDK function calling).

---

## 13. 예시: P03 prior_art_search chain graph

P03 Finder 의 KIPRIS RAG 흐름은 **3 chain graph** 으로 분리 (도구로 합쳐진 monolith 가 아니라 chain dispatch 로 분해). play 의 spawned chain BFS 가 3 chain 전체를 e2e 추적.

```
[P03.R00.PRIOR_ART_SEARCH_ANALYZE chain]
  step 0: analyze (LLM, gemini-3.1-pro-preview)
         output: invention_summary, technical_elements, search_queries,
                 ipc_codes, search_strategy, dispatch_choice=0
  ↓ dispatch_to.actions[0] = [P03.R01.SEARCH_AND_REFLECT]

[P03.R01.SEARCH_AND_REFLECT chain]
  step 0: query_plan (LLM) → queries: list × 15
  step 1: kipris.search_patents (tool step, DRO direct)
         params: {queries: $.steps.0.queries, max_results_per_query: 10}
  step 2: reflect (LLM)
         output: coverage_score, covered_elements, dispatch_choice (0=재시도, 1=진행)
  ↓ dispatch_to.actions[0] = [P03.R01.SEARCH_AND_REFLECT]  (self-recursion, max=3)
  ↓ dispatch_to.actions[1] = [P03.R02.POST_REFLECT]

[P03.R02.POST_REFLECT chain]
  step 0: dedupe_rank (LLM) → ranked_patents: list × 10
  step 1: claim_chart (LLM) → claim_elements 매핑
  step 2: synthesis (LLM)
         output: novelty_assessment, recommendations, confidence_score
  ↓ dispatch_to: { actions: [[]] }  (exit)
```

이 흐름이 play `make play P03.R00 SEED=tests/data/iom-samples/smart_beverage_detailed.json` (FIXTURE / PRODUCTION) 으로 e2e 검증.

---

## 14. 모드 (2 직교 knob)

stack 동작은 **2 직교 차원** 으로 결정 — 각 차원 자체 knob (`@deployment/knobs.yaml` profile, env 아님 — CHUNK 1b). 전체 knob 8종은 §14.3 note.

### 14.1 `ENGINE_MODE` (Nexus, pipeline 차원)

Nexus 가 사용자 메시지 인입 시 어떤 chain 을 spawn 할지.

| 값 | 설명 |
|----|------|
| `FULL` (default) | P01 (Buddy) + P02 (Director) 동시 spawn. 일반 운영 |
| `SMALLTALK` | P01 만 spawn (P02 director OFF). 응대 응답만 빠르게 테스트하는 dev 모드 |

코드: `ENGINE_MODE` 는 Nexus config — `message_flow` 가 검사 후 P02 spawn 여부 결정 (Nexus → DRO `POST /control/spawn`). DRO 는 ENGINE_MODE 를 읽거나 관리하지 않는다.

### 14.2 `LLM_MODE` (Actor, LLM 차원)

Actor 가 어떻게 LLM 호출.

| 값 | 설명 |
|----|------|
| `FIXTURE` (llm:fake) | `FIXTURE_PATH/{pipeline_id}/{step_id}.json` replay. LLM 만 mock, tool step (KIPRIS 등) 은 실 함수 호출 (kipris knob 별도). 로컬 dev 용 — knob default 는 real |
| `PRODUCTION` | 실 SDK 호출 (Claude / Gemini Vertex / OpenAI). EC2 IAM role 환경에서 동작 — AWS Secrets Manager 가 모든 credential 의 단일 source. secret 부재 시 `raise`. **이 dev 환경 자체가 EC2** 이므로 PRODUCTION 정상 사용 가능 |

다른 값은 `300.Actor/src/llm/__init__.py:create_session` 가 fail-loud. flow 인프라 테스트는 FIXTURE 가 더 정확.

### 14.3 Make 인터페이스

```
make deploy init [<knob> <value>...]   # profile 설정 (모드 = knob). 인자 없으면 default = PRODUCTION + SECURE
make up                                # profile 대로 풀 reset (positional 없음 — 모드는 profile 에서 read)
```

> **모드 = profile knob (env 아님)** — `@deployment/knobs.yaml`(committed 스키마) + `profile.stack.yaml`(gitignored, `make deploy` 가 씀)이 `/etc/deployment.yaml` 로 마운트되고 `venezia_deployment` 가 런타임 read → 각 config 의 auth/engine/llm. 모드는 env·`make up` positional 이 아니라 profile knob 으로만 제어. knob 8종: actor/dro/cm/nexus/llm/kipris=real|fake (dro:fake = tape player `tests/data/dro-tapes` — CHUNK 4 · kipris:fake = canned `tests/data/kipris-fixtures` — 3-C · cm/nexus fake = available:false) · auth=open|secure · engine=full|smalltalk. llm: real=PRODUCTION · fake=FIXTURE.

의미 있는 시나리오 (`make deploy init … && make up`):
- `init llm fake` — FULL + FIXTURE (운영 코드 + mock LLM 풀 검증). 로컬은 `auth open` 추가.
- `init engine smalltalk llm fake` — P01 만 + mock (응대 응답만 빠르게)
- `init` (default) — 실 운영: FULL + PRODUCTION + SECURE (EC2 IAM only)
- `init engine smalltalk` — 드문 (P01 만 + 실 LLM)

`/health` 노출 — Nexus = `auth_mode`, DRO·Actor = `llm_mode` (`engine_mode` 는 health 미노출). `make mode` 가 `@deployment/profile.stack.yaml` (SoT) 의 auth/engine/llm/kipris knob 을 직접 표시 — 현 stack 의 모드 즉시 확인.

### 14.4 직교성

두 knob 완전 독립:
- Nexus 는 ENGINE_MODE 만 영향 받음 (P02 spawn 여부). LLM_MODE 는 읽지 않음 (DRO 가 health 정보 노출용으로만 read)
- Actor 는 LLM_MODE 만 영향 받음 (FixtureSession vs 실 SDK)
- Nexus 와 Actor 가 별개 차원 → 새 차원 추가 시 새 knob (`@deployment/knobs.yaml` 1줄, enum 폭발 X)

**AWS 자격증명 — EC2 IAM role only.** compose.yaml 에 `AWS_ACCESS_KEY_ID` 등 host env pass-through 명시 없음 (의도적). 컨테이너 startup 시 `_check_aws_creds` 가 IMDS endpoint ping 으로 자격 확인. IMDS 없는 환경 (개인 노트북 등) 에서는 fail-loud. **현 dev 환경**: EC2 인스턴스 (IAM role `EC2-Instance-S3Full-SecretRO`, region `ap-northeast-2`) — PRODUCTION 모드 정상 동작.

---

## 15. 검증

### 정적 검증

```bash
make validate
```

검사 (15 stage 전수 — stage 1~6 은 pipeline 단위, stage 7~15 는 전역 1회: contracts meta-schema(7) · contracts extended(8) · external_api OpenAPI(9) · WS 정합(10) · dead schema(11) · infra config(12) · asyncapi(13) · coverage census(14) · 정적 병렬 묶음 형태(15)). pipeline 단위 핵심 규칙:
1. 파일명 `P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json`
2. common 의 layer 타입 (`inject_context`/`recommended_context`/`fragments` = dict, `llm_tools` = list)
3. step 의 layer 타입 동일
4. 해당 persona 의 `P{NN}.COMMON.json` 존재
5. `_shared/GLOBAL.json` 존재
6. 4-layer name+source 중복 conflict
7. `dispatch_to.actions` 길이 ↔ 마지막 step `output_contract.dispatch_choice.maximum` 일치
8. `step.output_contract` → `@contracts/<persona>/stages/<id>.schema.json` 파일 존재
9. `llm_tools` 의 각 도구가 self-chain allowlist 안
10. 허용 안 되는 키 발견 시 fail-loud

### 단위 + e2e 검증 (7 track)

```bash
make validate                                  # 정적 15 stage (pipeline schema·cross-ref·tool registry·contracts(전수)·OpenAPI/asyncapi(풀)·WS 정합·infra·census·정적 병렬 묶음 형태)
make lint                                      # 코드 자동수정+검사 (ruff --fix+format · mypy · bandit · pip-audit)
make invoke                                    # 스택 없는 로직 라인 99% 게이트 (5 suite: shared·cm·dro·actor·account)
make enact                                     # Actor 단일 RT 수행 격리 — 시나리오 5/5 게이트 (dispatch·context·tool·concurrency·errors) + 단건 모드
make play P03.R00 SEED=tests/data/iom-samples/smart_beverage_detailed.json   # P03 chain graph e2e
make play P02.R00 SEED=tests/data/iom-samples/smart_beverage_detailed.json   # P02 chain graph e2e
make play P02.R12 SEED=tests/data/iom-samples/smart_beverage_detailed.json   # 도면 chain graph e2e
make probe check <chain_id> INVENTION_ID=<id>  # 단일 chain 의 9 invariants 검증
make endpoint                                  # 외부 API 11 phase e2e
```

generic 인터페이스: 22개 모든 pipeline 을 `make play <P{NN}.R{NN}[.TITLE]>` 으로 동일하게 실행. prefix (`P03.R00`) 만 줘도 DRO 가 full ID 로 해석. dev/test pipeline trigger 는 DRO `POST /control/spawn` 직접 호출. P01 Buddy 는 R00 단일 chain (3 step: assess + compose + save), 응대원 역할에 맞게 최소화 + Gemini multimodal SDK 의 reasoning 능력 활용.

verify-chain invariants (`tests/probe/probe/commands/check.py` — 9개, 7~9 는 트레일 데이터 있을 때):
1. 모든 RT state=done
2. composer keys (`inject_context_spec` / `persona_prompt`) 존재
3. composer `prompt_chars > 0` (trail 부재 시 ⚠ warning — mock-actor 등)
4. `context.steps` 누적
5. `response_schema` wiring
6. placeholder substitution 완전성
7. fixture ⊂ real search (warning) · 8. tool params substitution · 9. search count ≤ max_results

play 가 chain dispatch graph 의 spawned chain 들도 BFS 로 추적 (`MAX_CHAINS=30`).

---

## 16. 핵심 데이터 원칙

1. **IOM 소유권**: 오직 P2 Director 만 IOM (`invention-object-model.json`) 을 쓴다. DRO·다른 페르소나·frontend 직접 수정 금지.
2. **사용자 입력 흐름**: 모든 입력 (채팅·구조화) → `runtime/00.dro/conversation.json` (user turn = Nexus message_flow, assistant turn = P01 save tool) → Director 판단 → IOM 반영. DRO·Nexus 모두 IOM 을 직접 patch 하지 않는다.
3. **AI 판단 우선**: 무엇을 IOM 에 쓸지는 Claude (Director) 가 결정. 사용자 입력은 raw 재료.
4. **1 RT = 1 작업단위** (LLM SDK 호출 **또는** tool 호출 — 모든 step 이 RT, tool=RT 통일 N-7).
5. **persona 별 동시성 cap**: Actor 는 persona 별 동시 요청 한도(engine.config `max_concurrency`)를 `src/slots.py` 세마포어로 집행 — `/tool` 은 별도 풀(`tools.max_concurrency`), kipris fan-out 은 `tools.kipris.max_concurrency`. 포화 즉시 503+`Retry-After` ≠ 실패 — DRO 가 시간예산(`DISPATCH_RETRY_BUDGET_S`) 안에서 지수 backoff(상한 `BUSY_BACKOFF_MAX_S`) 재시도 지속.
6. **(session,persona) 단일 worker — chain-at-a-time**: producer(`run_chain`)가 RT 들을 persona 큐에 push, (session,persona) 당 단일 worker 가 큐를 chain-at-a-time 소비 → 같은 persona 의 chain 직렬화 (다른 persona=다른 worker, 다른 session 도 병렬). 병렬 step fan-out(`asyncio.gather`)은 한 chain 안 동시 RT. race 자료는 file-key asyncio.Lock 으로 처리.
7. **cross-persona 협력**: Actor 끼리 직접 통신 금지. 두 형태만 — (a) Nexus 의 user-driven spawn (P01+P02 평행 — Nexus 결정·forward, DRO admission dedup 후 실행, D-7), (b) chain dispatch graph (P02→P05 등 자기 chain 이 다음 페르소나 trigger). 응대 페르소나(P01)의 chain 은 self-contained.
8. **fail-loud > silent**: 허용 안 되는 키 / 잘못된 입력 시 즉시 `RuntimeError`. fallback / skip / silent None 은 쓰지 않는다.
