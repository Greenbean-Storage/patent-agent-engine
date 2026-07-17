---
description: onboarding
applyTo: "**"
---

# Patent AI Agent Engine - Onboarding Guide (DRC)

프로젝트에 새로 합류한 사람(또는 컨텍스트)이 순서대로 따라가는 절차 가이드.

---

## 1. 문서 읽는 순서

```
.docs/Architectures/STATIC_BLOCK_ARCHITECTURE.md  ← 설계 의도 원본 (수정 금지)
.docs/Architectures/DRC_ARCHITECTURE.md           ← 현행 단일 진실 원천 (P{NN} chain dispatch graph)
.docs/Architectures/AGENT_SDK_DESIGN.md           ← Actor SDK 통합 (벤더 SDK ↔ composer ↔ agent_state)
.docs/Architectures/DIRECTION_PIPELINE_FLOW.md    ← P02 Director 의 비즈니스 흐름 다이어그램
.docs/Architectures/EXTERNAL_API.md               ← 외부 REST + WS contract (envelope v2)
.docs/Features/CONCEPT_MATURITY_FLOW.md           ← 구체화 단계 (P02.R00) 통합 reference — CDS/CMM/UR + roadmap 답변(REST)
.docs/Features/DRAWING_FLOW.md                    ← P02/P04/P05/P06 의 도면 chain graph
.docs/Verification/verification.md                ← 검증 도구 7 track 인벤토리 (validate/lint/invoke/probe/enact/play/endpoint)
.docs/Issues/DIRECTOR-R00-RESIDUALS.md            ← 구체화 단계 도입 후 알려진 잔재
.claude/rules/project.instructions.md             ← 아키텍처·원칙·기술스택 전체
.claude/rules/standard.instructions.md            ← 코딩/작업 규칙
.claude/rules/onboarding.instructions.md          ← 이 파일 (절차)
```

> 현행 설계는 위 표의 문서들 + 코드 베이스가 단일 진실 원천.

---

## 2. 핵심 개념 (DRC)

**DRC (Distributed Reasoning Chain)** — AI agent 의 사고 흐름을 외부 큐로 분해하는 아키텍처.
각 사고 단위(RT, Reasoning Task)는 큐에 적재되고, Actor 컨테이너는 로직 없는 수동 워커로
RT 를 단위 호출만 수행. 모든 상태는 S3 에 영속화.

**4 Units / 4 Containers / 6 Personas**:
- Nexus (100.Nexus, :59100) — mypage 영역 + **SOLE external gateway** (ALL client REST + client WebSocket + 쿠키 기반 인증). httpOnly access/refresh 토큰 발급·검증·회전 + logout + PKCE 단독. 소유: ws_manager · event_mapper · ws_inbound · message_flow · event_consumer · dro_client.
- DRO (200.DRO, :59200 SINGLE) — pure **INTERNAL chain executor**. 전 외부 표면 = {POST /control/spawn, POST /control/output(docx 빌드, C6), GET /events/{user_id}/{work_id} (SSE), GET /health}. client REST/WS/media/auth/debug-app 없음. keep: run_chain(producer/facade) · (session,persona) 단일 worker · step/RT/tool 실행.
- CM (400.CM, :59400) — Context Manager. S3 단일 writer
- Actor (300.Actor, :59300) — 수동 워커. unified 단일 컨테이너 — P1~P6 전 persona 수락 (수락 집합 = engine.config `personas`), persona 별 동시성 cap = `src/slots.py` 세마포어

**외부 REST 표면 — Nexus 단독**: Nexus 가 **client-facing 전부** 제공 (info/user/works·phase·thread·estimate(roadmap/CMM)·media·WS). DRO 는 client REST 0 — internal-only {POST /control/spawn, POST /control/output(docx 빌드, C6), GET /events/{user_id}/{work_id}, GET /health}. DRO 는 auth 없음 (internal-network trust). Nexus 가 JWT 발급·검증 단독.

**내부 채널 2종** — control = Nexus→DRO REST (`POST /control/spawn {user_id,work_id,persona,pipeline_id,chain_id}` → 202). event = DRO→Nexus per-session SSE (RAW events). Nexus 가 양쪽 dial.

**WS event 라우팅** — (user_id, work_id) WS-key broadcast. 봉투 `{type, timestamp, seq, data}`(scope/subject_id 없음, 모든 type 네임스페이스). `message.received/work.progress/message.reply` payload 에 task_id 없음. WS URL = `nexus:59100/api/v1/works/{work_id}/thread/stream` (스킴 = `ws` 내부망 / 외부 종단 `wss`). 이벤트는 best-effort 알림 (진실=CM, 누락 시 client refresh 로 복구, #15).

**WS `work.progress.data.channel` 6 라벨**: P1→support · P2→analysis · P3→research · P4→thinking · P5→drafting · P6→review. 매핑은 `shared/venezia_contracts/models/dro_api/channels.py` 의 `PERSONA_TO_CHANNEL` 한 곳. persona→channel + display_status 변환은 **Nexus event_mapper** 가 RAW event 를 client WS event 로 매핑하며 수행. 메타 5 — AI/LLM/persona/buddy/director 명 외부 노출 금지.

**KIPRIS** — 한국특허정보원 (외부 특허 API · 데이터 소스). 그 API 를 호출하는 wrapper (`kipris.search_patents`, `kipris.get_patent_detail`) 는 **DRO tool step** — `300.Actor/src/tools/kipris/` 의 `@register("kipris.*")` 로 등록되어 `POST /tool/{name}` 으로 DRO 가 직접 호출. LLM agent 의 native function calling tool (= `llm_tools`) 과는 별개 — `llm_tools` 는 self-chain `fetch_*` 7종만, KIPRIS 는 거기 안 들어감. KIPRIS RAG 자체는 P03 Finder 의 chain dispatch graph (R00 → R01 → R02 → R11) 로 분해됨. **kipris knob (via:config)**: `fake` 면 handler 가 canned (`tests/data/kipris-fixtures/`, `src/tools/kipris/fake.py` — mock-actor canned 과 단일 소스) 반환, 실 API·키 불요. 표준 로컬 레시피엔 비포함 (기본 real) — 원할 때 `make deploy set kipris fake`.

---

## 3. 디렉토리 구조

```
engine-prototype/
├── .docs/                       # 설계 문서 (현행 단일 진실 원천)
│   ├── Architectures/           # 시스템 설계 (단일 진실 원천)
│   │   ├── STATIC_BLOCK_ARCHITECTURE.md  # 설계 의도 원본 (수정 금지)
│   │   ├── DRC_ARCHITECTURE.md  # 종합 설계도
│   │   ├── AGENT_SDK_DESIGN.md  # Actor SDK 통합
│   │   ├── DIRECTION_PIPELINE_FLOW.md  # Director 흐름
│   │   └── EXTERNAL_API.md      # 외부 REST + WS contract
│   ├── Features/                # 비즈니스 흐름 reference
│   │   ├── CONCEPT_MATURITY_FLOW.md  # 구체화 단계 (P02.R00) 통합
│   │   └── DRAWING_FLOW.md      # 도면 chain graph
│   ├── Issues/                  # 알려진 잔재
│   │   ├── DIRECTOR-R00-RESIDUALS.md  # 구체화 단계 도입 후 알려진 잔재
│   │   ├── EXTERNAL-API-RESIDUALS.md  # 외부 API 재편 잔재
│   │   ├── AUTH-REDESIGN-RESIDUALS.md # 인증·UserID 재설계(info/user/works) 잔재
│   │   └── DOC-INCONSISTENCY-FOLLOWUPS.md   # 문서 정합 후속
│   ├── Report/                  # dated 스냅샷 리포트 (조사·리뷰·결정 기록)
│   └── Verification/            # verification.md — 검증 도구 7 track 인벤토리
├── .claude/rules/               # AI 에이전트 지침
│
├── 200.DRO/                      # DRO :59200 SINGLE — pure internal chain executor (NO :59290 debug port)
│   └── src/
│       ├── main.py              # CONTROL (/control/spawn + /control/output) + EVENT (/events SSE) + /health 만
│       ├── orchestrator.py      # chain 진행, RT push/pop (P{NN} 전용)
│       ├── pipeline_walker.py   # P{NN} loader + fail-loud legacy/cross-persona
│       ├── branch_evaluator.py  # substitute_placeholders
│       ├── dispatch_resolver.py # dispatch_to.actions 분기 + max_self_recursion 가드
│       ├── dispatcher.py        # Actor /dispatch + SSE 소비
│       ├── cm_client.py         # CM HTTP 클라이언트
│       ├── router.py            # internal surface — POST /control/spawn + POST /control/output(docx 빌드,C6) + GET /events/{u}/{w} (SSE)
│       └── event_sse.py         # per-session RAW SSE broker (event 채널)
│   └── mocks/                   # dro:fake mock (via:image knob — Dockerfile mock stage 가 이것만 COPY)
│       └── dro_app/             # /control/spawn(202) + /control/output(C6 canned+output_ready) + /events(SSE) + /health. spawn → tests/data/dro-tapes
│                                #   playlist 순차재생 (cursor=(u,w,pid), seq/ts 는 emit 시 할당, CM r/w 0)
│
├── 100.Nexus/                  # Nexus :59100 — SOLE external gateway (auth + account + work CRUD/metadata + ALL client REST + client WebSocket)
│   └── src/
│       ├── main.py
│       ├── router.py            # auth + account + work CRUD/metadata + 전 client REST (info/user/works·phase·thread·estimate·media)
│       ├── auth.py              # federated OAuth (google/naver/kakao) + 쿠키(access/refresh) 발급·검증·회전·PKCE
│       ├── cm_client.py         # CM HTTP 클라이언트 (invention 메타·IOM read 등)
│       ├── dro_client.py        # DRO control 채널 클라이언트 (POST /control/spawn)
│       ├── event_consumer.py    # DRO per-session SSE 소비 (event 채널)
│       ├── event_mapper.py      # RAW DRC event → client WS event (persona→channel + display_status)
│       ├── ws_manager.py        # WebSocket connection registry + replay
│       ├── ws_inbound.py        # WS inbound action (message.send 단일, correlation_id 멱등, strict)
│       ├── message_flow.py      # handle_message — user turn conversation write + root chain spawn (ENGINE_MODE)
│       ├── config.py            # Nexus 전용 (ENGINE_MODE 등)
│       └── errors.py            # DRO 와 동일 envelope
│
├── 400.CM/                       # CM :59400 — S3 단일 writer
│   └── src/
│       ├── store.py             # S3 read/write + media presigned 발급 (presign_put/get·list·delete)
│       ├── chain_store.py       # chains/* (manifest, RT, trail, agent_state)
│       ├── queue_store.py       # persona-N
│       ├── lock.py              # 파일 단위 asyncio.Lock
│       └── router.py            # 76 endpoint (users[identity(+delete)/profile/idempotency/refresh-tokens] / manifest / runtime / chains / models / drawings / outputs / inputs / patch / admin)
│
├── 300.Actor/                    # Actor :59300 — unified 단일 컨테이너 (P1~P6 전 persona)
│   └── src/
│       ├── main.py
│       ├── router.py            # POST /dispatch (SSE)
│       ├── dispatcher.py        # 공통 dispatch (모든 persona)
│       ├── composer.py          # single-text prompt 합성
│       ├── engine_config.py     # engine.config 범용 로더 (persona 정의+LLM 운영 SoT read — 코드 persona-제로)
│       ├── actor_session.py     # RT 처리 wrapper (vendor adapter 호출)
│       ├── cm_client.py
│       ├── sse.py
│       ├── llm/                 # LLM vendor adapter + client + retry 통합
│       │   ├── __init__.py      # create_session(persona) entry — engine.config 에서 sdk/model/effort 등 read
│       │   ├── session.py       # AgentSession Protocol
│       │   ├── client.py        # get_gemini_client() singleton (Vertex)
│       │   ├── retry.py         # _RetryableLLMError / with_backoff
│       │   ├── gemini.py        # GeminiAgentSession
│       │   ├── claude.py        # ClaudeAgentSession
│       │   ├── openai.py        # OpenAIAgentSession
│       │   ├── knowledge.py     # @knowledge/ static text loader
│       │   └── fixture.py       # FixtureSession (FIXTURE)
│       └── tools/               # 공유 tool 라이브러리 (11 dir)
│           ├── kipris/  drawing/  vision/  document/  media/
│           └── staging/  maturity/  roadmap/  cm/  knowledge/  fetch/
│   └── mocks/                   # actor:fake mock (via:image knob — Dockerfile mock stage 가 이것만 COPY)
│       ├── actor_app/           # /health + /dispatch(SSE fixture replay) + /tool(canned 6종) + busy-503 marker
│       │                        #   fixture 키잉 = 실 CM read(chain-only route) · CM-write 0 · strict fail-loud
│       └── busy_markers/        # {pipeline_id}/{step_id}.json {"times":N} — 이미지 bake, 미커밋(.gitignore)
│
├── shared/                      # venezia_logging / venezia_secrets / venezia_contracts / venezia_topology / venezia_memory / venezia_pipeline_runtime / venezia_deployment / venezia_cm_client(CM HTTP base — 3 컨테이너 cm_client 공통, D-4)
├── @deployment/                 # 배포 구성 SoT: topology.yaml(committed, 네트워크 형상) + knobs.yaml(committed, 검증 knob 스키마) + engine.config.yaml(committed, persona 정의+LLM/tool 운영 SoT — 빌드타임 COPY→Actor /app/engine.config.yaml) + engine-config.schema.json(committed, 그 명세 — validate stage 12) + profile.stack.yaml(gitignored, 현재 knob 값 — make deploy 가 씀)
├── @contracts/                  # JSON Schema (RT, chain_manifest 신규)
├── @pipelines/                  # P{NN} pipelines (DRC chain dispatch graph). P01 = R00 단일 chain (응대원, Gemini agent SDK 활용). 트리거 = DRO `POST /control/spawn {user_id,work_id,persona,pipeline_id,chain_id}` → 202.
│   └── _shared/GLOBAL.json
│   └── 0{1-6}.{persona}/P{NN}.COMMON.json + P{NN}.R{NN}.*.pipeline.json
├── tests/                       # 7 검증 track (validate / lint / invoke / probe / enact(5/5 게이트) / play / endpoint)
├── compose.yaml                 # 4 컨테이너 정의 (DRO + Nexus + CM + Actor)
└── Makefile                     # 모든 개발 명령어
```

---

## 4. 환경 설정

**필수**: Docker & Docker Compose / uv

**API 키 — AWS Secrets Manager 가 단일 source**. `.env` 직접 export 없음.

| Secret name | 내용 | env 매핑 |
|---|---|---|
| `llm-providers/prod/personal` | ANTHROPIC_KEY / OPENAI_KEY / GOOGLE_CLIENT_* / JWT_SECRET_KEY | `_KEY_MAP` 으로 자동 env 주입 |
| `llm-providers/prod/personal/google-credentials` | Vertex AI service account JSON | `/tmp/google-credentials.json` 파일 + `GOOGLE_GENAI_USE_VERTEXAI=true` / `GOOGLE_APPLICATION_CREDENTIALS` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` 자동 set |
| `public-data-sources/personal` | KIPRIS_KEY | `KIPRIS_API_KEY` env |

로딩 흐름: `shared/venezia_secrets/__init__.py:_load()` 가 `AWS_SECRET_NAME` (comma-separated) 의 secret 들을 모듈 import 시 자동 fetch + env 주입.

**실행**

```bash
make deploy init llm fake auth open   # 로컬/검증: FIXTURE + OPEN profile 생성 (@deployment/profile.stack.yaml)
make up                               # 4 컨테이너 — 모드는 profile 에서 read (positional 없음)
# 실 운영: make deploy init  (전 knob default = PRODUCTION + SECURE) 후 make up
```

> **배포 프로파일 (knob, 모드 단일 소스)** — `@deployment/knobs.yaml`(committed 스키마, 8 knob) + `@deployment/profile.stack.yaml`(gitignored 현재 값, `make deploy` 가 씀)이 컨테이너에 `/etc/deployment.yaml` 로 마운트되고 **`venezia_deployment` 가 런타임 read → 각 config 의 모드**(auth/engine/llm/kipris). 제어: `make deploy init [<knob> <value>...]` (default+override) · `set <knob> <value>` · `show`/`vet`/`reset`. knob: actor/dro/cm/nexus/llm/kipris=real|fake · auth=open|secure · engine=full|smalltalk. **llm: real=PRODUCTION · fake=FIXTURE.** default = 완전 프로덕션(전 real·secure·full) → 로컬은 `llm fake auth open` override 필수.

---

## 5. 개발 명령어 (Makefile)

**인터페이스 = deploy(구성) · up(기동) · 검증 7 track**. 캐싱 X, 매번 풀 reset.

```bash
make deploy init llm fake auth open # 로컬/검증 profile (FIXTURE + OPEN). 실 운영은 init 만(=PRODUCTION+SECURE)
make up                             # profile 대로 풀 reset (~5분, 캐싱 없음, positional 없음)
make mode                               # 현재 profile 모드 (auth/engine/llm/kipris) 표시
make deploy show / vet / set <knob> <value>   # 배포 profile 조회/검증/변경
```

**검증 트랙 인터페이스 (공통 문법: positional = 대상, `VAR=` = 옵션, 모드 = 스택 속성 — 트랙 인자 아님)**:
```bash
make play                           # 無인자 = root pipeline 전수 (fixture 보유 *.R00.* 순차 + 집계)
make play P03.R00                   # 단일 pipeline (dispatch 하위 chain 자동 BFS)
make play P03.R00 SEED=path.json WS_TIMEOUT=1800
make endpoint                       # 無인자 = 전 phase 전수 (Nexus REST+WS contract)
make endpoint ws                    # 특정 phase 만 (health/info/account/works/auth/work_resources/ws/ws_tape/error_envelope/secure)
make endpoint ws_tape               # 포괄 tape suite — dro:fake 스택 전용 (dro:real 이면 skip-pass)
make endpoint ws_tape TAPE=P01.R00.CHAT_CONVERSATION/02-rt-error-message   # 그 tape 만
make endpoint call REST="GET /api/v1/info/providers"          # 단건 REST 호출 (탐색/디버그)
make endpoint call WS='message.send {"content":"안녕하세요"}'  # 단건 WS 송신 + 수신 이벤트 출력
make probe verify                   # 실 CM 블랙박스 게이트
make enact                          # Actor 단일 RT 시나리오 전수 (5/5 정식 게이트 — dispatch/context/tool/concurrency/errors)
make enact concurrency              # 시나리오 단일 (5종 중)
make enact P01.R00 0                # 단건: 실 pipeline step RT 합성·수행·관측 (B4)
make enact PERSONA=2 PROMPT="..."   # 단건: ad-hoc — persona+프롬프트 차터 직접 입력 (spec 파일/SPEC= 도 가능)
```

**운영 보조**:
```bash
make down              # stack 종료 + image/volume 완전 제거
make logs              # 전체 로그 (-f)
make ps                # 컨테이너 상태
make help              # 도움말
```

**MODE 규칙**:
- `FIXTURE`: `tests/data/llm-fixtures/{pipeline_id}/{step_id}.json` replay. 로컬 dev 의 default.
- `PRODUCTION`: 실 LLM SDK 호출 (Claude / Gemini Vertex / OpenAI). **EC2 IAM role 환경에서 동작** — 컨테이너 startup 시 `_check_aws_creds` 가 IMDS endpoint 핑으로 자격 확인. IMDS 없는 환경 (e.g. 일반 노트북) 에서는 fail-loud. **참고**: 이 dev 환경 자체가 이미 EC2 인스턴스 (IAM role `EC2-Instance-S3Full-SecretRO`, region `ap-northeast-2`) 이므로 PRODUCTION 정상 동작.
**부분 반영 룰 없음** — 모든 코드 변경 (src / shared / compose / Dockerfile 무엇이든) 은 `make deploy init …` (모드 설정) 후 `make up` 의 풀 rebuild (`--no-cache --pull`) 로만 반영.

**별도 영역** (이 인프라와 무관):
```bash
make build-classification      # @knowledge/classification/ 빌드
make build-drafting            # @knowledge/drafting/ 빌드
make build-rejections          # @knowledge/rejections/ 빌드
```

---

## 6. 진행 상황

DRC 아키텍처(4 Units / 4 Containers / 6 Personas)는 구축 완료 상태. 현행 설계의 단일 진실 원천 = §2·§3 + `.docs/Architectures/` + 코드 베이스.

---

## 7. 주의사항

**모델 ID** — `claude-opus-4-7` / `gemini-3.1-pro-preview` / `o3`. Persona → 모델/effort/fallback 매핑의
단일 진실 원천 = **`@deployment/engine.config.yaml` 의 `personas`** (코드 persona-제로 — Actor 는
`src/engine_config.py` 범용 로더로 read). Gemini 계열 fallback 은
`gemini-3-flash-preview`, Claude/OpenAI 는 동일 모델 retry. effort 는 1급 공통 키
(claude→`effort`, openai→`reasoning_effort`, gemini→`thinking_level` 번역).

**Gemini = Vertex AI** — `gemini-3.1-pro-preview` 가 global endpoint only. 인증은 service account JSON (AWS Secret) → `GOOGLE_APPLICATION_CREDENTIALS` ADC.

**동시성 계약** — Actor 는 **persona 별 동시 요청 cap** (engine.config `personas.{id}.max_concurrency`, `src/slots.py` 세마포어 집행) + `/tool` 은 별도 풀(`tools.max_concurrency`). 포화 시 즉시 503+`Retry-After` — **포화 ≠ 실패**: DRO 가 시간예산(`DISPATCH_RETRY_BUDGET_S`) 안에서 지수 backoff(상한 30s) 재시도 지속. CM 큐 장부 = rt_id 별 lease (`pending[]+leases{}` — 만료 lease 는 다음 큐 작업 시 lazy 제거).

**agent_state = vendor 원형 envelope (컨텍스트 ②)** — `{schema_version, vendor, model(실사용), items[vendor 원형]}` (CM 은 내용 opaque — persona/updated_at 스탬프만). claude=session transcript entries(`llm/state.py:ClaudeTranscriptStore`+resume) · gemini=ADK events · openai=to_input_list items · fixture=평문. 다음 RT 가 **native 복원** — thinking/tool_use/tool_result 풀충실도 보존. vendor 교체 시에만 `items_to_plain` 텍스트 강등 (claude 타깃만 user-prompt preamble). legacy 평문 `messages` = fail-loud. 포맷 기록처 = `AGENT_SDK_DESIGN.md`.

**(session,persona) 단일 worker 가 chain-at-a-time 소비** — 페르소나별 RT 큐 (`runtime/{persona}/queue.json`, 6개). producer(`run_chain`)가 spawn 시 RT 들을 push, (session,persona) 당 단일 worker(`200.DRO/src/worker.py`)가 큐를 chain-at-a-time 소비 → 같은 (session,persona) 의 chain A + chain B 는 **직렬**(A 끝나야 B). 다른 persona=다른 worker, 다른 session 도 병렬 — 그래서 사용자 메시지마다 P01.R00 + P02.R00 동시 enqueue 는 평행(P1 vs P2 = 다른 worker, P01 응대 + P02 구체화). 병렬 step fan-out(nested list `asyncio.gather`)은 한 chain 안 동시 RT. race 는 file-key `asyncio.Lock`.

**P02.R00.CONCEPT_MATURITY 8 step (구체화 단계, P-C+P-D)** — `dispatch_to: null` self-contained.
- step 0/2/3/4/6 = Agent step (LLM 호출). step 1/5/7 = DRO tool step (LLM 없음, KIPRIS 패턴).
- step 0 `extract_stack` → step 1 `staging.save` (CDS PUT). 사용자 말 7 필드 누적.
- step 2/3/4 `score_clarity / completeness / potential` = **정적 병렬 묶음**(독립 채점 동시, D-6 — nested list, Actor P02 cap=2 라 2씩) → step 5 `maturity.compute` (가중 합산 + CMM PUT). `model.maturity` WS 는 Nexus 가 chain 완료 시 CM fetch (#12, DRO 미발사).
- step 6 `update_roadmap` → step 7 `roadmap.persist` (UR top-level array PUT). `model.roadmap` WS 는 Nexus 가 chain 완료 시 CM fetch (#12, DRO 미발사).
- 정식 7-way dispatch (gap/classify/rejection/prior_art/reasoning/drawing/evaluation) 는 `P02.R99.CENTRAL_AGENT` 에 보존 — **미구현 target**, 작성 단계 마일스톤에서 활성화 예정. 현 P02.R00 은 구체화 단계 전용 임시 self-contained chain.

**3 산출물 (P-C+P-D)** — `models/` 안:
- **CDS** (`concept-discovery-stack.json`) — 사용자 말 차곡차곡 7 필드 누적 (모델 아님, IOM precursor). writer = P02 step 1.
- **CMM** (`concept-maturity-model.json`) — 3 지표 + 7 sub-score + 가중 합산 (`overall = 0.30·clarity + 0.45·completeness + 0.25·potential`). writer = P02 step 5.
- **UR** (`user-roadmap.json`) — **top-level JSON array** (file-level meta 없음 — version/last_updated/schema_version 없음). 8 필드 strict item (id/title/description/status/priority/input_type/options/answer). 같은 id 보존 + D 안 자연 누적 (해소 item 도 list 안 — 시간선 자체). writer = P02 step 7.

**roadmap 답변 = REST 단독** (`PATCH /api/v1/works/{id}/estimate/roadmap/{item_id}` + `{value}`) — WS inbound action 아님(WS inbound 는 `message.send` 단일 — correlation_id 멱등, 재시도는 같은 id 재send). Nexus 가 CM item 을 즉시 atomic update(`status=satisfied`+answer) + structured user turn append (meta `{kind:"roadmap.answer", roadmap_item_id, input_type}` — conversation 메타데이터일 뿐 WS action 아님) + P01/P02 chain spawn (P02 가 다음 사이클에서 재평가).

**JSON Patch (RFC 6902) + JSON Pointer (RFC 6901) — P-E** — CM 의 모든 모델 부분 R/W 표준화. PATCH body = `[{op, path, value}, ...]` ops array. GET `?pointer=/path/to/field` 부분 read. path 표준 동일 (RFC 6901).

**Pipeline 포맷 = P{NN} 전용** — 모든 *.pipeline.json 은 `P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json` 패턴. legacy 키 (`W{NN}`, `step.type`, `step.next`, `parallel_task`, `sequential_conditional`, `api_call`, `http_response`, `sub_pipeline`, `agentic_llm_loop`) 는 허용 안 됨. `200.DRO/src/pipeline_walker.py` 의 `_assert_no_legacy_keys` 가 발견 시 RuntimeError.

**Step 타입 단 2종** — `instructions` 있으면 LLM step (composer + Actor SDK), `tool` 있으면 tool step (DRO direct `POST /tool/{name}`, LLM 없는 빠른 경로). 이외는 fail-loud. **단 둘 다 RT** — tool step 도 rt_id·`rts/{rt_id}.json` 기록·enqueue/pop·`rt_*` 이벤트가 LLM step 과 동일 (tool=RT 통일, N-7 — "RT 1개 = 1 작업단위(LLM 또는 tool)").

**instructions 객체 형태** — `instructions` 는 *객체* (`{...}`). 안에 `inline` (string, 짧은 인라인 텍스트) **XOR** `reference` (string, `@pipelines/.../*.md` path) 중 정확히 1개. 거의 모든 LLM step 은 `reference` 사용 — pipeline.json 옆 체인 디렉토리 (`@pipelines/{NN}.{persona}/P{NN}.R{NN}/{step_slug}.md`) 에 표준 markdown 으로 작성. composer (`300.Actor/src/composer.py`) 가 Actor 측에서 read → prompt 의 `[TASK]` 섹션에 그대로 dump. instructions 가 `list[str]` 또는 `string` 형태면 허용 안 됨 — loader + `_assert_no_legacy_instructions` 에서 fail-loud.

**chain dispatch graph** — `sub_pipeline` 은 허용 안 됨. 마지막 step 의 `output_contract` 가 `dispatch_choice` (integer enum) 출력 → `dispatch_to.actions[choice]` 의 pipeline_id 들이 다음 chain 으로 생성. self-recursion 으로 loop 표현 (max_self_recursion 가드).

**Cross-persona 직접 통신 금지** — Actor 끼리 호출 X. cross-persona 협력은 (1) Nexus 의 user-driven spawn (P01+P02 평행 — Nexus 가 결정·forward, DRO 가 admission(같은 4-tuple 완전대기 dedup, D-1) 후 실행) 또는 (2) chain dispatch graph (P02→P03/P04/P05/P06 같이 자기 chain 의 dispatch_to 로 다음 페르소나 trigger) 로만. **P01 같은 응대 페르소나는 self-contained — 다른 페르소나로 dispatch 하지 않음**. LLM 의 `llm_tools` 는 self-chain `fetch_*` 만 허용 (`fetch_dialog`, `fetch_step_output`, `fetch_drawing`, `list_drawings`, `fetch_outputs`, `fetch_conversation`). cross-persona 도구 발견 시 `_assert_no_cross_persona_tools` 가 RuntimeError.

**4-layer cascading** — `inject_context` / `recommended_context` / `fragments` / `llm_tools` 가 GLOBAL → persona.COMMON → pipeline.common → step 순으로 머지. 같은 name+source 가 두 layer 중복 = validator error.

**Pipeline 검증** — `make validate` (15 stage 전수 — stage 15 = 정적 병렬 묶음 형태) 또는 `cd tests/validate && uv run python -m validate --pipeline <pipeline_id>` (예: `P03.R00.PRIOR_ART_SEARCH_ANALYZE`).

**AUTH_MODE** — `OPEN`(인증 불요·고정 user_id) | `SECURE`(쿠키 인증 강제 — httpOnly access/refresh, 콜백 Set-Cookie+302, refresh 회전·logout·PKCE). 소스 = profile `auth` knob (default `secure`), 로컬은 `make deploy set auth open` (또는 `init … auth open`). health `auth_mode` 노출. 식별: **user_id ⊥ JWT ⊥ provider sub**(자체 UUID 발급 + `users/identities/` 매핑, PII 0), federated 3-provider(`/api/v1/user/auth/{provider}/...`). API 트리 = info/user/works. 현행 외부 표면 SoT = `external_api/openapi.nexus.json` (Nexus 단독) + `asyncapi.yaml` (servers/host = nexus:59100).

**Actor LLM 모드 2-way** (profile `llm` knob — real=PRODUCTION | fake=FIXTURE. compose env 아님)
- `FIXTURE`(llm:fake) — `FIXTURE_PATH/{pipeline_id}/{step_id}.json` replay (로컬 dev / 회귀 테스트). `make deploy set llm fake`.
- `PRODUCTION`(llm:real) — 실 SDK 호출 (Claude / Gemini Vertex / OpenAI). EC2 IAM role 환경에서 동작 (`make deploy set llm real` — default). **이 dev 환경 = EC2** 이므로 PRODUCTION 직접 동작.

`300.Actor/src/llm/__init__.py:create_session` 는 FIXTURE/PRODUCTION 외의 MODE 값에 fail-loud.

**AWS 자격증명** — EC2 IAM role only. compose.yaml 에 `AWS_ACCESS_KEY_ID` 등 host env pass-through 명시 없음 (의도적). 컨테이너 startup 시 `_check_aws_creds` 가 IMDS endpoint 핑으로 자격 확인. **이 dev 환경 자체가 EC2 인스턴스** (IAM role `EC2-Instance-S3Full-SecretRO`, region `ap-northeast-2`) 라 IMDS 살아있음 → `make deploy init && make up`(llm:real=PRODUCTION) 정상 동작. 모든 API key / KIPRIS / Google service account JSON 은 AWS Secrets Manager 가 단일 source — `shared/venezia_secrets/__init__.py:_load()` 가 컨테이너 startup 시 자동 fetch + env 주입.

**검증 트랙 — invoke(스택없는 로직 99%) vs probe(실 CM 블랙박스)** — `tests/invoke` = **유일한 라인-커버리지 트랙**. 스택 없이 5 패키지(shared·**cm**·dro·actor·account) 의 로직을 라인 99% 게이트(`make invoke`). CM 도 가짜 S3 로 스택 없이 구동 — **CM 을 빼지 않는다**. **제품 코드에 검증 흔적 0** — coverage omit/exclude 는 `tests/invoke/coveragerc`(--cov-config)에만, 제품 src/pyproject·`shared` 엔 `# pragma`·`[tool.coverage]` 두지 않음. `tests/probe` = **실 CM 블랙박스**(stack 필요). `make probe verify` = CM 의 *전 API* 전수 호출(`/openapi.json` 기반) + 실 S3 *메모리 구조* ↔ scaffolding 대조(`structure`). 라인-커버리지 아님(그건 invoke). 구조검증 로직은 probe 트랙 안(`_structure.py`) — 오직 probe 만 쓰므로 제품/shared 엔 두지 않음. CM 은 invoke(고립 로직)·probe(실 API+구조) 양쪽에 — **레이어 다른 다층 검증(중복 아님)**.

**검증 트랙 — enact(track 5) = 정식 게이트 (시나리오 5/5)** — Actor 가 단일 RT 를 *수행(enact)* 하는 격리 트랙 (UUT=real Actor 1 컨테이너, harness=DRO 역할 대행 — RT 실 pipeline 합성 seed→dispatch SSE / POST tool→CM 부수효과 관측, mock-below=llm:fake+real CM). 시나리오 5종: **dispatch**(SSE 순서/RT done+dispatch-result 계약/structured/envelope/trail) · **context**(컨텍스트 ② items 누적 실왕복) · **tool**(POST /tool 200/404/400/500 계약) · **concurrency**(persona cap 503 — gather 동시진입 결정적 포화+Retry-After) · **errors**(SSE error 4경로 — persona 미등재/RT 부재/composer 키 결손/legacy agent_state). 無인자 전수 green = 정식 게이트(exit 0), FIXTURE 가드. **단건 수행 모드 (B4)**: `make enact P01.R00 0` (pipeline step RT) / spec 파일·`PERSONA= PROMPT=` (ad-hoc 차터 — prompt 는 instructions.inline 설탕, literal 강제 텍스트는 fragments). 설계·사용법 = `tests/enact/README.md`.

**검증 트랙 — endpoint(통합) vs play(단위)** — `tests/play` = **단위 트랙**. pipeline 1회 trigger (DRO `POST /control/spawn` 직접) + 컨텍스트만 준비 → DRO 가 `dispatch_to` 로 후속 chain 을 잇고(play 가 잇는 게 아님) play 는 **dual 관측**: ① CM trail polling ② DRO per-session RAW SSE (`raw-sse-event` schema·seq 단조·≥1건 자동 assert — 실패 = FAIL. `play/_sse.py` self-contained, RAW SSE 검증 = play 전용). stack MODE 자동 감지. `tests/endpoint` = **통합검증(integration)**. 외부 클라이언트인 척 Nexus REST+WS contract 를 호출해 클라이언트가 겪는 **모든** 동작(전체 chain 구동 WS 이벤트 포함)을 직접 커버. 내부 LLM_MODE 모름(**mode-agnostic** — MODE 는 endpoint 가 붙는 stack 의 속성). 단 `dro` knob 만 profile 에서 read — **dro:fake 스택**(mock-dro tape player)에선 timing 3종(message.reply/model.maturity/model.roadmap)이 warn→hard 승격 + `ws_tape` phase 가 포괄 tape suite(~43 케이스, `tests/data/dro-tapes`)로 Nexus event_mapper 전 분기를 결정적 검증 (dro:real 이면 ws_tape skip-pass). **통합검증은 단위 통과분을 빼지 않는다 — endpoint 커버리지를 play 에 위임하지 않음.** 상세 = `.docs/Verification/verification.md` (7 track 인벤토리).
