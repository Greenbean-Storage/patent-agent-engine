# README 갱신 전수 조사 (README-REFRESH-SURVEY)

> **2026-07-17** · 목적: `README.md` 전면 갱신(국문+영문)의 데이터 원천.
> 방법: 코드 실측 — 병렬 조사 에이전트 16개(영역 맵핑 11 + README 주장 검증 4 + 누락 색출 1, 도구 호출 454회) + 핵심 수치 별도 재검증(직접 grep/실행).
> 원칙: **코드 = 단일 진실**. 문서(.docs / .claude/rules)의 서술은 검증 대상 — 본 조사에서 코드 불일치 46건 확인(§4). 모든 항목에 evidence(file:line) 부기. 사실만 기록.

---

## 0. 현 README 상태

- 국문 단일 파일 90줄. **영문 README 없음.**
- 마지막 실질 갱신 = `70f6a41` (2026-06-24, 인터페이스 문서 정합 + account→nexus·invention→work rename 커밋).
- 그 이후 코드/계약 커밋: C2b~C8 API 재편(`47bab8d`~`e44f9f2` — typed body·If-Match 필수·성숙도 키 short 통일·message id+correlation 멱등·message.resend 제거·WS close code 분리·HAL `_links` 제거·openapi 재생성), C5 멱등 fix 3건(`c5710fa`·`bfadb46`·`8e41626`), dated 문서 정리 2건(`117bd54`·`47a0a50`).
- 현 README 주장 52건 판정: **일치 46 / 불일치(구식) 2 / 부분 일치 4** → §1.

---

## 1. 현 README 주장 판정

### 1.1 정정 대상 6건

**1. [Architecture 표 + 표기 + 문서 링크] — 부분 일치**
- README 주장: Nexus auth = Google OAuth + JWT 발급
- 실측: JWT 발급·검증은 Nexus 단독 (create_access_token/refresh, jwt.encode) — 맞음. 단 OAuth 는 Google 단독이 아니라 federated 3-provider (google/naver/kakao) + httpOnly 쿠키(nx_access/nx_refresh) 기반 + PKCE
- 근거: 100.Nexus/src/auth.py:40 `SUPPORTED_PROVIDERS = ("google", "naver", "kakao")`, :91-146 (_google/_naver_client/_kakao_client provider registry), :277-300 create_access_token/jwt.encode, :178-179 PKCE code_challenge, :335-337 (httpOnly 쿠키 nx_access)

**2. [Architecture 표 + 표기 + 문서 링크] — 부분 일치**
- README 주장: Nexus mypage = account + work CRUD/metadata
- 실측: account (GET /api/v1/user/account, GET·PUT .../alias) + work 생성(POST 201)/목록(GET)/진입(GET)/meta(GET·PATCH) 존재. work 자체의 DELETE endpoint 는 없음 (delete route 는 auth provider 연결해제·media 뿐) — 'CRUD' 중 D 미존재
- 근거: 100.Nexus/src/router.py:418,425,434 (account/alias), :480-483 (POST /api/v1/user/works 201), :514 (GET 목록), :552 (GET /works/{work_id}), :566,589 (GET·PATCH meta); router.delete 전수 grep = :350 (auth provider), :907 (media) 만

**3. [Architecture 표 + 표기 + 문서 링크] — 부분 일치**
- README 주장: persona 별 동시성 cap = src/slots.py 세마포어
- 실측: cap 집행 위치 = 300.Actor/src/slots.py, persona 별 cap = engine.config max_concurrency — 맞음. 단 구현은 asyncio.Semaphore 가 아니라 카운터형 동시성 풀 (asyncio.Lock 보호 non-blocking try_acquire — 자체 docstring 이 '카운터형 동시성 풀'로 명시). /tool 은 별도 풀
- 근거: 300.Actor/src/slots.py:20-21 (`class _Pool: "카운터형 동시성 풀 (asyncio.Lock 보호, non-blocking try-acquire)"`), :23-38 (cap/inflight 카운터 + asyncio.Lock), :45-48 (persona 풀), :53-56 (tool 별도 풀)

**4. [검증 7 track + API/Documentation 링크] — 불일치(구식)**
- README 주장: make validate — JSON 산출물 schema · cross-ref · tool registry (정적, 14 stage)
- 실측: 15 stage. schema=Stage 1, cross-ref=Stage 3, tool registry=Stage 4 로 내용 서술 자체는 맞으나 stage 수가 다름 (Stage 15 = 정적 병렬 묶음 형태 검증까지 존재)
- 근거: tests/validate/validate/cli.py:1 ('15 stage 정적 검증 orchestrator'), cli.py:3-17 (Stage 1~15 목록), cli.py:203-217 (집계표 Stage 1~15), cli.py:235 ('validate PASS — 15 stage 모두 통과'), tests/validate/validate/stages/stage_15_parallel_shape.py 존재. Makefile:48 help 도 '15 stage'

**5. [검증 7 track + API/Documentation 링크] — 불일치(구식)**
- README 주장: make endpoint — 외부 API (REST + WS) contract e2e (10 phase)
- 실측: 11 phase — health/info/account/works/auth/work_resources/output/ws/ws_tape/error_envelope/secure (output phase 가 목록에 포함돼 총 11)
- 근거: tests/endpoint/endpoint/cli.py:23-36 (_ALL_PHASES 리스트 실측 11개 — 'output' phase: output/draft build·preview·download + proposal 501 포함), cli.py:42 ('검증 track 7 — 외부 API REST + WS contract e2e')

**6. [검증 7 track + API/Documentation 링크] — 부분 일치**
- README 주장: OpenAPI 는 Nexus only — 외부 표면 단일 게이트웨이, DRO 는 client REST 미제공
- 실측: DRO client REST 미제공은 실측 일치 (DRO 표면 = POST /control/spawn + POST /control/output + GET /events/{user_id}/{work_id} + GET /health 뿐). 단 openapi.json 문서 자체는 DRO 도 자기 internal 표면용으로 서빙 — 200.DRO/src/main.py:48 에 openapi_url="/api/v1/openapi.json" 이 설정돼 있고 DRO 포트 59200 도 host publish 됨. 'client-facing OpenAPI 는 Nexus 단독' 이 정확한 현행 서술
- 근거: 200.DRO/src/router.py:42 (/control/spawn), :88 (/control/output), :129 (/events/{user_id}/{work_id}), 200.DRO/src/main.py:54 (/health) — client REST 라우트 0. 200.DRO/src/main.py:48 (openapi_url="/api/v1/openapi.json"), @deployment/topology.yaml:25 (dro: host_publish_port 59200)

### 1.2 일치 판정 46건 (검증 완료 — 유지 가능 서술)

**[Architecture 표 + 표기 + 문서 링크]**
- 특허 출원을 돕는 AI Agent 시스템 — DRC 아키텍처가 사고 흐름을 외부 큐로 분해, Actor 컨테이너가 RT(Reasoning Task) 단위로 처리 — 근거: 400.CM/src/queue_store.py:1-9 (페르소나 RT 큐 runtime/{persona}/queue.json, producer push), 200.DRO/src/worker.py:128-144 (get_persona_queue/persona_queue_pop), 300.Actor/src/router.py:25 (POST /dispatch), @contracts/_shared/reasoning_task.schema.json (존재)
- 4 Units / 4 Containers / 6 Personas — 근거: compose.yaml services = ['dro','nexus','cm','actor'] (yaml 파싱 실측), @deployment/engine.config.yaml:19,29,40,50,61,72 (persona id 1~6, python yaml 파싱 count=6)
- 100.Nexus 포트 59100 — 근거: @deployment/topology.yaml:29 `nexus: { host: nexus, port: 59100, host_publish_port: 59100 }`, compose.yaml:92 container_name: 100.Nexus
- Nexus = SOLE external gateway — 모든 client REST + client WebSocket — 근거: 100.Nexus/src/router.py:208-1069 (REST 전 트리), :1079 @router.websocket("/api/v1/works/{work_id}/thread/stream"); 200.DRO/src 전 decorator grep = /control/spawn·/control/output·/events/{u}/{w}·/health 4개뿐; 300.Actor/src/router.py:25,85 + main.py:32
- Nexus 모듈 = ws_manager/event_mapper/ws_inbound/message_flow/event_consumer/dro_client — 근거: 100.Nexus/src/ 디렉토리 실측: ws_manager.py, event_mapper.py, ws_inbound.py, message_flow.py, event_consumer.py, dro_client.py 전부 존재
- 200.DRO 포트 59200 (single) — 근거: @deployment/topology.yaml:25 `dro: { host: dro, port: 59200, host_publish_port: 59200 }`, compose.yaml:48 container_name: 200.DRO, :53-54 ports 단일 매핑 (compose.yaml 주석: '구 production/debug 이원화·:59290 제거')
- DRO = pure INTERNAL chain executor. Surface = POST /control/spawn + POST /control/output (docx 빌드) + GET /events/... (SSE) + GET /health 만 — 근거: 200.DRO/src/router.py:42 (@router.post /control/spawn, status_code=202), :88-127 (@router.post /control/output — PatentDocxGenerator().generate → cm.upload_document draft.docx → event_sse.emit_raw output_ready), :129-130 (@router.get /events/{user_id}/{work_id} → StreamingResponse), 200.DRO/src/main.py:54 (@app.get /health); 전 파일 @router/@app grep 결과 이 4개 외 없음
- DRO 에 client REST/WS/media/auth/debug-app 없음 — 근거: 200.DRO/src/*.py @router/@app decorator 전수 grep = 4개뿐, 200.DRO/src/main.py:5 (내부망 신뢰 주석), compose.yaml 200.DRO 주석 '외부 클라이언트 표면 0'
- 400.CM 포트 59400, Context Manager, S3 단일 writer — 근거: @deployment/topology.yaml:26 `cm: { host: cm, port: 59400, host_publish_port: 59400 }`, compose.yaml:128 container_name: 400.CM, 400.CM/src/store.py:17,33,104 (boto3.client('s3'), put_object); boto3 grep 전수 — 4 컨테이너 src 중 400.CM/src/store.py 만 hit
- 300.Actor 포트 59300, unified Actor — P1~P6 전 persona 단일 컨테이너 (수락 집합 = @deployment/engine.config.yaml personas) — 근거: @deployment/topology.yaml:27 `actor: { host: actor, port: 59300, host_publish_port: 59300 }`, compose.yaml:168 container_name: 300.Actor (actor 서비스 단일), @deployment/engine.config.yaml:18-81 (personas 1~6), 300.Actor/src/slots.py:48 (`engine_config.persona(pid)["max_concurrency"]  # 미등재 = RuntimeError`)
- 표기 — 표의 이름 = container_name(docker ps) — 근거: compose.yaml:48 (container_name: 200.DRO), :92 (100.Nexus), :128 (400.CM), :168 (300.Actor)
- 표기 — DNS 서비스키 = nexus/dro/cm/actor — 근거: compose.yaml services = ['dro','nexus','cm','actor'] (yaml 파싱 실측), @deployment/topology.yaml:25-29 (host: dro/cm/actor/nexus)
- 표기 — 소스 디렉토리 = 100.Nexus/200.DRO/400.CM/300.Actor — 근거: ls 실측: /home/ubuntu/workspace/repository/engine-prototype/{100.Nexus,200.DRO,300.Actor,400.CM}/src/ 존재
- 자세한 설계 링크: .docs/Architectures/DRC_ARCHITECTURE.md — 근거: /home/ubuntu/workspace/repository/engine-prototype/.docs/Architectures/DRC_ARCHITECTURE.md (ls 실측 존재, :9 에 DRC 정의 서술)

**[Tech Stack]**
- Framework: FastAPI (Python 3.14+) — 근거: 100.Nexus/pyproject.toml:4,6 · 200.DRO/pyproject.toml:4,6 · 300.Actor/pyproject.toml:4,6 · 400.CM/pyproject.toml:4,6 (requires-python = ">=3.14", fastapi>=0.115.0)
- Package Manager: uv (pip/poetry 대체) — 근거: 100.Nexus/uv.lock · 200.DRO/uv.lock · 300.Actor/uv.lock · 400.CM/uv.lock · shared/uv.lock 존재; Makefile:85 (uv --version 체크), Makefile:93,96,99 (uv run)
- Validation: Pydantic v2 — 근거: 100.Nexus/pyproject.toml:8-9 · 200.DRO/pyproject.toml:8-9 · 300.Actor/pyproject.toml:8-9 · 400.CM/pyproject.toml:8-9 · shared/pyproject.toml:12
- Storage: AWS S3 (400.CM 가 단일 writer, boto3 직접) — 근거: 400.CM/src/store.py:17 (import boto3), :33 (boto3.client("s3")); grep 결과 그 외 boto3 사용처는 shared/venezia_secrets/__init__.py:68-71 (secretsmanager) 뿐
- LLM: Claude Opus 4.7 (P2/P5), Gemini 3.1 Pro Preview Vertex AI (P1/P3/P6), GPT o3 (P4) — 근거: @deployment/engine.config.yaml:18-81 (personas 1~6 의 llm 블록); shared/venezia_secrets/__init__.py:50 (GOOGLE_GENAI_USE_VERTEXAI=true); 300.Actor/pyproject.toml:18-21
- Inter-container: HTTP + SSE — 근거: 200.DRO/src/dispatcher.py:11,26,77,92 (httpx.AsyncClient + parse_sse); 200.DRO/src/event_sse.py (per-session RAW SSE broker); 100.Nexus/src/event_consumer.py:44,103 (sse task/sse_error)
- Document: python-docx (docx_generator.py — DRO internal, POST /control/output 배선: IOM→docx→CM upload→output.ready) — 근거: 200.DRO/pyproject.toml:10; 200.DRO/src/router.py:9-11,88,124-125; 200.DRO/src/docx_generator.py:1-6,27; 100.Nexus/src/event_mapper.py:125-134 (output_ready → output.ready)
- Tools: plantuml / openscad / schemdraw / chromadb — 근거: 300.Actor/Dockerfile:10-13 (plantuml, openscad); 300.Actor/pyproject.toml:16 (schemdraw>=0.19), :27 (chromadb>=0.5.0)
- Linter / Type Check: ruff (--fix+format 자동적용) + mypy + bandit + pip-audit (make lint 4개 다 게이트) — 근거: tests/lint/lint/cli.py:1,12,28-35,42 ("4개 모두 게이트"); tests/lint/lint/runners/ruff.py:27-33 (check --fix write + format write); Makefile:95-96
- Secrets: AWS Secrets Manager (단일 source) — 근거: shared/venezia_secrets/__init__.py:53-79 (_load, secretsmanager client, GOOGLE_GENAI_USE_VERTEXAI); compose.yaml:61,103,139,177 (AWS_SECRET_NAME env)

**[Getting Started + Pipeline 실행]**
- Prerequisites: Docker & Docker Compose — 근거: Makefile:14 (DOCKER := docker compose --env-file ...), compose.yaml 존재 (repo root)
- Prerequisites: uv — 근거: Makefile:84-85 (.uv target — uv --version 실패 시 설치 안내 + exit 1), Makefile:92-147 (validate/lint/invoke/probe/enact/play/endpoint/deploy 전부 `: .uv`)
- Prerequisites: AWS credentials (PRODUCTION 모드는 EC2 IAM role 환경에서만) — 근거: Makefile:240-241 (llm:real grep → _check_aws_creds), Makefile:307-313 (http://169.254.169.254/.../security-credentials/ 핑 실패 시 'PRODUCTION 모드는 EC2 IAM role 환경에서만 동작' 에러), 300.Actor/src/config.py:20-22
- make deploy init llm fake auth open && make up = 로컬 dev (FIXTURE + OPEN) — 근거: Makefile:143-148 (deploy passthrough → venezia_deployment), Makefile:176-180 (deploy positional dispatcher), shared/venezia_deployment/runtime.py:23 (_LLM_MODE = {real: PRODUCTION, fake: FIXTURE}), runtime.py:62-64 (open|secure → OPEN|SECURE)
- 로컬 dev 로 4 컨테이너가 뜬다 — 근거: compose.yaml:47-48, 91-92, 127-128, 163-168 (services 4개 + container_name)
- make deploy init && make up = 실 운영, 전 knob default (PRODUCTION + SECURE, EC2 IAM) — 근거: @deployment/knobs.yaml:10-17 (8 knob default 실측), shared/venezia_deployment/runtime.py:23 (real→PRODUCTION), Makefile:240-241 + 307-313 (_check_aws_creds)
- make logs = 전체 로그 — 근거: Makefile:265-266
- make ps = 컨테이너 상태 — 근거: Makefile:268-269
- make down = 종료 + image / volume 제거 — 근거: Makefile:261-263
- make play (無인자) = root pipeline 전수 — 근거: Makefile:120-129 (play target), tests/play/play/cli.py:49-52 (_root_pipelines — llm-fixtures 의 .R00. 스캔), cli.py:88 (targets), tests/data/llm-fixtures/ 디렉토리 실측
- make play P02.R00 = 단일 실행 — 근거: Makefile:151-157 (PLAY_VERB dispatcher) + 228 (P% 가짜 target), tests/play/play/cli.py:60-64, 200.DRO/src/pipeline_walker.py:213-229 (resolve_pipeline_id — prefix 유일 매칭/ambiguous/KeyError), @pipelines/02.director/P02.R00.CONCEPT_MATURITY.pipeline.json 존재
- make play P03.R00 SEED=path.json WS_TIMEOUT=1800 (옵션 변수) — 근거: Makefile:126-127 ($(if $(SEED),--seed-iom-from ...) + --ws-timeout $(or $(WS_TIMEOUT),1800)), tests/play/play/cli.py:66-77 (--seed-iom-from / --ws-timeout default 1800.0), @pipelines/03.finder/P03.R00.PRIOR_ART_SEARCH_ANALYZE.pipeline.json 존재

**[검증 7 track + API/Documentation 링크]**
- 섹션 제목 '검증 7 track' — 검증 트랙이 7개 (validate/lint/invoke/probe/enact/play/endpoint) — 근거: Makefile:2 (.PHONY 에 validate lint invoke probe enact play endpoint 7 verb), Makefile:47 (help 배너 '검증 7 track'), tests/ 하위에 validate·lint·invoke·probe·enact·play·endpoint 7 디렉토리 존재
- make lint — 자동수정+검사: ruff --fix+format · mypy · bandit · pip-audit (4개 다 게이트) — 근거: tests/lint/lint/cli.py:1 ('4 runner orchestrator'), cli.py:42 ('advisory 폐지 — 4개 모두 게이트'), cli.py:49-58 (max(rc) 집계, overall 0 이어야 PASS), tests/lint/lint/runners/ = ruff.py·mypy.py·bandit.py·pip_audit.py, runners/ruff.py:27-33 (check --fix write + format write)
- make invoke — 스택 없는 로직 라인 99% (5 suite — 유일한 라인-커버리지 트랙) — 근거: tests/invoke/invoke/cli.py:4-8 (suite 5종: shared·cm·dro·actor·account), cli.py:35 ('5 패키지 전부 99'), cli.py:51,58,65,72,82 (각 suite fail_under: 99), cli.py:95-103 (--cov/--cov-fail-under). tests/ 전체 grep 에서 --cov 는 invoke 외 0건 — probe/endpoint/validate 의 'coverage' 는 API 표면/census registry (tests/endpoint/endpoint/coverage.py:1 '외부 표면 44 전수 대비 커버 상태' — 라인 커버리지 아님)
- make probe — 실 CM 블랙박스, 13 sub-command (view/trail/check/seed/list/list-chains/dump-rt/models/dialogs/clean/structure/exercise/verify), verify=게이트 — 근거: tests/probe/probe/cli.py:50 (add_subparsers required=True), cli.py:52-134 (add_parser 13회 — grep -c 실측 13, 이름: view/trail/check/seed/list/list-chains/dump-rt/models/dialogs/clean/structure/exercise/verify), tests/probe/probe/commands/verify.py 존재, Makefile:77 ('verify 게이트: CM API 전수 + scaffolding 구조검증'), Makefile:224 (가짜 target 13개 동일 목록)
- make enact — Actor 단일 RT 수행, 시나리오 5/5 정식 게이트 + 단건 모드(P{NN}.R{NN} <step> | spec | PERSONA= PROMPT=) — 근거: tests/enact/enact/scenarios/__init__.py:9 (ALL_SCENARIOS = dispatch·context·tool·concurrency·errors 5종), cli.py:246 (無인자 = 전수), cli.py:109-117 (전부 PASS 시 exit 0), cli.py:74-80 (llm_mode≠FIXTURE 면 exit 2 가드), cli.py:206-256 (positional P{NN}.R{NN} [step] | spec 경로 | --spec/--persona/--prompt), Makefile:205-208 (ENACT_PROMPT/ENACT_PERSONA/ENACT_SPEC env 전달)
- make play — pipeline 실행 (無인자 = root 전수, make play P{NN}.R{NN} = 단일) — 근거: tests/play/play/cli.py:9-11 (usage), cli.py:49-52 (_root_pipelines = fixtures 의 *.R00.* 전수), cli.py:88 (targets = 단일 or 전수), cli.py:93 ('root 전수 모드'), cli.py:58 ('無인자 = root 전수, dispatch chain BFS follow'), Makefile:120-129 (play recipe + SEED/WS_TIMEOUT 전달)
- API Documentation — 표준 명세 링크 .docs/Architectures/EXTERNAL_API.md 존재 — 근거: /home/ubuntu/workspace/repository/engine-prototype/.docs/Architectures/EXTERNAL_API.md 존재 확인 (test -f)
- API Documentation — WS event schema 링크 @contracts/00.dro/websocket-events.json 존재 — 근거: /home/ubuntu/workspace/repository/engine-prototype/@contracts/00.dro/websocket-events.json 존재 확인 (test -f)
- OpenAPI (실행 중) URL = http://localhost:59100/api/v1/openapi.json — 근거: 100.Nexus/src/main.py:41 (openapi_url="/api/v1/openapi.json"), @deployment/topology.yaml:29 (nexus: port 59100, host_publish_port 59100)
- Documentation 링크 목록 10개 파일 (.docs/Architectures/{STATIC_BLOCK_ARCHITECTURE,DRC_ARCHITECTURE,AGENT_SDK_DESIGN,DIRECTION_PIPELINE_FLOW,EXTERNAL_API}.md + .docs/Features/{CONCEPT_MATURITY_FLOW,DRAWING_FLOW}.md + .claude/rules/{onboarding,project,standard}.instructions.md) 모두 존재 — 근거: test -f 전수 확인: .docs/Architectures/STATIC_BLOCK_ARCHITECTURE.md, DRC_ARCHITECTURE.md, AGENT_SDK_DESIGN.md, DIRECTION_PIPELINE_FLOW.md, EXTERNAL_API.md, .docs/Features/CONCEPT_MATURITY_FLOW.md, DRAWING_FLOW.md, .claude/rules/onboarding.instructions.md, project.instructions.md, standard.instructions.md — 11경로(EXTERNAL_API 중복 포함) 모두 EXISTS

---

## 2. 수치 실측 요약 (빠른 참조)

| 항목 | 실측값 | 근거 |
|---|---|---|
| Nexus HTTP 표면 | `@router` 33개 = REST 32 + WS 1, 별도 `GET /health` | `100.Nexus/src/router.py`, `main.py:89-91` |
| Nexus REST 묶음 | info 2 · user/auth 6 · account 3 · works(컬렉션+진입+meta) 5 · phase 2 · thread 1 · estimate 3 · media 4 · output 6 | `100.Nexus/src/router.py:208-1071` |
| OAuth provider | 3종 — google / naver / kakao (PKCE S256) | `100.Nexus/src/auth.py:40` |
| 인증 쿠키 | 3종 — `nx_access`(15분) / `nx_refresh`(14일) / `nx_pkce`(600초) | `100.Nexus/src/config.py:43-52` |
| client WS push 이벤트 | 9종 — message.received / message.reply / work.progress / work.failed / model.maturity / model.roadmap / output.ready / system.resync_required / system.error | `event_mapper.py:88-161`, `ws_inbound.py`, `ws_manager.py` |
| WS replay buffer | (user,work) 키별 seq + deque(maxlen=200), 소켓 수명 cap 720분(close 1001), close 4401/4404 | `100.Nexus/src/ws_manager.py:23`, `config.py:60`, `router.py:1107-1140` |
| DRO 내부 RAW SSE 이벤트 | 8종 — rt_enqueued / rt_started / rt_progress / rt_result / rt_error / chain_completed / output_ready / error | `@contracts/00.dro/raw-sse-event.schema.json:13-22` |
| DRO 표면 | 4개 — POST /control/spawn · POST /control/output · GET /events/{u}/{w} (SSE) · GET /health (+ 자체 openapi.json) | `200.DRO/src/router.py`, `main.py:48,54` |
| DRO dispatch 재시도 예산 | `DISPATCH_RETRY_BUDGET_S` = 1200s, 지수 backoff | `200.DRO/src/dispatcher.py` |
| CM endpoint | 76개 — 경로 묶음 = users(identity/profile/idempotency/refresh-tokens) / sessions / manifest / runtime(queue·dialog·chain·conversation) / chains / models / drawings / outputs / media / admin. **inputs 묶음 없음, media·dialog 실존. 'patch' 는 경로 묶음이 아니라 각 자원의 PATCH 메서드(RFC 6902)** | `400.CM/src/router.py` (grep 76 재확인 + 검증 에이전트 :116-952 실측) |
| Actor tool registry | **19종** (@register 실측 — §5 Actor 절 전체 목록. 조사 에이전트 1차 보고 18은 오산, 데코레이터 19개 재확인) | `grep -rn "@register(" 300.Actor/src/tools/` |
| llm_tools (fetch_*) | 6종 — fetch_dialog / fetch_step_output / fetch_drawing / list_drawings / fetch_outputs / fetch_conversation (문서 일부 '7종' 표기는 구식) | `300.Actor/src/tools/fetch/__init__.py:69-76`, `200.DRO/src/pipeline_walker.py:57-64` |
| pipeline 파일 | 22개 — P01 1 / P02 8 / P03 6 / P04 4 / P05 2 / P06 1 (+ COMMON 6 + GLOBAL.json) | `find @pipelines -name '*.pipeline.json'` (재확인) |
| 배포 knob | 8종 — actor/dro/cm/nexus/llm/kipris=real|fake · auth=open|secure · engine=full|smalltalk | `@deployment/knobs.yaml:10-17` |
| shared 패키지 | 9개 — logging / secrets / contracts / topology / memory / pipeline_runtime / deployment / cm_client / **media_config** | `shared/pyproject.toml:23` |
| @deployment 구성 파일 | topology.yaml · knobs.yaml · engine.config.yaml · engine-config.schema.json · **media.config.yaml · media-config.schema.json** · profile.stack.yaml(gitignored) | `git ls-files @deployment/` |
| validate | **15 stage** (stage_01~06·10~15 모듈 12개 + contracts(7)/contracts_extended(8)/external_api(9) 비번호 모듈 3개. 실행 출력 '15 stage 모두 통과' 재확인) | `tests/validate/validate/cli.py:1-55,203-235` |
| lint | 4 runner 전부 게이트 — ruff(--fix+format 상시) / mypy / bandit / pip-audit | `tests/lint/lint/cli.py` |
| invoke | 5 suite(shared/cm/dro/actor/account) × fail_under=99, coveragerc = `tests/invoke/coveragerc` 단일, test 파일 76개 | `tests/invoke/invoke/cli.py` |
| probe | sub-command 13개 — check/clean/dialogs/dump-rt/exercise/list/list-chains/models/seed/structure/trail/verify/view | `tests/probe/probe/commands/` (13 모듈) |
| enact | 시나리오 5종 — dispatch/context/tool/concurrency/errors + 단건 3형(P{NN}.R{NN} [step] | SPEC= | PERSONA=+PROMPT=) | `tests/enact/enact/scenarios/__init__.py:9`, `cli.py:205-262` |
| endpoint | **11 phase** — health/info/account/works/auth/work_resources/**output**/ws/ws_tape/error_envelope/secure + call 단건 모드 | `tests/endpoint/endpoint/cli.py:23-36` |
| dro-tapes | 43개 — P01.R00 35 + P02.R00 8 | `find tests/data/dro-tapes -name '*.json'` (재확인) |
| tests/data | 4종 — llm-fixtures(5 pipeline dir) / kipris-fixtures / dro-tapes(43) / iom-samples(1) | `tests/data/` ls |
| @contracts | git 트래킹 92 파일 — _shared 21 + 00.dro 5 + persona stages output_contract 64 | `@contracts/` (조사 에이전트 실측) |
| persona max_concurrency | P1=4 / P2=2 / P3=3 / P4=2 / P5=2 / P6=3 (+tools 별도 풀) | `@deployment/engine.config.yaml` personas |
| .docs/Issues | 8개 파일 (onboarding §3 의 4개 나열은 구식) | `.docs/Issues/` ls |
| Python | 3.14+ (전 컨테이너 pyproject) | 각 `pyproject.toml` requires-python |

---

## 3. 현 README 에 없는 실존 항목 28건 (갱신 시 수록 후보 풀)

**1. 배포 knob 시스템 (@deployment profile)**
- README 는 `make deploy init llm fake auth open` / `make deploy init` 명령 2줄만 있고, knob 8종(actor/dro/cm/nexus/llm/kipris=real|fake · auth=open|secure · engine=full|smalltalk)·knobs.yaml(committed 스키마)+profile.stack.yaml(gitignored 현재값)의 이원 구조·컨테이너 /etc/deployment.yaml 마운트를 venezia_deployment 가 런타임 read 하는 반영 방식·`make deploy set/show/vet/reset`·`make mode` 서술이 없음.
- 근거: @deployment/knobs.yaml:10-17, @deployment/profile.stack.yaml, shared/venezia_deployment/runtime.py, Makefile:255(mode target)

**2. mock 컨테이너 2종 (dro:fake / actor:fake)**
- README 에 mock 서술 없음. 실제로는 200.DRO/mocks/dro_app(실 표면 동형 stateless mock — tests/data/dro-tapes 43개 tape playlist 재생)과 300.Actor/mocks/actor_app(fixture replay SSE + canned tool 6종 + busy-marker 503)이 존재하고, Dockerfile production/mock 멀티스테이지를 compose build.target(<UNIT>_TARGET)으로 선택함. Nexus·CM 은 mock 미보유(knobs available:false).
- 근거: 200.DRO/mocks/dro_app/, 300.Actor/mocks/actor_app/, 200.DRO/Dockerfile, 300.Actor/Dockerfile, tests/data/dro-tapes/(43 json 실측), @deployment/knobs.yaml:10-13

**3. 6 persona 정의 상세 (engine.config.yaml SoT)**
- README 는 LLM 매핑 1줄(P2/P5·P1/P3/P6·P4 그룹)과 'engine.config personas' 참조 구절만 있음. persona 이름(P1 Buddy/P2 Director/P3 Finder/P4 Thinker/P5 Crafter/P6 Inspector)·역할·fallback_model(gemini-3-flash-preview 등)·effort(P2/P5 high, P4 medium)·max_concurrency(4/2/3/2/2/3)·channel 라벨의 단일 소스가 @deployment/engine.config.yaml 이고 Actor 코드는 persona-제로(범용 로더)라는 서술이 없음.
- 근거: @deployment/engine.config.yaml:18-(personas), @deployment/engine-config.schema.json, 300.Actor/src/engine_config.py

**4. WebSocket contract 상세**
- README 의 WS 언급은 Architecture 표의 'client WebSocket' 구절뿐. WS URL(/api/v1/works/{work_id}/thread/stream?since_seq=N)·envelope v2({type,timestamp,seq,data})·server push 이벤트 9종·inbound message.send 단일(correlation_id 멱등)·(user_id,work_id) 키별 seq + replay buffer 200 + system.resync_required·close code(4401/4404/1001)·channel 6 라벨(support/analysis/research/thinking/drafting/review) 서술이 없음.
- 근거: 100.Nexus/src/ws_manager.py, 100.Nexus/src/ws_inbound.py, 100.Nexus/src/event_mapper.py, shared/venezia_contracts/models/dro_api/channels.py, @contracts/00.dro/websocket-events.json, .docs/Architectures/external_api/asyncapi.yaml

**5. 인증 체계 (README 기존 서술이 실측과 불일치)**
- README:11 은 'auth (Google OAuth + JWT 발급)' 로만 기재. 코드 실측은 google/naver/kakao 3-provider federated OAuth(SUPPORTED_PROVIDERS)+PKCE S256+httpOnly 쿠키 3종(nx_access/nx_refresh/nx_pkce)+refresh family(fid+jti) 회전+AUTH_MODE OPEN|SECURE+user_id 자체 UUID mint(provider sub 와 분리, PII 미저장) — README 에 이 구조 서술 없음.
- 근거: 100.Nexus/src/auth.py:40(SUPPORTED_PROVIDERS), 100.Nexus/src/config.py, 400.CM/src/store.py(users 루트 identity/refresh-tokens), README.md:11

**6. Nexus REST 엔드포인트 트리**
- README 에 REST 표면 목록 없음(OpenAPI URL 링크만). 실측은 router.py @router 33개(REST 32 + WS 1)+/health — info(2)/user·auth(6)/account(3)/works(5)/phase(2)/thread(1)/estimate(3— roadmap 답변 PATCH 포함)/media(4)/output(6) 트리와 openapi.nexus.json 26 paths 가 존재함.
- 근거: 100.Nexus/src/router.py(@router 33 실측), 100.Nexus/src/main.py(/health), .docs/Architectures/external_api/openapi.nexus.json

**7. external_api 스냅샷 산출물 링크**
- README API Documentation 섹션은 EXTERNAL_API.md·websocket-events.json·런타임 openapi URL 3건만 링크. 실존하는 .docs/Architectures/external_api/ 의 openapi.nexus.json(OpenAPI 3.1 스냅샷)·asyncapi.yaml(AsyncAPI 3.0 WS 계약)·CLIENT-HANDOFF.md(frontend 핸드오프 노트) 링크가 없음.
- 근거: .docs/Architectures/external_api/openapi.nexus.json, .docs/Architectures/external_api/asyncapi.yaml, .docs/Architectures/external_api/CLIENT-HANDOFF.md

**8. 사용자 메시지 → root chain spawn 데이터 흐름**
- README 에 end-to-end 데이터 흐름 서술 없음. 코드에는 사용자 메시지 1건 → Nexus message_flow 가 conversation.json user turn write + DRO POST /control/spawn 으로 P01.R00.CHAT_CONVERSATION 항상 + ENGINE_MODE=FULL 시 P02.R00.CONCEPT_MATURITY spawn(chain_id 는 correlation_id 기반 uuid5 결정적)하는 흐름과 ENGINE_MODE(FULL|SMALLTALK) knob 이 있음.
- 근거: 100.Nexus/src/message_flow.py, 100.Nexus/src/config.py(ENGINE_MODE, P01_ENTRY/P02_ENTRY), 100.Nexus/src/dro_client.py

**9. DRO 실행 모델 (worker/producer/재시도/복구)**
- README 의 DRO 서술은 표면 4개 나열과 'chain orchestration' 구절뿐. (user_id,work_id,persona) 키별 단일 worker 의 chain-at-a-time 직렬 소비·run_chain producer(RT 일괄 enqueue)·admission dedup(chain_id 멱등 + pending 코얼레싱)·startup 시 미완 chain resume(resume_active_chains)·Actor 503 포화 시 시간예산(DISPATCH_RETRY_BUDGET_S=1200s) 지수 backoff 재시도·nested list 정적 병렬 fan-out 서술이 없음.
- 근거: 200.DRO/src/worker.py, 200.DRO/src/orchestrator.py, 200.DRO/src/dispatcher.py, 200.DRO/src/main.py(lifespan resume)

**10. 내부 채널 2종 (control / event RAW SSE)**
- README 에 Nexus↔DRO 내부 통신 구조 서술 없음. 코드에는 control=Nexus→DRO REST(POST /control/spawn)·event=DRO→Nexus per-session RAW SSE(이벤트 8종: rt_enqueued/rt_started/rt_progress/rt_result/rt_error/chain_completed/output_ready/error, replay 버퍼 없음)와 Nexus event_consumer(ref-count 공유 SSE 소비)→event_mapper(client WS 이벤트 변환) 경로가 있음.
- 근거: 200.DRO/src/event_sse.py, 200.DRO/src/router.py, 100.Nexus/src/event_consumer.py, 100.Nexus/src/event_mapper.py, @contracts/00.dro/raw-sse-event.schema.json

**11. S3 스토리지 레이아웃 + scaffolding.yaml 단일 소스**
- README 는 'AWS S3 (400.CM 가 단일 writer)' 1줄만. sessions/{user_id}/{work_id} 하위 runtime(00.dro conversation + persona queue/chain)·models(IOM/CMM/CDS/UR)·drawings·outputs·media 레이아웃과 별개 users/ 루트, 그리고 키 구조의 단일 소스가 shared/venezia_memory/scaffolding.yaml + key builder(직접 literal 금지)라는 서술이 없음.
- 근거: shared/venezia_memory/scaffolding.yaml, shared/venezia_memory/__init__.py

**12. CM 상세 (76 endpoint, RFC 6902/6901, lease 큐)**
- README 는 CM 을 'Context Manager. S3 단일 writer' 1줄로만 기재. 실측 76 endpoint(users identity/profile/idempotency/refresh-tokens 포함), JSON Patch(RFC 6902) ops array PATCH + JSON Pointer(RFC 6901) ?pointer= 부분 read 표준화, persona RT 큐의 pending[]+leases{} lease 장부(lazy 만료 제거), file-key asyncio.Lock 직렬화 서술이 없음.
- 근거: 400.CM/src/router.py(@router 76 실측), 400.CM/src/store.py, 400.CM/src/queue_store.py, 400.CM/src/chain_store.py, 400.CM/src/lock.py

**13. @pipelines 영역 (22 pipeline·P{NN} 포맷·dispatch graph)**
- README 에 @pipelines 디렉토리 언급 0 ('Pipeline 실행' 섹션은 make play 명령만). 실측 22개 *.pipeline.json(P01 1/P02 8/P03 6/P04 4/P05 2/P06 1)+COMMON 6+GLOBAL.json, step 2종(instructions XOR tool — tool 도 RT), instructions 객체(inline XOR reference), 4-layer cascading, 마지막 step dispatch_choice → dispatch_to.actions chain dispatch graph, legacy 키 fail-loud 가 존재함.
- 근거: @pipelines/(22개 실측), @pipelines/_shared/GLOBAL.json, @pipelines/manifest.pipeline.yaml, 200.DRO/src/pipeline_walker.py, shared/venezia_pipeline_runtime/

**14. @contracts 영역 전체 구조**
- README 는 @contracts/00.dro/websocket-events.json 1건만 링크. 실제 @contracts 는 git 트래킹 92 파일 — _shared(RT/chain_manifest/pipeline-definition/IOM 등 21종)+00.dro 5종(내부 control/SSE 계약 포함)+persona stages output_contract 64종 — 이며 shared/venezia_contracts/loader.py 의 ContractLoader(Draft-07)가 런타임 소비함. 이 구조 서술 없음.
- 근거: @contracts/_shared/, @contracts/00.dro/, @contracts/{01.buddy..06.inspector}/stages/, shared/venezia_contracts/loader.py

**15. Actor tool registry + fetch_* llm_tools**
- README Tech Stack 의 'Tools: plantuml/openscad/schemdraw/chromadb' 는 이미지 의존성만 기재. Actor 의 POST /tool/{name} tool registry(@register 18종 — kipris/drawing/vision/document/media/staging/maturity/roadmap/cm/knowledge)와 LLM native function calling 용 fetch_* 6종(fetch_dialog/fetch_step_output/fetch_drawing/list_drawings/fetch_outputs/fetch_conversation, cross-persona 금지) 서술이 없음.
- 근거: 300.Actor/src/tools/(11 dir), 300.Actor/src/tools/fetch/, 300.Actor/src/router.py(POST /tool)

**16. KIPRIS 통합**
- README 에 KIPRIS 언급 0. 코드에는 KIPRIS wrapper tool 2종(kipris.search_patents/get_patent_detail)·P03 Finder 의 KIPRIS RAG chain graph(P03.R00→R01→[self|R02])·kipris knob(fake=canned fixtures, 실 API 키 불요)·KIPRIS_API_KEY secret(public-data-sources/personal) 이 존재함.
- 근거: 300.Actor/src/tools/kipris/, @pipelines/03.finder/, tests/data/kipris-fixtures/, @deployment/knobs.yaml:15, compose.yaml(actor AWS_SECRET_NAME)

**17. 산출물 모델 4종 (IOM/CDS/CMM/UR)**
- README 본문에 models/ 산출물 서술 없음(Features 문서 링크만). 코드에는 invention-object-model.json(IOM)·concept-discovery-stack.json(CDS)·concept-maturity-model.json(CMM, 가중 합산 0.30/0.45/0.25)·user-roadmap.json(UR, top-level array) 4파일과 P02.R00 8-step chain(step 1/5/7 tool 이 writer)이 존재함.
- 근거: shared/venezia_memory/scaffolding.yaml(models namespace), @pipelines/02.director/P02.R00.CONCEPT_MATURITY.pipeline.json, 300.Actor/src/tools/{staging,maturity,roadmap}/, 400.CM/src/router.py(models 14 endpoint)

**18. media 업로드 (presigned S3 직접)**
- README 에 media 서술 0. 코드에는 Nexus media 4 endpoint(업로드 티켓 201/목록/메타+다운로드 URL/삭제 — 바이트는 브라우저↔S3 직접, 서버 미경유)와 CM presigned 발급(generate_presigned_post/url), 설정 SoT @deployment/media.config.yaml(max 20MiB, MIME 5종, work 당 50, 리빌드 없이 반영)이 존재함.
- 근거: 100.Nexus/src/router.py(media 4 endpoint), 400.CM/src/store.py(presign_put/get·list·delete), @deployment/media.config.yaml, shared/venezia_media_config/

**19. shared/ 9 패키지**
- README 에 shared/ 언급 0. 실측은 단일 uv 패키지 venezia-shared 안 9개 — venezia_logging/secrets/contracts/topology/memory/pipeline_runtime/deployment/cm_client/media_config — 이며 4 컨테이너가 Dockerfile COPY + path dep 로 내장함.
- 근거: shared/(9 디렉토리 실측), shared/pyproject.toml, 각 컨테이너 Dockerfile(COPY shared/)

**20. @knowledge 3 도메인 + build target**
- README 에 @knowledge 및 make build-* 서술 0. 실측은 classification(IPC+CPC 1348 파일)/drafting(KIPO 심사기준 추출+요약)/rejections(summary+by-section A..H+Chroma cases[gitignored]) 3 도메인과 make build-classification/build-drafting/build-rejections(+verify-*) target, Actor 컨테이너 /app/@knowledge :ro 마운트 소비(3곳)가 존재함.
- 근거: @knowledge/{classification,drafting,rejections}/, Makefile(build-* targets), tools/{classification-indexer,manual-indexer,rejections-indexer}/, compose.yaml(actor @knowledge mount), 300.Actor/src/llm/knowledge.py

**21. tools/ 루트 유틸리티**
- README 에 tools/ 루트 서술 0. 실측은 인덱서 uv 프로젝트 3종 외에 openapi-export(make export-openapi — Nexus openapi 를 external_api/openapi.nexus.json 으로 저장)와 일회성 마이그레이션 스크립트 2종(migrate_cmm_keys.py, migrate_pipelines.py)이 존재함. make export-openapi target 자체도 README 에 없음.
- 근거: tools/openapi-export/, tools/migrate_cmm_keys.py, tools/migrate_pipelines.py, Makefile:315-318

**22. Makefile 보조 target·검증 track 세부 문법**
- README 검증 섹션에 없는 실존 인터페이스: make mode(현 knob 표시, Makefile:255)·make topology·make endpoint <phase> 단건/call 모드(REST=/WS= 단건 호출)/ws_tape(TAPE= 단일 tape, dro:fake 전용)·make enact ad-hoc SPEC= 경로. README 는 endpoint 를 無인자 형태만 기재.
- 근거: Makefile:131,182-183,255, tests/endpoint/endpoint/cli.py(call·_ALL_PHASES), tests/enact/

**23. 검증 수치 — validate 15 stage · endpoint 11 phase**
- README:63 은 validate 를 '14 stage' 로 기재 — 실측은 15 stage(Stage 15 parallel shape 존재, 실행 출력 '15 stage 모두 통과'). README:69 는 endpoint 를 '10 phase' 로 기재 — 실측 _ALL_PHASES 는 11개(output phase 포함: health/info/account/works/auth/work_resources/output/ws/ws_tape/error_envelope/secure).
- 근거: tests/validate/validate/cli.py:17,217, tests/endpoint/endpoint/cli.py:23-36, README.md:63,69

**24. 미구현/placeholder 현황**
- README 에 미구현 경계 서술 0. 실측: output/proposal 3 endpoint = 501(status_code=501 라우트), draft 다운로드 X-Payment-Token 결제 게이트 = 검증 no-op, P02.R99.CENTRAL_AGENT(정식 7-way dispatch) = 파일 존재하나 프로덕션 src 참조 0건(도면 그래프 P04/P05/P06·IOM writer 흐름이 이 미구현으로 미가동), WS rate limit/Origin allowlist 부재.
- 근거: 100.Nexus/src/router.py:920,1059, @pipelines/02.director/P02.R99.CENTRAL_AGENT.pipeline.json, .docs/Issues/AUTH-REDESIGN-RESIDUALS.md, .docs/Issues/EXTERNAL-API-RESIDUALS.md, .docs/Features/DRAWING_FLOW.md

**25. Documentation 섹션 누락 링크 (Verification/Issues/Report)**
- README Documentation 목록에 .docs/Verification/verification.md(검증 7 track 인벤토리), .docs/Issues/ 8개 파일(DIRECTOR-R00/EXTERNAL-API/AUTH-REDESIGN/DOC-INCONSISTENCY/DRO-ACTOR-INTERFACE/MEDIA/REST-NORMALIZATION/VERIFICATION-GAPS), .docs/Report/ 7개, @pipelines/README.md, tests/ 각 track README.md 링크가 없음.
- 근거: .docs/Verification/verification.md, .docs/Issues/(8 파일 실측), .docs/Report/(7 파일 실측), @pipelines/README.md, tests/enact/README.md

**26. AWS Secrets Manager 주입 상세**
- README 는 'Secrets: AWS Secrets Manager (단일 source)' 1줄. secret 3종 이름(llm-providers/prod/personal, .../google-credentials, public-data-sources/personal)·모듈 import 시 _load() 자동 fetch + _KEY_MAP env 주입·Vertex service account JSON 자동 설치(/tmp/google-credentials.json + GOOGLE_APPLICATION_CREDENTIALS 등)·EC2 IAM role/IMDS 확인(_check_aws_creds) 서술이 없음.
- 근거: shared/venezia_secrets/__init__.py:15(_KEY_MAP), compose.yaml(AWS_SECRET_NAME 서비스별), Makefile(_check_aws_creds)

**27. make up 풀 리셋 시맨틱 + topology.yaml**
- README 는 make up 명령만 기재. 인자 거부($(error))·5단계 풀 리셋(down --rmi all -v → build --no-cache --pull → up --force-recreate → healthcheck 대기)·부분 반영 룰 없음·모드가 env 아닌 profile 런타임 read 라는 반영 모델, 그리고 host/port SoT topology.yaml(/etc/topology.yaml 마운트 + TOPOLOGY_NETWORK internal|external) 서술이 없음.
- 근거: Makefile(_full_reset, up target), @deployment/topology.yaml, shared/venezia_topology/, compose.yaml(마운트·build.target)

**28. Actor LLM 세션 계층 (vendor adapter·agent_state)**
- README 본문에 Actor 의 LLM 호출 구조 서술 없음(모델명만). 코드에는 LLM_MODE 2-way(FIXTURE|PRODUCTION, 이외 fail-loud)·vendor adapter 4종(claude/gemini/openai/fixture)·fallback 1회+backoff 재시도+response_schema 검증 재시도·effort 공통 키 번역(claude effort/openai reasoning_effort/gemini thinking_level)·agent_state vendor 원형 envelope({schema_version,vendor,model,items}) native 복원이 존재함.
- 근거: 300.Actor/src/llm/__init__.py(create_session), 300.Actor/src/llm/{claude,gemini,openai,fixture}.py, 300.Actor/src/llm/retry.py, 300.Actor/src/actor_session.py

---

## 4. 타 문서의 코드 불일치 46건 (README 작성 시 원문 인용 주의 대상)

> README 를 다른 문서에서 옮겨 적으면 아래 불일치가 전파된다. 각 항목 = 문서 서술 / 코드 실측 / 근거.

### .claude/rules/onboarding.instructions.md

- **서술**: router.py # 76 endpoint (users[identity(+delete)/profile/idempotency/refresh-tokens] / manifest / runtime / chains / models / drawings / outputs / inputs / patch / admin)
  - **실측**: 76개 숫자는 실측 일치. 그러나 'inputs' 묶음 경로는 router.py 에 0개(문자열 'inputs' 자체가 grep 0건)이고, 목록에 없는 media 묶음 4개(presign-put/presign-get/list/DELETE)와 dialog 묶음 3개가 실존한다.
  - 근거: grep -n 'inputs' 400.CM/src/router.py → 0건; 400.CM/src/router.py:677-716 (media 4), 787-813 (dialog 3)
- **서술**: "`llm_tools` 는 self-chain `fetch_*` 7종만"
  - **실측**: make_fetch_tools 가 반환하는 fetch tool 은 6종 (fetch_dialog / fetch_step_output / fetch_drawing / list_drawings / fetch_outputs / fetch_conversation) — project.instructions.md 의 허용 목록 6종과는 일치
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/tools/fetch/__init__.py:69-76 (all_tools 6개)
- **서술**: "`llm_tools` 는 self-chain `fetch_*` 7종만" (§2 KIPRIS 단락)
  - **실측**: allowlist 는 6종 (fetch_dialog/fetch_step_output/fetch_drawing/list_drawings/fetch_outputs/fetch_conversation) — schema enum·Actor 구현 모두 6개. 같은 문서·project.instructions 의 열거 목록 자체도 6종
  - 근거: @contracts/_shared/pipeline-definition.schema.json:95 enum(6개); 300.Actor/src/tools/fetch/__init__.py:69-76
- **서술**: §3 디렉토리 구조에서 shared/ 를 8개 패키지로 열거: "venezia_logging / venezia_secrets / venezia_contracts / venezia_topology / venezia_memory / venezia_pipeline_runtime / venezia_deployment / venezia_cm_client" (146행).
  - **실측**: 실측 9개 — venezia_media_config 가 추가로 존재하며 wheel packages 목록에 포함되고 Nexus 미디어 라우트가 런타임 read 한다.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/pyproject.toml:23; shared/venezia_media_config/__init__.py:1-9; 100.Nexus/src/router.py:27,834-842
- **서술**: §4 표에서 secret llm-providers/prod/personal 의 내용을 "ANTHROPIC_KEY / OPENAI_KEY / GOOGLE_CLIENT_* / JWT_SECRET_KEY" 로 열거 (164행 부근 표).
  - **실측**: _KEY_MAP 은 NAVER_CLIENT_ID/NAVER_CLIENT_SECRET, KAKAO_CLIENT_ID/KAKAO_CLIENT_SECRET 도 등록(주석: "federated provider 확장 (Naver / Kakao)") — 문서 표의 열거에는 이 4개 키가 없음.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_secrets/__init__.py:22-26
- **서술**: §3 디렉토리 구조가 .docs/Issues/ 를 4개 파일(DIRECTOR-R00 / EXTERNAL-API / AUTH-REDESIGN / DOC-INCONSISTENCY)로 나열.
  - **실측**: 실제 Issues/ 는 8개 파일 — 추가로 DRO-ACTOR-INTERFACE-FOLLOWUPS.md, MEDIA-RESIDUALS.md, REST-NORMALIZATION-RESIDUALS.md, VERIFICATION-GAPS.md 존재.
  - 근거: .docs/Issues/ ls 실측 (8 파일)

### .claude/rules/project.instructions.md

- **서술**: POST .../output/draft = "빌드·200 동기 placeholder — 빌드 기능 미구현"
  - **실측**: draft_build 는 dro_client.control_output(user_id, work_id, "draft") 로 DRO POST /control/output 에 docx 빌드를 실제 위임하고 {document_id, filename, size_bytes} 를 반환 — 빌드 배선 구현 상태 (같은 문서·onboarding 의 다른 절과 memory 는 C6 완료로 기술).
  - 근거: 100.Nexus/src/router.py:959-985, 100.Nexus/src/dro_client.py (control_output)
- **서술**: 내부 RAW event = rt_enqueued / rt_started / rt_progress / rt_result / rt_error / chain_completed / error 7종
  - **실측**: event_mapper 는 raw type "output_ready" 도 처리해 client output.ready 로 매핑 — 문서의 RAW event 목록에 output_ready 부재.
  - 근거: 100.Nexus/src/event_mapper.py:125-142
- **서술**: 내부 RAW event 목록을 `rt_enqueued / rt_started / rt_progress / rt_result / rt_error / chain_completed / error` 7종으로 나열 (line 193)
  - **실측**: 코드는 output_ready 를 포함해 8종 emit — router.py control/output 이 RAW output_ready 발사, 계약 enum 과 DRC_ARCHITECTURE.md:418 도 8종(output_ready 포함)
  - 근거: 200.DRO/src/router.py:125; @contracts/00.dro/raw-sse-event.schema.json:13-22; .docs/Architectures/DRC_ARCHITECTURE.md:418
- **서술**: `W{NN}` / `parallel_task` / `sequential_conditional` / `api_call` / `http_response` / `agentic_llm_loop` 등을 `pipeline_walker._assert_no_legacy_keys` 가 발견 시 RuntimeError 내는 '키'로 서술
  - **실측**: _assert_no_legacy_keys 의 검사 집합(_LEGACY_TOP_KEYS 6종 + _LEGACY_STEP_KEYS 22종)에 parallel_task/sequential_conditional/api_call/http_response/agentic_llm_loop 라는 키는 없음 — 코드가 잡는 것은 type/next/sub_pipeline 등 키이며(해당 이름들은 구 step.type 의 값), W{NN} 파일명은 _assert_no_legacy_keys 가 아니라 _index 의 파일명 정규식(_P_FILENAME_RE) 검사가 RuntimeError 를 냄
  - 근거: 200.DRO/src/pipeline_walker.py:20,23-54,84-111,130-141
- **서술**: users/* + /sessions/{u}/{i}/* — 76 endpoint (..., outputs, inputs, patch, admin/active-chains)" 및 "/sessions/{u}/{i}/runtime/* — chain runtime (manifest, queue, RT, trail, agent_state, dialog, inputs)
  - **실측**: runtime 하위에 inputs 관련 엔드포인트·키 builder 가 없다. runtime 실측 표면 = manifest(인덱스)/queue/dialog/chain(manifest·trail·rts·agent_state)/conversation(00.dro). venezia_memory 에도 inputs 관련 key builder 없음.
  - 근거: 400.CM/src/router.py:592-927 (runtime 전체 라우트), shared/venezia_memory/__init__.py:131-358 (key builder 목록에 inputs 없음)
- **서술**: CM 의 모든 write 가 file_key 단위 asyncio.Lock 으로 직렬화된다.
  - **실측**: lock_for(asyncio.Lock) 사용은 queue_store 의 push/pop/release 와 chain_store 의 create_chain/add_chain_to_manifest/update_chain_in_manifest/patch_chain/append_trail/patch_rt/put_agent_state 에 한정. store.py 의 write/patch(모델 PUT·PATCH)/append_conversation/set_array_item_by_id/write_profile 등과 chain_store.create_rt 는 lock 없이 sync 함수의 no-yield 원자성(단일 인스턴스)에 의존한다.
  - 근거: 400.CM/src/lock.py:22-23; lock_for 호출처 = 400.CM/src/queue_store.py:73,99,132 + 400.CM/src/chain_store.py:71,93,159,224,270,326,382 (store.py 에는 lock import 없음 — 400.CM/src/store.py:10-27)
- **서술**: tool 표가 kipris 2종·drawing.render·cm 2종·knowledge 1종·media 4종·staging.save·maturity.compute·roadmap.persist 만 나열
  - **실측**: 실측 registry 는 19종(데코레이터 재확인) — 표에 없는 등록 tool 6종 존재: drawing.plantuml / drawing.openscad / drawing.schemdraw / document.parse / vision.image_io / vision.review_drawing (이 6종은 @pipelines 하위 어떤 pipeline JSON 에서도 미참조)
  - 근거: grep '@register(' /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/tools/ — drawing/__init__.py:149,154,159 · document/__init__.py:17 · vision/__init__.py:16,29

### .docs/Architectures/AGENT_SDK_DESIGN.md · .docs/Architectures/DIRECTION_PIPELINE_FLOW.md

- **서술**: P02.R00 step 0 이름을 'extract_to_stack' 으로 표기 (AGENT_SDK:60, DIRECTION:9)
  - **실측**: 실제 step instructions reference = '@pipelines/02.director/P02.R00/extract_stack.md' — slug 는 extract_stack
  - 근거: @pipelines/02.director/P02.R00.CONCEPT_MATURITY.pipeline.json:21 + @pipelines/02.director/P02.R00/ 디렉토리 목록(extract_stack.md)

### .docs/Architectures/DRC_ARCHITECTURE.md

- **서술**: §6.6 'LLM step 의 SDK function calling 에 등록 가능한 tool 은 다음 7개 allowlist 만' / §12 'self-chain fetch_* 7종' (열거 자체는 6개)
  - **실측**: allowlist 는 6종 — fetch_dialog/fetch_step_output/fetch_drawing/list_drawings/fetch_outputs/fetch_conversation. AGENT_SDK_DESIGN.md 는 '6종' 으로 정확
  - 근거: 200.DRO/src/pipeline_walker.py:57-64(_LLM_TOOL_ALLOWLIST 6개), 300.Actor/src/tools/fetch/__init__.py:69-76(함수 6개); DRC_ARCHITECTURE.md:263,471
- **서술**: §12 tool registry 표의 호출처 — media_classifier.classify=P01.R00.step0, media_processor.image/document/audio_describe=P01.R10/R20/R21.step0
  - **실측**: 어떤 pipeline 도 media_classifier/media_processor 를 참조하지 않음(tool step 전수 grep 0건). P01 은 R00.CHAT_CONVERSATION 단일 — P01.R10/R20/R21 pipeline 파일 자체가 없고, P01.R00 의 유일한 tool step 은 step 2 cm.append_conversation. 핸들러 등록(@register)만 존재
  - 근거: grep -rl media_ @pipelines = 0건; ls @pipelines/01.buddy/ = P01.R00 만; P01.R00.CHAT_CONVERSATION.pipeline.json:52; DRC_ARCHITECTURE.md:464-465
- **서술**: §5 S3 구조 루트를 's3://venezia-bucket/sessions/{user_uuid}/{invention_uuid}/' 로 표기
  - **실측**: scaffolding.yaml(단일 truth source)의 entity_path = 'sessions/{user_id}/{work_id}', key builder 도 work_id 명명 — invention_uuid 표기는 폐기된 구 명칭 잔재(경로 형상은 동일, placeholder 라벨만 상이)
  - 근거: shared/venezia_memory/scaffolding.yaml:20(entity_path), shared/venezia_memory/__init__.py:142-144; DRC_ARCHITECTURE.md:130

### .docs/Architectures/external_api/CLIENT-HANDOFF.md

- **서술**: §5 'WS model.maturity/model.roadmap 는 SECURE + ENGINE_MODE=FULL + 모델 존재 시에만 발생, 개발(OPEN/smalltalk)·빈 모델이면 미발생' (line 150)
  - **실측**: event_mapper 의 발생 조건은 chain_completed[persona=2] + CM 에 모델 존재뿐 — auth_mode(OPEN/SECURE) 게이트 코드 없음. OPEN 스택에서도 P02 spawn(engine full)이면 발생 (endpoint 트랙이 auth open 인 dro:fake 스택에서 model.maturity/model.roadmap timing 을 hard 검증하는 전제와도 부합)
  - 근거: 100.Nexus/src/event_mapper.py:100-124(auth 분기 부재); CLIENT-HANDOFF.md:150
- **서술**: 머리 기준선 '기준: 2026-06-24 · 커밋 70f6a41. 아래 계약 산출물은 서버가 실제 서빙하는 것과 정확히 일치(검증됨)' (line 5)
  - **실측**: 파일 자체 최종 갱신은 2026-06-28 b7dd786(C8 최종 동기화) — 내부 dateline 이 실제 동기화 커밋보다 4일 과거를 가리킴. 이후에도 코드 커밋 3건(C5 멱등 fix, 2026-06-28)이 ws_inbound 동작을 변경(계약 자체는 동일 서술 유지)
  - 근거: git log -- external_api/CLIENT-HANDOFF.md(b7dd786 2026-06-28); git log --name-only 8e41626/bfadb46/c5710fa

### .docs/Architectures/external_api/README.md

- **서술**: '후속·미구현 항목' 목록에 'JWT refresh' 포함
  - **실측**: POST /api/v1/user/auth/refresh (refresh 쿠키 검증 + family 회전 → 새 access/refresh, 204) 가 구현·서빙 중이고 openapi.nexus.json paths 에도 포함
  - 근거: external_api/README.md:138 vs 100.Nexus/src/router.py:358-375 · openapi.nexus.json /api/v1/user/auth/refresh
- **서술**: '후속·미구현 항목' 목록에 'JWT refresh' 를 미구현으로 나열 (line 138)
  - **실측**: POST /api/v1/user/auth/refresh 가 refresh family 회전(재사용 감지→family revoke+401, 동시 갱신 204)까지 완전 구현되어 있고, 같은 폴더의 CLIENT-HANDOFF.md·openapi.nexus.json 은 이를 ✅ LIVE 로 게시
  - 근거: 100.Nexus/src/router.py:358-384(auth_refresh — rotate_refresh_family); CLIENT-HANDOFF.md:55

### .docs/Features/CONCEPT_MATURITY_FLOW.md

- **서술**: 말미 잔재 참조가 DIRECTOR-R00-RESIDUALS 의 예시로 '(status=satisfied 자동 처리, manifest.context enum 미정의 등)' 을 든다.
  - **실측**: 현행 DIRECTOR-R00-RESIDUALS.md 의 open 4건에 'manifest.context enum 미정의' 항목이 없음 (satisfied 건만 잔존).
  - 근거: .docs/Features/CONCEPT_MATURITY_FLOW.md:238 vs .docs/Issues/DIRECTOR-R00-RESIDUALS.md 전문

### .docs/Features/DRAWING_FLOW.md

- **서술**: P02.R12 흐름을 'step 0,1: generate_drawing_list + review_drawing_list', 'P02 가 merge_renders + aggregate_inspect 처리', 'step 14: drawings_summary' 로 서술.
  - **실측**: 실제 P02.R12 는 14 step(index 0~13)이고 step 명(instructions ref 기준)은 list_figures / review_figures / trigger_numerals / review_numerals / numerals_decision / trigger_claims_mapping / review_claims_mapping / trigger_dl_codegen / review_dl_code / trigger_render / review_render / trigger_vision_check / consolidate_inspection / finalize. generate_drawing_list·merge_renders·aggregate_inspect·drawings_summary 라는 step 은 없고 step 14 도 존재하지 않음(마지막 = index 13 finalize).
  - 근거: @pipelines/02.director/P02.R12.DRAWING_ORCHESTRATION.pipeline.json steps[0..13] instructions.reference 실측
- **서술**: 흐름도가 P02.R12 step 2 에서 P04.R10 로, step 7-8 에서 P05.R00 로 dispatch 하고, 검수 fail 시 'P04.R10 재 dispatch'·'P05.R00 재 dispatch' 한다고 서술.
  - **실측**: dispatch 는 chain 말미 dispatch_to 단일 메커니즘(step 단위 dispatch_to 는 Step schema 에 없음)이고, P02.R12 의 dispatch_to.actions = [[P02.R99.CENTRAL_AGENT],[P02.R12 self]](max_self_recursion 2) 2개뿐 — 현행 pipeline JSON 에 P02.R12→P04.R10/P05.R00 배선이 없음. (P04.R11→P02.R12, P05.R10→P06.R00, P06.R00→{P02.R12|P05.R00} 배선은 실재.)
  - 근거: @pipelines/02.director/P02.R12.DRAWING_ORCHESTRATION.pipeline.json dispatch_to 실측, @contracts/_shared/pipeline-definition.schema.json $defs.Step properties(dispatch_to 없음), 200.DRO/src/dispatch_resolver.py:22-66
- **서술**: P04.R10.EXTRACT_NUMERALS 를 '도면별 self-recursion' 으로 서술.
  - **실측**: P04.R10 의 dispatch_to.actions = [[P04.R11.CLAIMS_WITH_NUMERALS]] 단일 — self-recursion 배선 없음.
  - 근거: @pipelines/04.thinker/P04.R10.EXTRACT_NUMERALS.pipeline.json dispatch_to 실측
- **서술**: P05.R10 의 tool step drawing.render 가 'PlantUML CLI / OpenSCAD CLI / SchemDraw / SMILES' 도구별 dispatch 라고 서술 (도구 매핑 표에도 화학=SMILES, 기계 상세=CadQuery 기재).
  - **실측**: drawing.render 의 renderer map(_RENDERERS) = plantuml / mermaid(→plantuml alias) / openscad / schemdraw 4종 — SMILES·CadQuery renderer 는 코드에 없음. P05.R00 의 첫 step 도 문서의 select_tool 이 아니라 choose_tool.md.
  - 근거: 300.Actor/src/tools/drawing/__init__.py:104-108, @pipelines/05.crafter/P05.R00.GENERATE_DL.pipeline.json steps[0].instructions.reference

### .docs/Issues/DIRECTOR-R00-RESIDUALS.md

- **서술**: #2: P03 research/rejection-cases·P06 evaluation dialog 는 'contract schema 없음', 위치 '@contracts/_shared/runtime/03.finder/dialog/ (디렉토리 자체 없음)'.
  - **실측**: schema 파일은 실재 — @contracts/_shared/runtime/03.finder/{research,rejection-cases}.runtime.schema.json 및 06.inspector/evaluation.runtime.schema.json (2026-06-09 커밋부터). 단 'dialog write 시 validation 없음' 자체는 유효 — CM 은 이름 allowlist 검사(_validate_dialog, vm.DIALOG_NAMES)만 하고 내용 schema 검증은 안 함.
  - 근거: @contracts/_shared/runtime/ find 실측, 400.CM/src/router.py:94-100·789-812, git log fe6b47b(2026-06-09)

### /home/ubuntu/workspace/repository/engine-prototype/.claude/rules/onboarding.instructions.md

- **서술**: §3 디렉토리 구조의 @deployment/ 설명이 topology.yaml + knobs.yaml + engine.config.yaml + engine-config.schema.json + profile.stack.yaml 5개만 나열
  - **실측**: @deployment/ 에는 media.config.yaml (committed, 미디어 업로드 제한·presign TTL — Nexus·CM 에 /etc/media.config.yaml 마운트) + media-config.schema.json (committed) 도 존재
  - 근거: git ls-files @deployment/ 결과, /home/ubuntu/workspace/repository/engine-prototype/@deployment/media.config.yaml:1-15, compose.yaml:36-41
- **서술**: onboarding.instructions.md:202 — "make endpoint ws # 특정 phase 만 (health/info/account/works/auth/work_resources/ws/ws_tape/error_envelope/secure)" — 열거 10개
  - **실측**: phase 는 11개 — 열거에 output phase(output/draft build·preview·download + proposal 501 검증, all_phases.py:438 phase_output) 가 누락
  - 근거: tests/endpoint/endpoint/cli.py:23-36 (_ALL_PHASES 에 "output" 포함), tests/endpoint/endpoint/phases/all_phases.py:438,849

### /home/ubuntu/workspace/repository/engine-prototype/README.md

- **서술**: make validate — 'JSON 산출물 schema · cross-ref · tool registry (정적, 14 stage)' (README.md:63)
  - **실측**: validate stage 모듈은 stage_01~06 + stage_10~15 로 최고 번호 15 (stage_15_parallel_shape.py 존재). Makefile help 와 onboarding.instructions.md 도 '15 stage' 로 표기
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/validate/validate/stages/stage_15_parallel_shape.py, tests/validate/validate/cli.py:44-55, Makefile:48
- **서술**: README.md:63 — "make validate # JSON 산출물 schema · cross-ref · tool registry (정적, 14 stage)"
  - **실측**: validate 는 15 stage — cli.py 요약표에 Stage 1~15 하드코딩, 실행 출력 '✅ validate PASS — 15 stage 모두 통과.' (stage_15_parallel_shape 포함)
  - 근거: tests/validate/validate/cli.py:203-219 + `cd tests/validate && uv run python -m validate` 실행 출력. Makefile:48·92 와 tests/validate/README.md:21 은 이미 15 stage 로 표기
- **서술**: README.md:69 — "make endpoint # 외부 API (REST + WS) contract e2e (10 phase)"
  - **실측**: endpoint phase 는 11개 — _ALL_PHASES = [health, info, account, works, auth, work_resources, output, ws, ws_tape, error_envelope, secure]
  - 근거: tests/endpoint/endpoint/cli.py:23-36, tests/endpoint/endpoint/phases/all_phases.py:839-853. verification.md:197 은 '11 phase' 로 표기

### 100.Nexus/src/config.py:57-59

- **서술**: connect 후 이 시간(또는 SECURE 토큰 만료 중 이른 쪽)에 도달하면 소켓 close
  - **실측**: router 의 WS deadline 은 수명 cap 단독 — access 토큰 만료(exp)에 묶지 않음이 주석으로 명시된 구현 (C1f).
  - 근거: 100.Nexus/src/router.py:1107-1109

### @contracts/README.md

- **서술**: manifest.contract.yaml 은 'codegen 입력' 이며 새 contract 추가 시 항목 추가 '(codegen 이 읽음)'
  - **실측**: repo 내에 manifest.contract.yaml 을 읽는 코드/스크립트 0건 (README 자신도 runtime validator 는 파일명 rglob 이라 명시 — manifest 는 실질 사람용 인벤토리만)
  - 근거: grep -rn "manifest.contract" (*.py/*.yaml/*.toml/Makefile) → 0건; shared/venezia_contracts/loader.py rglob 방식

### @contracts/_shared/chain_manifest.schema.json

- **서술**: 저장 경로를 sessions/{user_id}/{work_id}/chains/{chain_id}/manifest.json · .../chains/{chain_id}/rts/{rt_id}.json 로 서술
  - **실측**: 실제 key builder 는 runtime/{NN}.{persona}/{chain_id}/manifest.json · .../rts/{rt_id}.json — chains/ 최상위 디렉토리는 scaffolding 에 없음
  - 근거: shared/venezia_memory/__init__.py:247-258 (chain_dir/chain_manifest_key) · shared/venezia_memory/scaffolding.yaml runtime.persona.chain 정의

### @knowledge/README.md

- **서술**: '현재 포함' 표에 classification/ 만 있고, drafting/·rejections/ 는 '향후 (예정)' 섹션에 나열
  - **실측**: drafting/ (2026-05-05 추출·요약 완료) 과 rejections/ (layer 1+2+3 빌드 완료) 가 실존하며 빌더(manual-indexer·rejections-indexer)·Makefile 타깃·런타임 로더까지 배선됨
  - 근거: @knowledge/README.md:11-21 vs @knowledge/drafting/version.json·@knowledge/rejections/version.json·Makefile:338-374

### @knowledge/rejections/README.md

- **서술**: Layer 1 트리거 = '매 director 라운드 (system_prompt 정적 prefix)' ✅, Layer 3 = 'director가 1회 fetch → contexts/rejection-cases.json 캐시' ✅ 로 상태 표기
  - **실측**: 주입 메커니즘(claude.py 의 inject_knowledge 키 해석)은 존재하나 그 키를 쓰는 pipeline/설정이 0건이고, cases Chroma 인덱스를 읽는 런타임 코드·등록 tool 도 0건 — 자산 빌드는 완료, 런타임 배선은 by-section(Layer 2, P02.R10 tool step) 만 확인됨
  - 근거: @knowledge/rejections/README.md:7-11 vs grep inject_knowledge @pipelines·@deployment 0건 · grep chroma 300.Actor/src 0건 · @register 전수 목록

### @pipelines/README.md

- **서술**: 디렉토리 트리에 01.buddy "P01.R*.pipeline.json # 10 entry/sub pipelines" (line 14)
  - **실측**: 01.buddy 의 pipeline.json 은 P01.R00.CHAT_CONVERSATION 1개
  - 근거: find @pipelines/01.buddy -name '*.pipeline.json' → 1개; @pipelines/README.md:14
- **서술**: 디렉토리 트리에 02.director "P02.R*.pipeline.json # 7 entry/sub pipelines" (line 17)
  - **실측**: 02.director 의 pipeline.json 은 8개 (R00/R10/R11/R12/R13/R20/R21/R99)
  - 근거: find @pipelines/02.director -name '*.pipeline.json' → 8개; @pipelines/README.md:17
- **서술**: $.user_input.<key> = "`POST /messages` 로 들어온 사용자 payload (content / media / context_hint)" (line 88)
  - **실측**: DRO 표면에 POST /messages 없음 (internal surface = /control/spawn·/control/output·/events·/health). user_input 은 /control/spawn 의 trigger payload 에서 읽으며(orchestrator), 현행 Nexus spawn 은 trigger 로 {"kind":"user_message"} 만 전달
  - 근거: 200.DRO/src/orchestrator.py:63,82; grep '/messages' 200.DRO/src/router.py 0건; 100.Nexus/src/message_flow.py:94
- **서술**: cross-persona 협력 경로 (1) = "DRO 의 user-driven 동시 enqueue (P01+P02 평행)" (line 45)
  - **실측**: user-driven spawn 의 결정·트리거 주체는 Nexus message_flow(ENGINE_MODE 판정 포함)이고 DRO 는 /control/spawn 수신 후 admission+enqueue — onboarding/project instructions 는 "Nexus 의 user-driven spawn" 으로 기술
  - 근거: 100.Nexus/src/message_flow.py:73-105; 100.Nexus/src/config.py:23-24

### @pipelines/manifest.pipeline.yaml

- **서술**: P02.R12.DRAWING_ORCHESTRATION = "4 step: (0)~(3)" (manifest line 59, pipeline description 동일)
  - **실측**: steps 배열의 step 객체는 14개(전부 LLM step, .md 14개와 1:1) — "4" 는 문언상 step 수와 불일치(단계 묶음 서술)
  - 근거: @pipelines/02.director/P02.R12.DRAWING_ORCHESTRATION.pipeline.json steps 파싱=14; manifest.pipeline.yaml:59; 동 파일 description(line 2)

### shared/venezia_media_config/__init__.py

- **서술**: "Nexus(업로드 게이트·소유권 검증)·CM(presigned 서명) 이 런타임 read" — compose.yaml:36 주석도 "(Nexus·CM 만)" 동일 서술.
  - **실측**: 400.CM/src 에 venezia_media_config import 0건. CM 의 presign_put/presign_get 은 ttl 을 함수 파라미터로 받고(400.CM/src/store.py:537,569), TTL·제한값 read 는 Nexus router 만 수행. 마운트 자체는 nexus·cm 양쪽에 존재.
  - 근거: grep venezia_media_config 400.CM/src → 0건; 400.CM/src/store.py:537,569; 100.Nexus/src/router.py:842,896; compose.yaml:110,147

### shared/venezia_memory/scaffolding.yaml + shared/venezia_memory/__init__.py

- **서술**: scaffolding.yaml:12 "conversation = 00.dro/conversation.json (DRO writer, P01 buddy 아님)", __init__.py:220 conversation_key docstring "writer = DRO".
  - **실측**: 실측 writer 는 Nexus message_flow 가 user turn append(100.Nexus/src/message_flow.py:58, CM 경유) + Actor tool cm.append_conversation 이 P01 assistant turn append(300.Actor/src/tools/cm/__init__.py:72-115). project.instructions.md 데이터 흐름 서술(Nexus user turn + P01 assistant turn)과는 일치 — venezia_memory 안의 주석·docstring 만 옛 서술.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/100.Nexus/src/message_flow.py:40-58; 300.Actor/src/tools/cm/__init__.py:72-115

### shared/venezia_memory/scaffolding.yaml:42

- **서술**: refresh-tokens/{user_id}/{family_id}.json = { family_id, user_id, current_jti, issued_at, rotated_at, revoked }
  - **실측**: 실제 기록에는 prev_jti 필드가 추가로 항상 포함되고(최초 write 시 None), revoke 시 revoked_at 필드도 추가된다.
  - 근거: 400.CM/src/store.py:346-358 (write_refresh_family rec 에 prev_jti), 384-386,395-397 (revoked_at)

### tools/rejections-indexer/README.md

- **서술**: "PR-B (Layer 2 by-section), PR-C (Layer 3 RAG)는 후속" · "make build-rejections # 전체 (현재 = summary만)"
  - **실측**: cli.py 의 build = summarize + by-section 이고 cases 서브커맨드(PR-C)도 구현됨. 산출물 by-section/A..H.md + cases/chroma.sqlite3 (256건 인덱싱) 존재, version.json layer="1+2+3"
  - 근거: tools/rejections-indexer/README.md:21,33-35 vs rejections_indexer/cli.py:31-59 · @knowledge/rejections/version.json

---

## 5. 영역별 실측 데이터 (README 작성 재료 전량)

### 100.Nexus

100.Nexus 는 유일한 외부 게이트웨이로, router.py 에 /api/v1 REST 32개 + WebSocket 1개, main.py 에 GET /health 1개가 있다. 인증은 google/naver/kakao 3-provider federated OAuth(PKCE S256) + httpOnly 쿠키(nx_access/nx_refresh/nx_pkce) 기반이며 refresh 는 family(fid+jti) 회전, AUTH_MODE 는 OPEN(고정 user_id)/SECURE 2모드다. WS 는 /api/v1/works/{work_id}/thread/stream 단일 경로에서 inbound 는 message.send 1종(correlation_id 멱등, CM idempotency store dedup)이고 server push 는 9종 이벤트(envelope v2, 키별 seq + replay buffer 200 + since_seq replay)다. 사용자 메시지 1건은 write_user_turn(CM conversation append) → spawn_root_chains(P01 항상 + ENGINE_MODE=FULL 이면 P02, chain_id 는 correlation_id 에서 uuid5 결정적 도출)로 처리된다. openapi_url 은 "/api/v1/openapi.json" 이고 호스트 publish 포트 59100 이라 README 의 URL 주장은 실측과 일치한다. 문서 어긋남은 project.instructions.md 의 output/draft "빌드 기능 미구현 placeholder" 서술(실제는 DRO /control/output 위임 구현)과 내부 RAW event 목록의 output_ready 누락 2건이 확인됐다.

- **REST 엔드포인트 개수** — router.py 의 @router 데코레이터는 총 33개 — REST 32개 + WebSocket 1개. main.py 의 GET /health 를 더하면 HTTP 엔드포인트 총 33개 (/api/v1 REST 32 + /health 1) + WS 1.
  - 근거: 100.Nexus/src/router.py:208-1079, 100.Nexus/src/main.py:89-91
- **REST — info (2)** — GET /api/v1/info/providers (SUPPORTED_PROVIDERS 목록), GET /api/v1/info/attributions (OSS·AI·저작권 고지).
  - 근거: 100.Nexus/src/router.py:208-221
- **REST — user/auth (6)** — GET /api/v1/user/auth/{provider}/authorize · GET /api/v1/user/auth/{provider}/callback (302) · POST /api/v1/user/auth/{provider}/connect (200) · DELETE /api/v1/user/auth/{provider} (204 멱등) · POST /api/v1/user/auth/refresh (204) · POST /api/v1/user/auth/logout (204 멱등).
  - 근거: 100.Nexus/src/router.py:279-400
- **REST — user/account (3)** — GET /api/v1/user/account · GET /api/v1/user/account/alias (ETag 동반) · PUT /api/v1/user/account/alias (If-Match 필수 — 무헤더 428, 불일치 412).
  - 근거: 100.Nexus/src/router.py:418-456
- **REST — user/works (2)** — POST /api/v1/user/works (201 + Location, Idempotency-Key 지원 — replay/busy 409) · GET /api/v1/user/works (목록, 최근 활동 순 정렬).
  - 근거: 100.Nexus/src/router.py:480-544
- **REST — works 진입/meta (3)** — GET /api/v1/works/{work_id} ({work_id,title} 경량 진입) · GET /api/v1/works/{work_id}/meta (ETag) · PATCH /api/v1/works/{work_id}/meta (title rename, If-Match 필수 428/412).
  - 근거: 100.Nexus/src/router.py:552-618
- **REST — phase (2)** — GET /api/v1/works/{work_id}/phase (state = discovery/ready/drafting/complete — maturity overall_score ≥ 0.7 이면 ready, drafting 에서 draft.docx 존재 시 complete) · PATCH /api/v1/works/{work_id}/phase (무본문, discovery→drafting 전이만).
  - 근거: 100.Nexus/src/router.py:200,627-671
- **REST — thread (1)** — GET /api/v1/works/{work_id}/thread/messages — cursor 페이지네이션 (before=<message_id>, limit 1~200 default 50). message id = conversation 내 0-based 위치 파생값 (저장 안 함).
  - 근거: 100.Nexus/src/router.py:674-698
- **REST — estimate (3)** — GET /api/v1/works/{work_id}/estimate/roadmap · GET /api/v1/works/{work_id}/estimate/maturity (미계산 시 shaped null) · PATCH /api/v1/works/{work_id}/estimate/roadmap/{item_id} (body {value}, CM atomic 갱신 status=satisfied+answer 후 handle_message 로 chain spawn).
  - 근거: 100.Nexus/src/router.py:701-774
- **REST — media (4)** — POST /api/v1/works/{work_id}/media (201 presigned POST 티켓, Idempotency-Key, MIME allowlist + work 당 상한) · GET .../media (목록) · GET .../media/{media_id} (메타+presigned 다운로드 URL) · DELETE .../media/{media_id} (204 멱등). 바이트는 브라우저↔S3 직접.
  - 근거: 100.Nexus/src/router.py:811-914
- **REST — output (6)** — POST /api/v1/works/{work_id}/output/draft (200 — DRO POST /control/output 로 docx 동기 빌드 위임 + manifest last_activity 갱신) · GET .../output/draft (docx 다운로드, X-Payment-Token placeholder 게이트) · GET .../output/draft/preview (IOM 마스킹 JSON) · proposal build/preview/download 3종 = 501.
  - 근거: 100.Nexus/src/router.py:959-1071
- **health** — GET /health → {status:"ok", service:"nexus", auth_mode:<open|secure>}.
  - 근거: 100.Nexus/src/main.py:89-91
- **auth — provider 3종** — SUPPORTED_PROVIDERS = ("google", "naver", "kakao"). google 은 httpx_oauth 내장 GoogleOAuth2, naver/kakao 는 BaseOAuth2 generic + 수동 profile fetch (nid.naver.com / kauth.kakao.com).
  - 근거: 100.Nexus/src/auth.py:40,91-144
- **auth — 쿠키** — 쿠키 3종: nx_access (access JWT, Lax, path=/api/v1, 15분) · nx_refresh (refresh JWT, Strict, path=/api/v1/user/auth, 14일) · nx_pkce (PKCE verifier 서명값, max_age 600s). 전부 httpOnly, COOKIE_SECURE default True.
  - 근거: 100.Nexus/src/config.py:43-52, 100.Nexus/src/router.py:234-258,286-294
- **auth — PKCE** — PKCE S256 — /authorize 가 verifier 생성(secrets.token_urlsafe(64)) 후 state 에 바인딩·서명해 nx_pkce 쿠키로 심고, callback/connect 가 검증·1회 consume. state 는 TimestampSigner 서명 (CSRF, max_age 600s).
  - 근거: 100.Nexus/src/auth.py:159-197, 100.Nexus/src/router.py:279-347
- **auth — refresh 회전** — refresh JWT 는 sub+fid(family)+jti. POST /refresh 에서 CM rotate_refresh_family 결과 rotated=새 쿠키 204 / concurrent=현 쿠키 유지 204 / 그 외(재사용·revoked)=family revoke 후 401+쿠키 clear. logout 은 revoke_refresh_family + 쿠키 clear, 항상 멱등 204.
  - 근거: 100.Nexus/src/router.py:358-400, 100.Nexus/src/auth.py:289-300
- **auth — AUTH_MODE** — AUTH_MODE = OPEN|SECURE (profile /etc/deployment.yaml 을 venezia_deployment 가 read, default SECURE). OPEN: 인증 불요 + 고정 OPEN_USER_ID("00000000-0000-0000-0000-00000000open") + JWT secret 미주입 시 dev fallback. SECURE: nx_access 쿠키 JWT(typ=access) 검증, secret 미주입이면 503 fail-close.
  - 근거: 100.Nexus/src/config.py:62-81, 100.Nexus/src/auth.py:38,268-345
- **auth — 식별 레이어** — user_id 는 자체 UUID mint — (provider, provider_sub)→user_id 매핑을 CM 에 영속(get/put_identity), 첫 로그인 시 profile(nickname="발명가-{앞6자}") 생성. PII(실명·이메일) 미저장. JWT sub = 우리 user_id (provider sub 아님). connect 는 타 사용자 기연결 시 409, disconnect 는 identity 먼저 삭제(expected_user_id 소유권 확인) 후 profile 패치.
  - 근거: 100.Nexus/src/auth.py:205-260
- **WS — URL·인증·종료 코드** — WS 경로 = /api/v1/works/{work_id}/thread/stream?since_seq=N (query default 0). 인증 = nx_access 쿠키 (OPEN 은 무토큰 고정 id). accept 후 인증 실패 close 4401, 없는/타인 work close 4404, 최대 수명 cap(WS_MAX_LIFETIME_MINUTES=720분) 도달 시 close 1001. 연결 시 그 (user,work) 키의 DRO SSE consumer 를 ref-count 로 acquire, 해제 시 release.
  - 근거: 100.Nexus/src/router.py:1079-1140, 100.Nexus/src/config.py:60, 100.Nexus/src/event_consumer.py:37-60
- **WS — inbound action** — inbound 는 message.send 1종만 — strict frame 검증({action,data}, data={content,correlation_id}만 허용). 그 외 action 은 system.error(validation_failed). 멱등: CM idempotency store 키 message:{work_id}:{correlation_id} + content_hash — done 재수신=재-ack(재-spawn 없음), 같은 id+다른 content=system.error(conflict), in_flight(비충돌)=멱등 재처리. 실패 시 선점 해제(delete_idempotency)로 재시도 재처리. ack = message.received {correlation_id, id} unicast (seq=0).
  - 근거: 100.Nexus/src/ws_inbound.py:56-188
- **WS — envelope·replay** — server push envelope = {type, timestamp, seq, data} (scope/subject_id 없음). seq 는 (user_id,work_id) 키별 monotonic, replay buffer deque(maxlen=200). replay_since: since_seq>0 인데 빈 버퍼/evict/seq 리셋이면 system.resync_required {reason} unicast. 마지막 연결 해제 시 키의 connections/replay/seq GC.
  - 근거: 100.Nexus/src/ws_manager.py:23,50-149
- **event_mapper — client push 이벤트 9종** — Nexus 가 client 로 push 하는 WS 이벤트 type 은 9종: work.progress·message.reply·model.maturity·model.roadmap·output.ready·work.failed (event_mapper), message.received·system.error (ws_inbound unicast), system.resync_required (ws_manager). raw rt_enqueued/rt_progress/rt_result 는 미노출.
  - 근거: 100.Nexus/src/event_mapper.py:88-161, 100.Nexus/src/ws_inbound.py:36-49,179-188, 100.Nexus/src/ws_manager.py:110-120
- **event_mapper — 생성 조건** — work.progress = raw rt_started 마다 {display_status{ko,en}(step.display_status, fallback "진행 중…"), channel(PERSONA_TO_CHANNEL, fallback support)}. message.reply = chain_completed(persona=1) 시 CM conversation 최신 assistant turn {id,text}. model.maturity = chain_completed(persona=2) 시 CM CMM fetch {overall_score,scores,weights} (dict 아니면 미발생). model.roadmap = 동일 조건 CM UR fetch {count}. output.ready = raw output_ready {document_id,filename,size_bytes,preview_url,download_url — URL 은 routes.py 빌더로 enrich}. work.failed = raw rt_error/error 시 sanitize 고정 문구 {message,channel} broadcast (raw 는 log 에만).
  - 근거: 100.Nexus/src/event_mapper.py:27-161, 100.Nexus/src/routes.py:11-18
- **event_consumer — SSE 소비** — (user_id,work_id) 키당 DRO SSE consumer 1개를 멀티탭 공유(ref-count) — 마지막 WS 해제 시 cancel. SSE→asyncio.Queue(maxsize 1000) 버퍼, overflow 는 oldest drop + queue_drops 계측, 끊김 시 1.0s 후 재연결 반복.
  - 근거: 100.Nexus/src/event_consumer.py:21-104
- **message_flow — 사용자 메시지 흐름** — write_user_turn: work-guard(manifest 없으면 404) 후 CM append_conversation 으로 user turn append (correlation_id 를 meta 에 실어 CM 멱등 append) → 메시지 id(0-based) 반환. spawn_root_chains: manifest last_activity_at 패치 후 DRO control_spawn 으로 P01.R00.CHAT_CONVERSATION(persona 1) 항상 + ENGINE_MODE=FULL 이면 P02.R00.CONCEPT_MATURITY(persona 2) spawn. chain_id 는 correlation_id 있으면 uuid5(work_id:correlation_id:p{persona}) 결정적, 없으면(REST roadmap 경로) uuid4. handle_message = 두 함수 일괄 실행하는 비멱등 래퍼 (REST roadmap_submit 전용).
  - 근거: 100.Nexus/src/message_flow.py:33-121, 100.Nexus/src/config.py:23-24
- **config.py 설정 항목** — Settings: OAuth credential 6종(GOOGLE/NAVER/KAKAO CLIENT_ID·SECRET) · JWT_SECRET_KEY · JWT_ALGORITHM=HS256 · ACCESS_TOKEN_EXPIRE_MINUTES=15 · REFRESH_TOKEN_EXPIRE_MINUTES=20160(14일) · COOKIE_SECURE=True · 쿠키 이름 3종(nx_access/nx_refresh/nx_pkce) · SPA_COMPLETE_ROUTE="/auth/complete" · WS_MAX_LIFETIME_MINUTES=720 · AUTH_MODE(profile venezia_deployment.auth()) · ENGINE_MODE(profile venezia_deployment.engine(), FULL=P01+P02 / SMALLTALK=P01만) · CM_URL/DRO_URL 은 venezia_topology.service_url property. 모듈 상수 P01_ENTRY/P02_ENTRY.
  - 근거: 100.Nexus/src/config.py:23-98
- **main.py — FastAPI app** — openapi_url="/api/v1/openapi.json" (실측). title="100.Nexus — mypage (auth + account + work CRUD/metadata)", version="1.0.0", servers=[{url:"https://{host}", host default "api.venezia.example"}]. custom openapi 가 alias PUT·meta PATCH 의 If-Match 를 required 로 승격 + 428 응답 명시. lifespan 종료 시 cm_client aclose.
  - 근거: 100.Nexus/src/main.py:26-86
- **README openapi URL 검증** — README 의 "http://localhost:59100/api/v1/openapi.json" 주장은 실측과 일치 — main.py openapi_url="/api/v1/openapi.json" + nexus host publish port 59100 (topology.yaml nexus host_publish_port 59100, compose ports "${NEXUS_PUBLISH_PORT}:${NEXUS_PORT}").
  - 근거: 100.Nexus/src/main.py:41, @deployment/topology.yaml:29, compose.yaml:97-98, README.md:76
- **WS 수명과 토큰 무관** — WS 소켓 deadline = connect + WS_MAX_LIFETIME_MINUTES cap 단독 — access 토큰 exp 에 묶지 않음 (handshake 시점 인증 후 cap 까지 유지).
  - 근거: 100.Nexus/src/router.py:1107-1109

### 200.DRO

200.DRO 는 단일 포트(:59200)의 순수 내부 chain executor 로, HTTP 표면은 POST /control/spawn(202) · POST /control/output(docx 빌드, 200) · GET /events/{user_id}/{work_id}(RAW SSE) · GET /health 4개다. chain 실행은 run_chain facade(producer — chain 생성·RT 일괄 enqueue·worker 깨움)와 (user_id, work_id, persona) 키별 단일 worker(chain-at-a-time 직렬 소비, idle 30s 후 자기 제거) 구조이며, admission 잠금 안에서 chain_id 멱등 drop 과 같은 (persona, pipeline_id) pending 중복 코얼레싱(D-1)을 수행하고, startup 시 CM 의 미완 chain 을 resume 한다. Actor 호출은 unified 단일 actor 직결로 503 포화 시 시간예산(DISPATCH_RETRY_BUDGET_S=1200s) 안에서 지수 backoff(계수 1.0s, 상한 30s) 무한 재시도한다. RAW SSE 이벤트는 (user_id, work_id) 키별 monotonic seq 로 8종(rt_enqueued/rt_started/rt_progress/rt_result/rt_error/chain_completed/output_ready/error)을 발사하며 replay 버퍼는 없다. pipeline 은 P{NN} 파일명 정규식·legacy 키 집합·legacy instructions 형식·cross-persona llm_tool 을 전부 RuntimeError 로 fail-loud 하고, dispatch_resolver 는 max_self_recursion 기본 3 으로 self-call 을 가드한다. mocks/dro_app 은 실 표면 동형의 stateless mock 으로 tests/data/dro-tapes 의 tape playlist 를 (user,work,pipeline) cursor 로 순차재생한다.

- **외부 표면** — router.py 의 endpoint 는 POST /control/spawn(202), POST /control/output(200), GET /events/{user_id}/{work_id}(SSE) 3개이고, GET /health 는 main.py 에 정의(응답 {status, service:"dro", llm_mode}). 이외 라우트 없음. FastAPI openapi 는 /api/v1/openapi.json 으로 노출.
  - 근거: 200.DRO/src/router.py:42,88,129; 200.DRO/src/main.py:48,54-60
- **control/spawn 계약** — body 는 user_id/work_id/pipeline_id/chain_id(str)+persona(int) 필수 — 아니면 400 validation_failed. persona 1-6 범위 밖도 400. pipeline_id 는 수신 즉시(202 전) short-form 해소·존재 검증 — AmbiguousPipelineId→409 pipeline_ambiguous, 미존재→404 pipeline_unknown. trigger 는 optional dict(기본 {"kind":"control_spawn"}). chain_id 는 Nexus 발급값 유지, 응답 {chain_id}. 인증 없음(내부망 신뢰).
  - 근거: 200.DRO/src/router.py:43-85
- **control/output 흐름** — variant="draft" 만 허용(그 외 400). CM 에서 IOM fetch — None 이면 404 content_not_ready. drawing manifest fetch 후 PatentDocxGenerator().generate() 를 asyncio.to_thread 로 오프로드해 docx 합성 → cm.upload_document 로 draft.docx 업로드 → 응답 {document_id:"draft", filename:"draft.docx", size_bytes} → RAW output_ready 1건 emit. chain/RT/worker 미경유 동기 단발 변환.
  - 근거: 200.DRO/src/router.py:88-126
- **docx 생성기** — PatentDocxGenerator.generate(iom, drawing_manifest) 가 python-docx 로 BytesIO 반환. IOM 의 bibliographic/specification/claims/abstract 를 사용해 표지(특허출원서)·명세서·청구범위·요약서 4부를 page break 로 구분 구성. A4 페이지, 본문 폰트 맑은 고딕(east-asian)/Times New Roman.
  - 근거: 200.DRO/src/docx_generator.py:22-23,26-55,59-66
- **worker 모델** — (user_id, work_id, persona) 키별 단일 worker 를 _WORKERS dict + _REGISTRY_LOCK 으로 관리. lazy 생성(ensure_worker)·wake=asyncio.Event·큐 비면 _IDLE_GRACE_S=30.0s 대기 후 registry lock 안 double-check 하고 자기 제거. worker 는 CM persona 큐(pending head)의 chain 을 한 번에 하나씩 _drive_chain 으로 끝까지 구동(chain-at-a-time 직렬) — 인메모리 큐 없음, CM 큐가 진실.
  - 근거: 200.DRO/src/worker.py:43,51-77,126-203
- **run_chain producer** — run_chain 이 모든 chain 진입의 단일 facade: pipeline_id resolve(short-form 허용)+load, persona resolve(인자 우선, else pipeline.persona — 1-6 아니면 RuntimeError), chain_id(인자 우선, else uuid4), CM create_chain, build_chain_context 로 결정적 context 합성 후 _enqueue_all_rts 로 전 step 의 RT 를 persona 큐에 pre-push(각각 rt_enqueued RAW), 마지막에 ensure_worker + wake.set(). Nexus root chain 과 dispatch_to 후속이 동일 경로.
  - 근거: 200.DRO/src/worker.py:424-498; 200.DRO/src/orchestrator.py:50-88,185-253
- **admission dedup** — run_chain 은 (user,work,persona) 별 _admission_lock 안에서 두 가지 dedup 수행: (1) 멱등 — 인자 chain_id 가 이미 존재(any status)하면 drop + trail spawn_duplicate_chain_id 후 chain_id echo, (2) D-1 코얼레싱 — 같은 (persona, pipeline_id) 의 status=pending chain 존재 시 create 없이 drop + 그 대기 chain trail 에 spawn_coalesced 기록(RAW 무신호).
  - 근거: 200.DRO/src/worker.py:376-416,449-490
- **재시작 자동복구** — startup lifespan 이 resume_active_chains 호출 — cm.list_active_chains 로 전 세션 미완(pending/active) chain 을 각 worker 의 resume set 에 등록+깨움. resume 구동 시 _rehydrate_done_steps 가 trail 의 rt_enqueued(step_id↔rt_id)에서 state=done RT output 을 context["steps"] 로 복원(LLM structured unwrap 동형)해 _run_one_step 이 done step 을 skip, 미완 step 은 재실행.
  - 근거: 200.DRO/src/main.py:29-33; 200.DRO/src/worker.py:95-118,162-174,211-234,270-274; 200.DRO/src/orchestrator.py:148-152
- **chain 실패 처리** — _drive_chain 은 초기구간 포함 모든 실패를 chain status=failed patch(best-effort) + RAW error emit 으로 처리(A-5). chain 구동 종료 후 _drain_chain_pending 이 그 chain 의 잔여 pending RT 를 pop 해 state=failed("chain aborted before dispatch") 마킹 + lease release. 성공 시 status=done patch + trail chain_completed + RAW chain_completed emit.
  - 근거: 200.DRO/src/worker.py:135-156,346-372
- **병렬 step fan-out** — steps 안 nested list = 정적 병렬 그룹 — trail parallel_started/parallel_done 사이에서 asyncio.gather 로 그룹 내 step 동시 실행. step 은 instructions(LLM step) XOR tool(tool step) — 둘 다 있거나 둘 다 없으면 RuntimeError.
  - 근거: 200.DRO/src/orchestrator.py:108-137,153-172
- **tool=RT 통일** — tool step 도 RT — _pop_or_create_step_rt 로 큐 pop, RT in_flight/done/failed patch, trail rt_started/rt_completed/rt_failed + tool_call_started/done/failed, RAW rt_started/rt_result/rt_error emit 이 LLM step 과 대칭. cm./staging./maturity./roadmap. 접두 tool 은 params 에 user_id/work_id 자동 주입. tool step 의 inject_context 는 orchestrator 가 cm:// 를 CM pointer fetch(RFC 6901)로 직접 해소하며 dot-path 표기는 RuntimeError.
  - 근거: 200.DRO/src/orchestrator.py:436-465,590-642,645-829
- **dispatcher 재시도 상수** — DISPATCH_TIMEOUT_S=1200.0(단일 dispatch HTTP timeout), BUSY_BACKOFF_S=1.0(지수 계수), BUSY_BACKOFF_MAX_S=30.0(delay 상한), DISPATCH_RETRY_BUDGET_S=1200.0(포화 대기 총 예산). Actor /dispatch 503→AllActorsBusy 로 시간예산 안 지수 backoff 무한 재시도(횟수 상한 없음), 그 외 4xx/5xx·연결 실패는 ActorError 즉시 raise. dispatch_tool(POST /tool/{name}, timeout 기본 60s)도 503 에 동일 backoff, 404 는 "tool not registered" ActorError. 큐 lease ttl = DISPATCH_RETRY_BUDGET_S + DISPATCH_TIMEOUT_S.
  - 근거: 200.DRO/src/config.py:20-24; 200.DRO/src/dispatcher.py:53-115,118-181,184-214; 200.DRO/src/orchestrator.py:448
- **Actor 직결** — ACTOR_URL/CM_URL 은 venezia_topology.service_url("actor"/"cm") 로 derive — unified 단일 actor 직결(구 persona 후보 풀/fallback 폐기). dispatch body 에 persona 를 실어 Actor 가 persona sub-folder 를 직접 read.
  - 근거: 200.DRO/src/config.py:33-41; 200.DRO/src/dispatcher.py:60-74
- **event_sse broker** — _RawEventHub 가 (user_id, work_id) 키별 subscriber asyncio.Queue 목록과 monotonic seq 를 lock 으로 관리. envelope = {type, user_id, work_id, persona, seq, timestamp, payload} + optional step{id, display_status}. 큐 maxsize 1000 — overflow 시 oldest drop, 구독자 없으면 best-effort drop, replay 버퍼 없음(Nexus 소유). SSE 프레임은 event:/data: (ensure_ascii=False).
  - 근거: 200.DRO/src/event_sse.py:29-97; 200.DRO/src/sse.py:13-16
- **RAW 이벤트 타입** — 실제 emit 지점: rt_enqueued(producer pre-push), Actor SSE 소비 시 rt_{type} 동적(rt_started/rt_progress/rt_result/rt_error — rt_started 에 step display_status 동봉), tool 경로 rt_started/rt_result/rt_error, chain_completed·error(worker), output_ready(control/output). 계약 enum 은 8종 rt_enqueued/rt_started/rt_progress/rt_result/rt_error/chain_completed/output_ready/error.
  - 근거: 200.DRO/src/orchestrator.py:199-207,474-487,690,749,803; 200.DRO/src/worker.py:351,366; 200.DRO/src/router.py:125; @contracts/00.dro/raw-sse-event.schema.json:13-22
- **pipeline fail-loud** — 파일명은 정규식 ^P\d{2}\.R\d{2}\.[A-Z][A-Z0-9_]*\.pipeline\.json$ 강제(_index — 위반 시 RuntimeError). _assert_no_legacy_keys 는 top-level 6키{version,$schema,entry,metadata,error_handling,pipeline_id} + step 22키{type,next,system_prompt,input,priority_context_references,available_tools,output_schema,context_manager_reads,mode,over,item_var,task,tasks,bind_results,timeout_per_item,on_error,branches,service,action,calls,response_map,sub_pipeline} 발견 시 RuntimeError. instructions 가 list/str 이면 _assert_no_legacy_instructions RuntimeError. llm_tools 는 allowlist 6종(fetch_dialog/fetch_step_output/fetch_drawing/list_drawings/fetch_outputs/fetch_conversation) 외 발견 시 _assert_no_cross_persona_tools RuntimeError.
  - 근거: 200.DRO/src/pipeline_walker.py:20-64,67-127,130-141
- **pipeline resolve/로드** — resolve_pipeline_id 는 exact match 우선, prefix 매칭 유일하면 full id 반환, 2개+ AmbiguousPipelineId, 0개 KeyError. load_pipeline 은 in-process 캐시 + venezia_pipeline_runtime.load_pipeline_cascaded(4-layer cascading) 후 orchestrator shape 로 coerce(persona_prompt 를 LLM step 의 system_prompt 로 주입).
  - 근거: 200.DRO/src/pipeline_walker.py:147-201,213-229
- **dispatch_resolver** — DEFAULT_MAX_SELF_RECURSION=3. actions 빈 list=exit([]), 길이 1 이면 그대로, >1 이면 last_step_output.dispatch_choice(정수, 범위 검증)로 index 선택. self-recursion 가드 = ancestor_pipeline_ids 내 자기 pipeline_id 등장수+1 > max 이면 그 self-call 만 제외. resolve 실패 시 _drive_chain 이 trail chain_dispatch_failed 기록 후 raise(chain=failed 승격). 후속 chain 은 새 uuid4 chain_id 로 run_chain 핸드오프하며 trigger 에 kind:spawned/parent_outputs/spawned_from/ancestor_pipeline_ids 를 실음 + trail chain_dispatched.
  - 근거: 200.DRO/src/dispatch_resolver.py:15,22-83; 200.DRO/src/worker.py:278-344
- **에러 envelope** — APIError + _envelope 로 전 에러가 {"error": {code, message}} 형태 — errors.install(app) 로 핸들러 장착. mock 도 동형 envelope 사용.
  - 근거: 200.DRO/src/errors.py:34,54,103; 200.DRO/mocks/dro_app/app.py:30-32
- **Dockerfile 이원 stage** — python:3.14-slim 기반 production/mock 멀티스테이지 — compose build.target ${DRO_TARGET}(knob dro=real|fake)가 선택. production 은 shared/ + 200.DRO/src COPY + uv sync, mock stage 는 200.DRO/mocks/ 만 COPY(minimal 의존성, production 과 독립). 포트는 compose 의 $PORT env 주입.
  - 근거: 200.DRO/Dockerfile:1-27,31-50
- **mock(dro:fake) 표면** — mocks/dro_app 은 실 표면 동형 4 endpoint: GET /health(실 동형 + mock:true + pipelines 목록), POST /control/spawn(실 동일 타입검증 400 envelope, playlist 부재 pipeline_id 는 404 pipeline_unknown, 202 후 background tape 재생), POST /control/output(실 동형 검증, canned {document_id:draft, filename:draft.docx, size_bytes:2048} + RAW output_ready emit — 실 docx·CM 미영속), GET /events/{u}/{w}(SSE 실 헤더 동형). CM read/write 0 (stateless).
  - 근거: 200.DRO/mocks/dro_app/app.py:35-106
- **mock tape playlist** — TAPE_DIR(기본 /app/data/dro-tapes, compose 가 tests/data/dro-tapes ro mount)의 {pipeline_id}/{NN-슬러그}.json 을 정렬순 playlist 로 startup 1회 전수 load + 구조 검증(잘못된 tape = 컨테이너 crash fail-loud, type enum 은 비강제). cursor 키 = (user_id, work_id, pipeline_id) — i번째 spawn 이 i번째 tape 재생, 소진 시 마지막 반복. tape event 는 delay_ms 지원, payload 에 chain_id 주입, seq/timestamp 는 hub 가 emit 시 할당. 현재 tape 디렉토리 = P01.R00.CHAT_CONVERSATION, P02.R00.CONCEPT_MATURITY. hub 는 실 event_sse 미러(maxsize 1000, oldest drop) + wait_subscriber(2s) race 보험.
  - 근거: 200.DRO/mocks/dro_app/config.py:7; 200.DRO/mocks/dro_app/tape_player.py:30-98; 200.DRO/mocks/dro_app/hub.py:20-92; tests/data/dro-tapes/
- **lifespan/shutdown** — FastAPI app version 2.0.0. lifespan startup 에 resume_active_chains(best-effort), shutdown 에 worker.shutdown_all(전 worker cancel) 후 CM client aclose. secrets/worker 모듈을 config read 전에 import 해 env 주입.
  - 근거: 200.DRO/src/main.py:17,26-51
- **RT 스키마 검증** — RT 생성 시 venezia_contracts.ContractLoader 로 reasoning_task 계약 검증 — 위반은 실패가 아니라 warning 로그 + trail schema_violation 기록(진행 계속). loader 미가용 시 검증 skip.
  - 근거: 200.DRO/src/orchestrator.py:300-343

### 400.CM (Context Manager)

400.CM 은 FastAPI 앱(main.py, title "Memory Manager" v2.0.0)으로 router.py 에 정확히 76개의 @router 엔드포인트를 보유하며(문서 주장 76개와 일치), 별도로 main.py app 레벨 GET /health 1개가 추가로 존재한다. 저장은 store.py 가 boto3 S3 직접 호출(read/write/patch/media presigned/users 루트)로 수행하고, chain 자료는 chain_store.py(manifest.runtime.yaml 인덱스 + chain manifest/trail.jsonl/rts/agent_state), persona RT 큐는 queue_store.py(pending[]+leases{} lease 장부, lazy 만료 제거)가 담당한다. 부분 R/W 는 jsonpatch(RFC 6902)·jsonpointer(RFC 6901) 라이브러리 기반으로 PATCH=ops array, GET ?pointer= 부분 read 로 표준화되어 있다. S3 키 구조의 단일 소스는 shared/venezia_memory/scaffolding.yaml 이고 venezia_memory 의 key builder 함수들이 이를 로드해 제공한다. 문서와 어긋난 점은 (1) 엔드포인트 묶음 목록의 "inputs" 가 실측 0개(대신 media 4개 존재), (2) "모든 write 는 file_key asyncio.Lock 직렬화" 주장과 달리 lock 은 queue_store·chain_store 의 async 경로에만 있고 store.py 의 sync write 경로는 lock 없이 single-instance no-yield 원자성에 의존한다는 것이다.

- **endpoint 총수** — router.py 의 @router.{get,post,put,patch,delete} 데코레이터는 정확히 76개 (grep -c 실측). 이와 별도로 main.py 에 app 레벨 GET /health 1개가 있어 컨테이너 전체 HTTP 표면은 77개.
  - 근거: 400.CM/src/router.py (grep -c 76), 400.CM/src/main.py:17-19
- **endpoint 묶음별 분류** — 76개 실측 분류: users 13 (identities GET/PUT/DELETE 3 + profiles GET/PUT/PATCH 3 + idempotency GET/PUT/claim/DELETE 4 + refresh-tokens PUT/rotate/revoke 3) · sessions 4 (POST /sessions, GET /sessions/{user_id}, DELETE /sessions/{u}/{w}, GET tree) · manifest/context 3 (GET/PUT/PATCH) · models 14 (manifest 2 + IOM 3 + CMM 3 + UR 2+item PATCH 1 + CDS 3) · drawings 9 (manifest 3 + numerals/dl/figure 각 GET/PUT) · outputs 5 (list, manifest GET/PUT, {filename} PUT/GET) · runtime 인덱스 2 (GET/POST runtime) · admin 1 (GET /admin/active-chains) · conversation 2 (GET, POST append) · media 4 (presign-put, presign-get, list, DELETE) · persona queue 4 (GET, push, pop, release) · dialog 3 (GET/PUT/PATCH) · chain 자료 9 (chain GET/PATCH, trail POST/GET, rts POST, rt GET/PATCH, agent_state GET/PUT) · legacy by-chain 3 (chains/{chain_id} GET, trail GET, rts/{rt_id} GET). 합계 13+4+3+14+9+5+2+1+2+4+4+3+9+3=76.
  - 근거: 400.CM/src/router.py:116-958
- **router — persona 검증** — persona path param 은 'NN.name' dir 형식('01.buddy'~'06.inspector')만 허용(_persona_dir_for, 미등재 400), _persona_int 가 dir명→1..6 변환. dialog 명은 vm.DIALOG_NAMES allowlist 로 검증(_validate_dialog, 미등재 400). chain_id 만 아는 legacy 경로는 manifest.runtime.yaml 에서 persona 를 resolve(_resolve_persona_by_chain, 없으면 404).
  - 근거: 400.CM/src/router.py:63-101
- **store.py — S3 read/write** — boto3 S3 client 싱글톤(_s3), read/write 는 venezia_memory key builder 로 키 생성(literal 금지), .yaml/.yml 확장자는 yaml.safe_dump(ContentType application/yaml)·그 외 JSON(application/json) 직렬화, NoSuchKey/404 는 None 반환. 전체 키를 이미 가진 호출자용 read_by_key/write_by_key 변형 존재.
  - 근거: 400.CM/src/store.py:30-152
- **store.py — media presigned 4종** — presign_put = generate_presigned_post 로 업로드용 presigned POST 발급(content-length-range 0..max_bytes + Content-Type 조건 강제, 로컬 서명), presign_get = media_id prefix 조회(resolve_media_key) 후 generate_presigned_url(get_object) 발급(객체 없으면 None→404), list_media = media/ prefix 전수 + head_object 로 mime 취득(장부 없음, S3 가 진실), delete_media = prefix media/{media_id}. 의 객체 삭제(멱등, 반환=삭제 수). 키 = sessions/{user}/{work}/media/{media_id}.{ext}.
  - 근거: 400.CM/src/store.py:531-623
- **store.py — media presign 입력검증** — presign-put/get 엔드포인트는 _require_fields(media_id/ext/mime)·_as_int(max_bytes/ttl) 로 누락·비정수 body 를 400 처리(KeyError→500 방지 주석 명시). presign_get/list/delete 는 asyncio.to_thread 로 S3 호출, presign_put 은 로컬 서명이라 to_thread 미사용.
  - 근거: 400.CM/src/router.py:48-60,677-716
- **store.py — users 루트 (인증·식별)** — sessions 와 별개의 users/ 루트: identities/{provider}/{sub}.json={user_id}(로그인 인덱스, delete 는 expected_user_id CAS 로 cross-account 오삭제 차단), profiles/{user_id}/profile.json(write 마다 updated_at 스탬프 — alias If-Match/ETag 기준), idempotency/{user_id}/{key_hash}.json(claim 원자 선점: done/in_flight/claimed 3-state, in-flight TTL _IDEM_TTL_S=30초, content_hash 보존), refresh-tokens/{user_id}/{family_id}.json(회전 CAS rotate_refresh_family 결과 5종 rotated/concurrent/reuse/revoked/missing, prev_jti+grace 창 _REFRESH_GRACE_SECONDS=30초로 동시 갱신 포용, reuse 시 family revoke).
  - 근거: 400.CM/src/store.py:227-397
- **store.py — conversation 멱등 append** — append_conversation 은 runtime/00.dro/conversation.json 에 turn append. user turn 의 meta.correlation_id 가 이미 기록돼 있으면 no-op(멱등, A-4), user role 이면 total_user_turns 증가. CM 단일 인스턴스 sync(read→write 무 yield)로 원자성 확보 — asyncio.Lock 미사용.
  - 근거: 400.CM/src/store.py:192-224
- **chain_store.py — chains/* 구조** — chain 자료 = runtime/{persona_dir}/{chain_id}/ 아래 manifest.json + trail.jsonl + rts/{rt_id}.json + agent_state.json. manifest.runtime.yaml 은 페르소나 무관 root 의 chain 인덱스(add 멱등·chain_id 중복 방지). create_chain 은 같은 chain_id 재생성 시 기존 manifest 반환(멱등), venezia_contracts ContractLoader 로 chain_manifest schema 검증(위반 시 trail 에 schema_violation 기록 후 write 는 계속). patch_chain 은 RFC 6902 ops 적용 후 /status·/completed_at 값만 runtime manifest 인덱스에 mirror.
  - 근거: 400.CM/src/chain_store.py:49-239
- **chain_store.py — RT·trail·agent_state** — create_rt 는 state=pending/retry_count=0/max_retries=3/sse_events=[] 기본값 세팅. patch_rt 는 특수 path '/sse_events_append' 를 sse_events array 의 server-side append 로 변환(나머지는 RFC 6902 적용). trail 은 jsonl 1줄 append(read-modify-write, ts 자동 스탬프, application/x-ndjson). agent_state 는 envelope pass-through(CM 은 내용 opaque — persona/updated_at 만 스탬프), 미존재 시 default {persona, schema_version:1, vendor:null, model:null, items:[], updated_at} 반환.
  - 근거: 400.CM/src/chain_store.py:288-385
- **chain_store.py — admin/active-chains** — list_active_chains 는 sessions/ prefix 전수 스캔으로 각 세션의 manifest.runtime.yaml 에서 status가 pending/active 인 chain entry 를 열거 — DRO 재시작 자동복구용(A-3). suffix 는 하드코딩 대신 key builder 에서 도출.
  - 근거: 400.CM/src/chain_store.py:102-140, 400.CM/src/router.py:612-616
- **queue_store.py — persona RT 큐 + lease 장부** — runtime/{persona}/queue.json shape = {pending:[{rt_id,chain_id,enqueued_at}], leases:{rt_id:{chain_id,actor,started_at,expires_at}}, updated_at}. pop 은 pending head(chain_id 지정 시 그 chain 의 첫 entry 만)를 leases 로 이동, lease TTL 기본 DEFAULT_LEASE_TTL_S=2400.0초(DRO 가 lease_ttl_s 전달 가능). 만료 lease 는 push/pop/release 시 lazy 제거(_sweep_expired — GET 은 순수, 별도 데몬 없음). release 는 본인 rt_id 만 해제(멱등). push/pop/release 모두 lock_for(key) asyncio.Lock 으로 직렬화.
  - 근거: 400.CM/src/queue_store.py:1-138
- **lock.py** — FileLockManager 가 resource key 별 asyncio.Lock 1개를 defaultdict 로 보유(같은 파일 직렬·다른 파일 병행), 모듈 싱글톤 _manager + lock_for(key) 로 노출. 총 23줄.
  - 근거: 400.CM/src/lock.py:9-23
- **lock 실제 사용 범위** — lock_for 사용처는 queue_store 3곳(push/pop/release)과 chain_store 7곳(create_chain, add_chain_to_manifest, update_chain_in_manifest, patch_chain, append_trail, patch_rt, put_agent_state)뿐. store.py 의 write/patch/append_conversation/set_array_item_by_id 와 chain_store.create_rt 는 lock 없이 sync(no-yield) 실행의 원자성에 의존(코드 주석에 'CM 단일 인스턴스 + sync = read→write 원자' 명시).
  - 근거: 400.CM/src/queue_store.py:73,99,132; 400.CM/src/chain_store.py:71,93,159,224,270,326,382; 400.CM/src/store.py:175-177,296
- **JSON Patch (RFC 6902)** — store.apply_json_patch 가 jsonpatch 라이브러리로 add/remove/replace/move/copy/test ops array 적용(array 지원, 구 _deep_merge dict-only 폐기 — P-E). PATCH 엔드포인트 body = ops array 로 통일: profile, manifest/context, IOM, CMM, CDS, drawings/manifest, dialog, chain, rt. store.patch 는 결과가 dict 면 last_updated 스탬프. 예외: UR item PATCH(models/user-roadmap/items/{item_id})는 RFC 6902 가 아니라 id 기준 atomic field 병합(set_array_item_by_id — top-level array 의 index 경로 회피, 못 찾으면 404). 의존성 = jsonpatch>=1.33.
  - 근거: 400.CM/src/store.py:67-76,155-186; 400.CM/src/router.py:159-163,317-322,371-374,425-434; 400.CM/pyproject.toml:14
- **JSON Pointer (RFC 6901)** — store.read_pointer 가 jsonpointer 라이브러리로 부분 read(빈 string/'/' = 전체). GET ?pointer= query 지원 엔드포인트 = IOM/CMM/UR/CDS/conversation 5개(invalid pointer → 400). 의존성 = jsonpointer>=3.0.
  - 근거: 400.CM/src/store.py:79-85; 400.CM/src/router.py:349-360,377-388,405-416,437-450,652-662; 400.CM/pyproject.toml:15
- **scaffolding.yaml — S3 키 단일 소스** — shared/venezia_memory/scaffolding.yaml (schema_version 1.0.0) 이 S3 layout 단일 truth source: root_prefix=sessions, entity_path=sessions/{user_id}/{work_id}, root_manifest=manifest.context.yaml, 별개 users 루트(identities/profiles/idempotency/refresh-tokens), namespaces = runtime(manifest.runtime.yaml + 00.dro/conversation.json + {persona_dir}/queue.json + {chain_id}/{manifest.json,trail.jsonl,rts/{rt_id}.json,agent_state.json} + dialog_allowlist) / models(iom·cmm·user_roadmap·concept_discovery_stack 4파일 + manifest.models.yaml) / drawings({drawing_id}/numerals·dl·figure) / outputs / media({media_id}.{ext}, 장부 없음). venezia_memory/__init__.py 가 이를 로드해 PERSONA_DIRS(1~6→01.buddy..06.inspector)·DIALOG_NAMES 와 40여 개 key builder 함수(session_root, queue_key, conversation_key, chain_manifest_key, trail_key, rt_key, agent_state_key, iom_key, media_key 등)를 제공하고, CM 의 store/chain_store/queue_store/router 전부 이 builder 를 경유(직접 literal 없음).
  - 근거: shared/venezia_memory/scaffolding.yaml:1-107, shared/venezia_memory/__init__.py:43-131
- **dialog allowlist** — 페르소나별 누적 dialog allowlist: 02.director=[analysis,decisions,evaluation,workspace], 03.finder=[research,rejection-cases], 06.inspector=[evaluation], 01.buddy/04.thinker/05.crafter=[], 00.dro=[conversation]. router 의 dialog GET/PUT/PATCH 가 이 allowlist 로 400 검증.
  - 근거: shared/venezia_memory/scaffolding.yaml:71-78, 400.CM/src/router.py:94-101
- **config** — Settings = S3_BUCKET(필수) + AWS_REGION(기본 ap-northeast-2), pydantic-settings BaseSettings. main.py 는 import 시 secrets 모듈(AWS Secrets Manager env 주입)을 먼저 로드.
  - 근거: 400.CM/src/config.py:4-11, 400.CM/src/main.py:6-8
- **세션 CRUD** — POST /sessions 는 user_id(미제공 시 uuid4)·work_id·session_id 발급 + manifest.context.yaml 초기화(status=draft, current_phase=discovery, title='발명 {work_id[:8]}', title_source=auto, last_activity_at 포함). GET /sessions/{user_id} 는 S3 CommonPrefixes 스캔으로 work 목록. DELETE 는 ?confirm=true 필수, S3 prefix 전수 삭제(delete_objects 1000개 batch). GET tree 는 probe structure 검증용 실 키 전수 반환.
  - 근거: 400.CM/src/router.py:243-296, 400.CM/src/store.py:403-528

### 300.Actor (unified LLM 워커)

300.Actor 는 P1~P6 전 persona 를 단일 컨테이너로 수락하는 수동 워커로, HTTP 표면은 POST /dispatch (SSE) · POST /tool/{tool_name} · GET /health 3개다. 동시성은 slots.py 의 persona 별 카운터 풀 + /tool 전용 별도 풀이 engine.config cap 을 집행하며 포화 시 즉시 503+Retry-After(1) 를 반환한다. dispatcher 가 CM 에서 RT 와 agent_state(vendor 원형 envelope {schema_version,vendor,model,items}) 를 읽어 composer 로 단일 텍스트 prompt([PERSONA]/[CONTEXT]/[FRAGMENTS]/[TASK]/[DISPATCH_CHOICE_GUIDE]/[RECOMMENDED_FETCH]) 를 합성하고, create_session 이 LLM_MODE(FIXTURE|PRODUCTION, 그 외 fail-loud) 에 따라 FixtureSession 또는 ActorSession(claude/gemini/openai vendor adapter, fallback 1회 + backoff 재시도 + schema retry) 을 만든다. tool registry 는 10개 dir 에 @register 18종이고, fetch dir 는 @register 없이 LLM native function calling 용 fetch_* 6종을 factory(make_fetch_tools) 로 제공한다. mocks/actor_app 은 fixture replay SSE + canned tool 6종 + busy-marker 503 으로 실 표면을 미러한다. 문서 대비 실측 어긋남 2건: project.instructions.md tool 표에 등록 tool 6종 누락, onboarding 의 "fetch_* 7종" 은 실측 6종.

- **표면 — POST /dispatch** — body {chain_id, rt_id, user_id, work_id, persona} 필수(결측 = HTTP 400). persona 슬롯 try-acquire 후 200 SSE 스트림(StreamingResponse text/event-stream). 슬롯 포화 = 503 + ErrorEnvelope(rate_limited, "actor busy (persona slot saturated)") + Retry-After: 1. engine.config 미등재 persona 는 슬롯 없이 진행해 SSE error 이벤트로 거절
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/router.py:25-58
- **표면 — POST /tool/{tool_name:path}** — body {"params": {...}}. 응답: 200 {"status":"success","result":...} · 404 not_found(미등록 tool) · 400 validation_failed(params non-dict 또는 handler TypeError) · 500 internal(handler 예외, 메시지 500자 절단) · 503 rate_limited+Retry-After(tool 풀 포화). 에러는 전부 ErrorEnvelope {"error":{"code","message"}}
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/router.py:85-137
- **표면 — tool=RT 기록** — _record_tool_rt 가 body 에 rt_id/chain_id/persona/user_id/work_id 가 모두 있으면 tool 결과를 CM patch_rt 로 {"output", "state":"done"} 기록(LLM /dispatch 대칭). 식별자 미비 시 no-op, CM 실패는 warning 만(best-effort)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/router.py:61-82,126-128
- **표면 — GET /health** — {status, actor_id, personas(engine_config.persona_ids()), tools(registry 전체 이름), llm_mode, slots(slots.snapshot() — persona/tool 풀의 cap·inflight)} 반환. 라우트는 router 의 2개 + main.py 의 /health 뿐
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/main.py:32-45
- **slots.py — 동시성** — _Pool = asyncio.Lock 보호 카운터형 non-blocking try-acquire. persona 풀 cap = engine.config personas.{id}.max_concurrency (미등재 persona = RuntimeError fail-loud), tool 풀 cap = engine.config tools.max_concurrency 로 dispatch 와 비공유. release 는 음수 가드. snapshot() 이 /health 관측 제공, reset() 은 테스트용
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/slots.py:20-99
- **composer.py — prompt 합성** — compose_prompt 가 단일 텍스트를 [PERSONA] → [CONTEXT](inject_context 자원 fetch 후 inline) → [FRAGMENTS] → [TASK](instructions) → [DISPATCH_CHOICE_GUIDE] → [RECOMMENDED_FETCH](hint 만, fetch 안 함) 순으로 합성. source prefix 는 @knowledge/ 와 cm:// 2종만(이외 ComposerError)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/composer.py:111-116,125-186
- **composer.py — instructions 계약** — instructions 는 객체로 {inline} XOR {reference} 정확히 1키(허용 키 = {inline, reference}). legacy list[str]/string 은 ComposerError fail-loud. reference 는 @pipelines/ prefix 만 지원하고 파일 read 는 lru_cache(maxsize=256)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/composer.py:22,41-100
- **composer 입력의 출처** — 4-layer cascading 머지는 composer 가 하지 않음 — dispatcher 가 RT.input 의 머지 결과 키(persona_prompt/inject_context_spec/recommended_context_spec/fragments/instructions/dispatch_choice_guide)를 그대로 compose_prompt 에 전달. knowledge_root=/app/@knowledge, pipelines_root=/pipelines
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/dispatcher.py:163-175
- **dispatcher.py — SSE 흐름** — SSE 이벤트 순서 = started → (persona 미수락/RT 부재 시 error) → progress{phase: llm_call_started, tools_loaded, fetch_tools} → result(LLM {text, structured}). 처리 중 예외는 SSE error(internal). 성공 시 agent_state PUT + RT PATCH {output, state: done} 후 result. trail 에 llm_input_prepared 이벤트 append(prompt_chars/available_tools/response_schema 유무 등)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/dispatcher.py:42-226
- **dispatcher.py — RT 필수 키** — RT.input 에 inject_context_spec 도 persona_prompt 도 없으면 RuntimeError(구설계 RT.input 폐기 fail-loud). persona 수락 판정 = engine_config.persona_ids() (구 ACTOR_PERSONAS env 폐기)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/dispatcher.py:34-38,84-88
- **dispatcher.py — cm:// fetch** — cm_fetch 지원 resource = invention_object_model / concept_discovery_stack / concept_maturity_model / conversation / user_roadmap (+ dialogs/<persona>.<name>.json). 부분 read 는 RFC 6901 slash pointer, dot-path 표기는 RuntimeError fail-loud, 미지원 resource 도 fail-loud
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/dispatcher.py:120-160
- **llm/create_session** — engine.config persona entry 의 llm{sdk, model} 을 읽고 LLM_MODE(대문자화) 분기: 허용 = {FIXTURE, PRODUCTION}, 그 외 RuntimeError. FIXTURE 는 step_id+pipeline_id 필수 → FixtureSession. PRODUCTION 은 ActorSession 에 fallback_model/effort/llm_settings/retry_cfg(vendor_retry)/defaults_cfg 전부 engine.config 에서 주입 — 코드에 persona 테이블 없음
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/llm/__init__.py:24-75
- **engine_config.py — 로더** — 소스 = /app/engine.config.yaml (ENGINE_CONFIG_FILE env override), lru_cache(1). 필수 섹션 = personas/vendors/tools/defaults, persona 의 llm 필수 키 = sdk/model/fallback_model — 결손·미등재는 전부 RuntimeError fail-loud. 제공 API = persona(pid)/persona_ids()/vendor_retry(sdk)/tools()/defaults()
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/engine_config.py:21-83
- **ActorSession — fallback/retry/schema** — 3단: ① retryable 실패 시 같은 vendor 의 fallback_model 1회(fallback 없음·동일 값이면 raise) ② 각 모델 시도 안 with_backoff(engine.config vendors.{sdk}.retry 의 max_attempts/backoff_seconds, 기본 3회·(2,5,10)s) — permanent 에러 즉시 raise ③ response_schema 있으면 jsonschema Draft7 검증, 실패 시 오류 피드백 prompt 로 재시도(횟수 = defaults.schema_retry, 기본 1), 소진 후도 실패면 _PermanentLLMError
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/actor_session.py:63-93,149-191,242-314
- **ActorSession — effort 번역** — effort 1급 공통 키 → vendor stage 키 번역 = {claude: effort, openai: reasoning_effort, gemini: thinking_level} (_EFFORT_STAGE_KEY). llm_settings 는 vendor 전용 passthrough(adapter 가 아는 키만 read)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/actor_session.py:29,124-128
- **llm/retry.py — 에러 분류** — _classify_llm_error: httpx 429/5xx=retryable, 400/401/403/404=permanent; anthropic·openai SDK 예외 타입별 분류; Google 은 메시지 키워드 기반; unknown 은 보수적으로 retryable. with_backoff 는 _RetryableLLMError 만 catch
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/llm/retry.py:40-178
- **agent_state envelope** — {schema_version: 1, vendor, model, items} — vendor ∈ {claude, gemini, openai, fixture}. items 원형: claude=session transcript entries(JSONL dict), gemini=ADK Event dump, openai=to_input_list items, fixture=평문 {role, content}. parse_agent_state: items 비면 None, legacy 평문 messages = RuntimeError fail-loud. persona/updated_at 스탬프는 CM 몫
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/llm/state.py:1-66
- **컨텍스트 ② — vendor seed/강등** — vendor 일치 시 items 를 native seed(openai 는 openai_seed_items 로 모델 전환 처리), 불일치 시 items_to_plain 텍스트 강등(gemini 타깃 = plain_to_gemini_events, openai 타깃 = 평문 그대로). claude 가 타깃인 강등만 native 주입 불가 → user prompt 앞 preamble. 성공 _invoke 가 export_items() 캡처 → export_state() 가 다음 RT 용 envelope 반환
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/actor_session.py:209-240,296-303,356-362
- **llm/ vendor adapter 4종** — claude.py=ClaudeAgentSession(claude-agent-sdk ClaudeSDKClient, ClaudeTranscriptStore(SessionStore duck-typed)+resume seed) · gemini.py=GeminiAgentSession(google-adk LlmAgent+InMemoryRunner, response_schema→output_schema native, function_tools→LlmAgent.tools callable) · openai.py=OpenAIAgentSession(openai-agents Agent+Runner, reasoning_effort→ModelSettings) · fixture.py=FixtureSession({fixture_dir}/{pipeline_id}/{step_id}.json replay, 파일 미존재 시 echo fallback). 공통 Protocol = llm/session.py AgentSession(vendor/run_stage/export_items/close)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/llm/claude.py:1-30,142-145; src/llm/gemini.py:1-28; src/llm/openai.py:1-27; src/llm/fixture.py:1-40; src/llm/session.py:17-40
- **llm/client.py · knowledge.py** — client.py = get_gemini_client() lru_cache singleton(google-genai, Vertex ENV 기반 — embedding 등 raw client 용, chat 은 ADK 가 자체 생성). knowledge.py = @knowledge/ static text loader(KNOWLEDGE_DIR env 또는 상위 탐색)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/llm/client.py:1-24; src/llm/knowledge.py:1-30
- **tools/ registry 구조** — TOOLS dict + @register decorator + get()/list_available(). import 시 auto-register 대상 dir 10개 = cm/document/drawing/kipris/knowledge/maturity/media/roadmap/staging/vision (fetch 는 auto-register 목록에 없음). tools/ 하위 dir 총 11개(fetch 포함)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/tools/__init__.py:1-41
- **tools/ — @register 전수 (18종)** — kipris.search_patents(:28)·kipris.get_patent_detail(:97) / drawing.plantuml(:149)·drawing.openscad(:154)·drawing.schemdraw(:159)·drawing.render(:164) / vision.image_io(:16)·vision.review_drawing(:29) / document.parse(:17) / media_processor.image_describe(processor.py:102)·media_processor.document_describe(:108)·media_processor.audio_describe(:121)·media_classifier.classify(classifier.py:52) / staging.save(:28) / maturity.compute(:80) / roadmap.persist(:61) / cm.save_drawing_artifacts(:25)·cm.append_conversation(:72) / knowledge.load_rejections_section(:78)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/tools/{kipris,drawing,vision,document,staging,maturity,roadmap,cm,knowledge}/__init__.py + tools/media/{processor,classifier}.py (grep '@register(')
- **tools/fetch — llm_tools 6종** — fetch dir 는 @register 0 — registry tool 이 아니라 LLM native function calling 용. make_fetch_tools(cm, user_id, work_id, persona, chain_id, allowed_names) 가 closure 로 식별자 고정한 6종 반환: fetch_dialog / fetch_step_output / fetch_drawing / list_drawings / fetch_outputs / fetch_conversation. allowed_names 필터(D-3) — dispatcher 가 RT 의 available_tools 선언만 노출, 선언 없으면 fetch 도구 0개
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/tools/fetch/__init__.py:22-80; src/dispatcher.py:104-108
- **config.py** — LLM_MODE·KIPRIS_MODE 는 env 가 아니라 마운트된 profile(/etc/deployment.yaml) 을 venezia_deployment runtime 으로 read 하는 default_factory. FIXTURE_PATH=/app/data/llm-fixtures, KIPRIS_FIXTURE_DIR=/app/data/kipris-fixtures, CM_URL 은 venezia_topology service_url("cm"). 구 ACTOR_PERSONAS env 폐기(수락 집합 = engine.config)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/src/config.py:15-49
- **mocks/actor_app — 표면** — actor:fake 는 /health(실 동형 + mock:true, slots:None) · /dispatch(SSE fixture replay: started→progress→result|error) · /tool(canned) 3표면. persona 수락 = mock 전용 env ACTOR_PERSONAS(default "1,2,3,4,5,6"). 동시성 cap 은 비시뮬레이트(divergence 명기) — 의도적 503 은 busy-marker 전담
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/mocks/actor_app/app.py:40-119; mocks/actor_app/config.py:20-27
- **mocks/actor_app — fixture·busy·canned** — fixture 키잉 = 실 CM RT read(rt_lookup) 의 (pipeline_id, step_id) → tests/data/llm-fixtures 경로 load, miss 는 strict FixtureMiss → SSE error(실 FixtureSession 의 echo fallback 미러 안 함). busy-marker = {BUSY_MARKER_DIR}/{pipeline_id}/{step_id}.json {"times":N} — 처음 N회 503+Retry-After. canned tool 6종 = staging.save / maturity.compute / roadmap.persist / cm.append_conversation / kipris.search_patents / kipris.get_patent_detail (미등록 = 404). mock 의 CM-write 0
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/mocks/actor_app/fixtures.py:1-40; mocks/actor_app/busy.py:1-40; mocks/actor_app/canned.py:120-127; mocks/actor_app/app.py:1-15

### @pipelines

@pipelines 는 DRC chain dispatch graph 정의 영역으로, `_shared/GLOBAL.json` + persona 별 6개 디렉토리(`P{NN}.COMMON.json` + 22개 `*.pipeline.json` + step instructions .md 56개) + `manifest.pipeline.yaml`(사람용 inventory) + `README.md` 로 구성된다. 프로덕션 root spawn 은 Nexus `message_flow.spawn_root_chains` 가 트리거하는 P01.R00.CHAT_CONVERSATION + (ENGINE_MODE=FULL 시) P02.R00.CONCEPT_MATURITY 2개뿐이고, 나머지 chain 은 dispatch_to 그래프로만 이어진다. P02.R00 은 id 0~7 의 8 step(LLM 5 + tool 3, step 2/3/4 는 nested list 정적 병렬)이며 dispatch_to: null 로 self-contained. P03 KIPRIS RAG 는 R00→R01→(self|R02) 로 실측 확인되고, R11 은 R02 가 아니라 R10.ANALYZE_PLAN 에서 dispatch 되며 P02.R99 로 복귀한다. P02.R99.CENTRAL_AGENT 는 1 step + 7-way dispatch 로 파일은 완성돼 있으나 3개 컨테이너 src 에 참조가 전무해 프로덕션 트리거 경로가 없다. 전 pipeline·COMMON·GLOBAL 의 llm_tools 는 현재 모두 빈 배열이며, allowlist(6종 fetch_*)는 schema enum 과 Actor 구현에만 존재한다. 문서 어긋남은 @pipelines/README.md 의 파일 수·$.user_input 출처, manifest 의 P02.R12 step 수, onboarding 의 fetch_* 7종 표기 등 6건 실측됐다.

- **디렉토리 구조 — 전수** — @pipelines/ = manifest.pipeline.yaml + README.md + _shared/GLOBAL.json + 6개 persona 디렉토리(01.buddy/02.director/03.finder/04.thinker/05.crafter/06.inspector). 각 디렉토리에 P{NN}.COMMON.json 1개씩(6개), *.pipeline.json 총 22개(buddy 1 / director 8 / finder 6 / thinker 4 / crafter 2 / inspector 1), step instructions .md 총 56개(buddy 2 / director 31 / finder 11 / thinker 9 / crafter 2 / inspector 1). .md 는 chain 별 하위 디렉토리(P{NN}.R{NN}/)에 위치. tool-step 전용 pipeline(P02.R13, P05.R10)은 .md 디렉토리 없음
  - 근거: find @pipelines -type f 전수 목록 (/home/ubuntu/workspace/repository/engine-prototype/@pipelines/)
- **pipeline 전체 목록** — P01: R00.CHAT_CONVERSATION. P02: R00.CONCEPT_MATURITY / R10.DIRECTOR_GAP_ANALYSIS / R11.PATENT_EVALUATION / R12.DRAWING_ORCHESTRATION / R13.SAVE_DRAWING_ARTIFACTS / R20.CLASSIFY_INVENTION / R21.CLASSIFY_SHARD / R99.CENTRAL_AGENT. P03: R00.PRIOR_ART_SEARCH_ANALYZE / R01.SEARCH_AND_REFLECT / R02.POST_REFLECT / R10.ANALYZE_PLAN / R11.EVALUATE_NOVELTY / R20.ANALYZE_REJECTION_RISK. P04: R00.INVENTION_REASONING / R02.VERIFY_CLAIM_LOGIC / R10.EXTRACT_NUMERALS / R11.CLAIMS_WITH_NUMERALS. P05: R00.GENERATE_DL / R10.RENDER_DRAWING. P06: R00.REVIEW_DRAWING — 합계 22
  - 근거: @pipelines/ 파일 목록 + @pipelines/manifest.pipeline.yaml:13-172
- **root chain (프로덕션 진입점)** — 프로덕션 root spawn 은 P01_ENTRY=("P01.R00.CHAT_CONVERSATION",1) 항상 + P02_ENTRY=("P02.R00.CONCEPT_MATURITY",2) ENGINE_MODE=FULL 일 때 — Nexus spawn_root_chains 가 DRO /control/spawn 으로 트리거. 그 외 pipeline 은 dispatch_to 그래프 또는 dev/test 직접 spawn 으로만 도달
  - 근거: 100.Nexus/src/config.py:23-24, 100.Nexus/src/message_flow.py:73-105
- **manifest.pipeline.yaml 성격** — version 2, 22 pipeline 인덱스 + dispatches_to 그래프 기재. 자체 선언: "사람 inventory 용 — runtime SoT 는 *.pipeline.json 파일명 + 파일 자체 (pipeline_walker / tests/validate 가 파일 scan)". persona 정의 SoT 는 @deployment/engine.config.yaml 의 personas 로 위임(중복 기재 없음)
  - 근거: @pipelines/manifest.pipeline.yaml:1-8
- **P02.R00.CONCEPT_MATURITY step 구성 실측** — steps 배열 top-level 6 엔트리, step id 0~7 총 8 step. 0=extract_stack(LLM, inject: cm://conversation + cm://concept_discovery_stack) → 1=staging.save(tool, 7필드 CDS PUT) → [2=score_clarity, 3=score_completeness, 4=score_potential](nested list 정적 병렬, 각 LLM) → 5=maturity.compute(tool, $.steps.2/3/4 합산) → 6=update_roadmap(LLM, inject: conversation/CMM/CDS/UR 4종) → 7=roadmap.persist(tool, $.steps.6). dispatch_to: null (self-contained). LLM step=0/2/3/4/6, tool step=1/5/7. 각 step 에 display_status {ko,en} 존재
  - 근거: @pipelines/02.director/P02.R00.CONCEPT_MATURITY.pipeline.json:9-167
- **P03 KIPRIS RAG chain graph 실측** — P03.R00(1 LLM step) dispatch_to=[[P03.R01]] → P03.R01(3 step: query_plan LLM → kipris.search_patents tool → coverage_reflect LLM) dispatch_to=[[P03.R01(self)],[P03.R02]] (choice 0=재검색, 1=진행) → P03.R02(3 LLM step: rank/match/synthesize) dispatch_to actions=[] (exit). P03.R11(4 step: analyze LLM → kipris.get_patent_detail tool → match LLM → synthesize LLM)은 P03.R02 가 아니라 P03.R10.ANALYZE_PLAN 의 dispatch_to=[[P03.R11]] 에서 이어지며, R11 은 [[P02.R99.CENTRAL_AGENT]] 로 dispatch. P03.R20 도 [[P02.R99]] 로 dispatch
  - 근거: @pipelines/03.finder/P03.R00…:9-15, P03.R01…:9-18, P03.R02…:9-11, P03.R10…, P03.R11…:9-15, P03.R20… 각 pipeline.json
- **P02.R99.CENTRAL_AGENT 상태** — 파일 존재, 1 LLM step(instructions reference=@pipelines/02.director/P02.R99/decide.md, output_contract=validate-and-plan-output) + 7-way dispatch_to(actions 7개: P02.R10 / P03.R20 / P02.R20 / P03.R00 / P04.R00 / P02.R12 / P02.R11). 100.Nexus/src·200.DRO/src·300.Actor/src 전체에 'R99' 문자열 참조 0건 — 프로덕션 코드가 spawn 하는 경로 없음(root entry 는 P01.R00/P02.R00 만). R99 를 향해 dispatch 하는 pipeline 은 P02.R10/R12/R20, P03.R11/R20, P04.R00 의 6개
  - 근거: @pipelines/02.director/P02.R99.CENTRAL_AGENT.pipeline.json:9-47; grep R99 100.Nexus/src 200.DRO/src 300.Actor/src 결과 0건; 100.Nexus/src/config.py:23-24
- **dispatch graph 전체 실측** — P01.R00→[[]](exit). P02.R00→null. P02.R10→[[],[P02.R99]]. P02.R11→[[],[P03.R00],[P03.R11],[P04.R02],[P02.R11(self)]] + max_self_recursion:3. P02.R12(14 LLM step)→[[P02.R99],[P02.R12(self)]] + max_self_recursion:2. P02.R13→[[]]. P02.R20→[[P02.R99]]. P02.R21→[[]]. P04.R00→[[P02.R99]]. P04.R02→[[]]. P04.R10→[[P04.R11]]. P04.R11→[[P02.R12]]. P05.R00→[[P05.R10]]. P05.R10(tool drawing.render 1 step)→[[P06.R00]]. P06.R00(1 LLM step)→[[P02.R12],[P05.R00]]. max_self_recursion 코드 default=3
  - 근거: 각 *.pipeline.json (python 전수 파싱); @pipelines/02.director/P02.R11…:25, P02.R12…:18; 200.DRO/src/dispatch_resolver.py:7,28,79
- **tool step 실측 (9곳, 8 tool)** — tool step 사용처: P01.R00 step2=cm.append_conversation, P02.R00 step1/5/7=staging.save/maturity.compute/roadmap.persist, P02.R10 step1=knowledge.load_rejections_section, P02.R13=cm.save_drawing_artifacts, P03.R01 step1=kipris.search_patents, P03.R11 step1=kipris.get_patent_detail, P05.R10=drawing.render. 나머지 step 은 전부 instructions(LLM) — 2종 외 형태 없음
  - 근거: 각 *.pipeline.json python 전수 파싱 (steps 의 tool/instructions 키)
- **GLOBAL.json 내용** — GLOBAL layer = inject_context 에 invention_object_model: "cm://invention_object_model" 1건만. recommended_context/fragments 빈 객체, llm_tools 빈 배열
  - 근거: @pipelines/_shared/GLOBAL.json:1-8
- **COMMON.json 6개 내용** — 6개 모두 persona_prompt(한국어 역할 정의: Buddy=Gemini 3.1 Pro 응대원, Director=Claude Opus 4.7 중앙 판단, Finder=KIPO 심사관급 선행기술, Thinker=GPT o3 멀티도메인, Crafter=Claude Opus 4.7 DL 작성, Inspector=Gemini Vision 검수) + fragments 보유. fragments 수: P01=10개(korean_tone·가드레일 7종 등), P02=3개(특허법·completeness_scoring·claim_decomposition), P03=1개(kipris_token_and), P04=2개, P05=2개(drawing_tool_selection·dl_code_structure), P06=0개. inject_context/recommended_context 는 6개 전부 빈 객체, llm_tools 전부 빈 배열
  - 근거: @pipelines/0{1-6}.*/P0{1-6}.COMMON.json 전수 read
- **4-layer cascading** — 머지 대상 4항목 = inject_context/recommended_context/fragments/llm_tools, 순서 GLOBAL → P{NN}.COMMON → pipeline.common → step. 같은 키+같은 source 중복 = validator error. 검증은 tests/validate stage 2 가 shared loader load_pipeline_cascaded 로 cascading 후 effective_llm_tools 를 schema enum allowlist 와 대조
  - 근거: @pipelines/README.md:47-58; tests/validate/validate/stages/stage_02_cascading.py:1-50; tests/validate/validate/_common.py:74-79
- **llm_tools 실사용** — 현재 22개 pipeline.json + 6개 COMMON.json + GLOBAL.json 의 llm_tools 는 전부 빈 배열 — fetch_* 를 선언한 step 이 0개. allowlist(6종: fetch_dialog / fetch_step_output / fetch_drawing / list_drawings / fetch_outputs / fetch_conversation)는 pipeline schema 의 enum 이 단일 소스이고, Actor 구현도 동일 6종(make_fetch_tools — step 의 llm_tools 선언이 노출 제어, fetch_iom 은 IOM 상시 inline 이라 없음)
  - 근거: grep llm_tools @pipelines (비어있지 않은 배열 0건); @contracts/_shared/pipeline-definition.schema.json:95 ($defs.Step.properties.llm_tools.items.enum); 300.Actor/src/tools/fetch/__init__.py:7,21-80
- **P01.R00 구성** — 3 step: 0=assess(LLM, Gemini multimodal 1차 분석, output_contract=chat-assess-output) → 1=compose(LLM, 응답 작성) → 2=cm.append_conversation(tool, $.steps.1.assistant_turn). pipeline.common 의 inject_context 에 conversation: cm://conversation. dispatch_to.actions=[[]] — self-contained. step 에 display_status {ko,en} 존재
  - 근거: @pipelines/01.buddy/P01.R00.CHAT_CONVERSATION.pipeline.json:3-62
- **step id 필드** — step 객체의 "id" 필드는 P02.R00 만 명시("0"~"7"). P01.R00/P02.R12 등 다른 pipeline 의 step 은 id 필드 없음
  - 근거: @pipelines/02.director/P02.R00…json:12,31,54; P01.R00…json·P02.R12…json steps 파싱 (id=None)

### @deployment + compose + Makefile

배포 구성은 @deployment/ 가 SoT — knobs.yaml(8 knob 스키마, committed) + profile.stack.yaml(현재 knob 값, gitignored) + topology.yaml(호스트/포트 주소록) + engine.config.yaml(persona·LLM·tool 운영 SoT, 빌드타임 Actor 이미지에 COPY) + media.config.yaml(미디어 업로드 설정, 런타임 마운트) 구성. compose.yaml 은 4 서비스(dro/nexus/cm/actor)를 정의하며 모드는 env 가 아니라 profile.stack.yaml 의 /etc/deployment.yaml 마운트를 venezia_deployment 가 런타임 read 하고, build.target 은 make 가 생성하는 .env.deploy 의 <UNIT>_TARGET(production|mock)으로 보간된다. Actor·DRO Dockerfile 만 production+mock 멀티스테이지(mock = mocks/ 만 COPY 하는 독립 minimal 이미지)이고 Nexus·CM 은 production 단일 stage(knobs 의 available:false 와 일치). Makefile 은 검증 7 track(validate/lint/invoke/probe/enact/play/endpoint) + stack utility(up/down/logs/ps/mode/topology) + deploy(knob 제어) + export-openapi + knowledge base 빌드 target 을 제공하며, make up 은 인자 거부·풀 리셋(--no-cache --pull) 5단계로만 반영한다. Python 요구는 전 패키지 requires-python ">=3.14", 베이스 이미지 python:3.14-slim. 문서 대비 어긋난 점은 README 의 validate "14 stage"(실측 최고 stage 15) 와 onboarding 의 @deployment 파일 나열에 media.config.yaml/media-config.schema.json 누락 2건.

- **knobs.yaml — 8 knob 실측** — knob 은 정확히 8개: actor/dro/cm/nexus/llm/kipris (kind:fidelity, values real|fake, default real) + auth (kind:behavior, open|secure, default secure) + engine (kind:behavior, full|smalltalk, default full). cm·nexus 는 available:false (fake 미구현 — 선택 시 fail-loud). realize 는 actor/dro/cm/nexus=via image(컨테이너 교체), llm/kipris/auth/engine=via config(런타임 /etc/deployment.yaml read)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/@deployment/knobs.yaml:9-17
- **engine.config.yaml — personas P1~P6 실값** — P1 Buddy(channel support, memory_dir 01.buddy): sdk gemini, model gemini-3.1-pro-preview, fallback gemini-3-flash-preview, effort 없음, max_concurrency 4. P2 Director(analysis, 02.director): claude, claude-opus-4-7, fallback claude-opus-4-7, effort high, max_concurrency 2. P3 Finder(research, 03.finder): gemini, gemini-3.1-pro-preview, fallback gemini-3-flash-preview, max_concurrency 3. P4 Thinker(thinking, 04.thinker): openai, o3, fallback o3, effort medium, max_concurrency 2. P5 Crafter(drafting, 05.crafter): claude, claude-opus-4-7, fallback claude-opus-4-7, effort high, max_concurrency 2. P6 Inspector(review, 06.inspector): gemini, gemini-3.1-pro-preview, fallback gemini-3-flash-preview, max_concurrency 3
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/@deployment/engine.config.yaml:18-81
- **engine.config.yaml — vendors/tools/defaults** — schema_version 1. vendors: claude/gemini/openai 각각 retry {max_attempts:3, backoff_seconds:[2,5,10]}. tools: max_concurrency 4, media_describe.model gemini-3.1-pro-preview, kipris {max_concurrency:3, timeout_s:30, max_results:30, max_results_per_query:10, base_url http://plus.kipris.or.kr/kipo-api/kipi, cache {max_size:1024, ttl_s:3600}}, drawing.render_timeout_s 120. defaults: max_iterations 10, schema_retry 1, cm_http_timeout_s 60
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/@deployment/engine.config.yaml:16,83-108
- **engine-config.schema.json 존재** — @deployment/engine-config.schema.json 존재 (149줄, JSON Schema). top-level required = [schema_version, personas, vendors, tools, defaults]. persona required = [name, role, channel, memory_dir, llm, max_concurrency], llm required = [sdk, model, fallback_model]. tools required = [max_concurrency, media_describe, kipris, drawing]
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/@deployment/engine-config.schema.json:8,20,37,78
- **topology.yaml 역할** — 순수 네트워크 주소록 (host/port SoT): dro 59200 / cm 59400 / actor 59300 / nexus 59100 (각 host_publish_port 동일값) + account_callback_path /auth/callback. 로딩 2경로: 컨테이너 안 /etc/topology.yaml read-only mount → shared/venezia_topology read, compose interpolation 은 make topology 가 생성하는 @deployment/.env.topology 를 --env-file 로 import
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/@deployment/topology.yaml:8-33
- **profile.stack.yaml 역할** — gitignored (git check-ignore 확인) 현재 knob 값 파일 — make deploy 가 쓰고 compose 가 /etc/deployment.yaml 로 read-only mount, venezia_deployment 가 런타임 read. 현재 로컬 값: actor/dro/cm/nexus/kipris=real, llm=fake, auth=open, engine=full. .env.topology/.env.deploy 도 gitignored 생성물
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/@deployment/profile.stack.yaml:1-9, compose.yaml:29-34, git check-ignore 실행 결과
- **@deployment committed 파일 전체** — git 추적 파일 = engine-config.schema.json, engine.config.yaml, knobs.yaml, media-config.schema.json, media.config.yaml, topology.yaml (+.gitkeep). media.config.yaml 은 미디어 업로드 설정 (max_file_bytes 20971520=20MiB, allowed_mime 5종 jpeg/png/webp/gif/pdf, max_files_per_work 50, presign put_ttl 600/get_ttl 300) — /etc/media.config.yaml 로 Nexus·CM 에만 마운트, 리빌드 없이 반영
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/@deployment/media.config.yaml:4-15, compose.yaml:37-41, git ls-files 실행 결과
- **compose.yaml — 4 서비스 정의** — services = dro(container_name 200.DRO), nexus(100.Nexus), cm(400.CM), actor(300.Actor). 각각 build.target ${<UNIT>_TARGET:?...} (미생성 시 fail-loud 메시지), ports ${<UNIT>_PUBLISH_PORT}:${<UNIT>_PORT}, network drc-network(bridge), named volume logs, restart unless-stopped, healthcheck = uv run python urllib.request.urlopen(http://localhost:$PORT/health) 30s 간격. dro/nexus/actor 는 depends_on cm(service_healthy)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/compose.yaml:43-210
- **compose.yaml — 마운트·env** — 공통 마운트: topology.yaml→/etc/topology.yaml, profile.stack.yaml→/etc/deployment.yaml (전 서비스, read-only). media.config.yaml→/etc/media.config.yaml 은 nexus·cm 만. dro 추가: @pipelines:/pipelines, @contracts:/contracts, tests/data/dro-tapes:/app/data/dro-tapes. actor 추가: @pipelines, @knowledge:/app/@knowledge, tests/data/llm-fixtures, tests/data/kipris-fixtures. env: 전 서비스 PORT/TOPOLOGY_NETWORK=internal/AWS_REGION=ap-northeast-2/AWS_SECRET_NAME/LOG_DIR, cm 에 S3_BUCKET=venezia-bucket, actor 에 FIXTURE_PATH·ACTOR_ID=300.Actor, actor 의 AWS_SECRET_NAME 에 public-data-sources/personal(KIPRIS) 포함. LLM_MODE/AUTH_MODE/ENGINE_MODE 는 env 에 없음 — profile 을 런타임 read (compose 주석 명시)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/compose.yaml:22-41,57-68,100-110,135-147,171-189
- **Makefile — target 전체 목록** — 공개 target: help(기본 goal)·validate·lint·invoke·probe·enact·play·endpoint(검증 7 track), up·down·logs·ps·mode·topology(stack utility), deploy(init|show|reset|vet|set — venezia_deployment CLI), export-openapi, knowledge base 계열 cli-install/build-classification(-dry)/verify-classification, manual-install/build-drafting(-raw/-summary)/verify-drafting, rejections-install/build-rejections(-summary/-by-section/-cases)/verify-rejections. 내부 helper: .uv, _full_reset, _deploy_env, _check_aws_creds, _wait_healthy. probe positional 용 가짜 target 13개(view trail check seed list list-chains dump-rt models dialogs clean structure exercise verify) + P% 패턴
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/Makefile:1-9,92-140,143,224-229,237-269,315-375
- **Makefile — 각 track 요지** — validate=tests/validate 정적 검사(help 문구 '15 stage'), lint=ruff --fix+format·mypy·bandit·pip-audit 4개 게이트, invoke=스택 없는 라인 99%(5 suite), probe=실 CM 블랙박스 sub-command(+verify 게이트), enact=Actor 단일 RT(시나리오 5/5 게이트+단건), play=pipeline 실행(無인자 root 전수), endpoint=외부 REST+WS contract e2e. probe/enact/play/endpoint 는 TOPOLOGY_NETWORK=external + TOPOLOGY_FILE(+enact/play/endpoint 는 DEPLOYMENT_FILE)로 실행. deploy 후 _deploy_env 자동 재실행으로 .env.deploy 동기화
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/Makefile:47-54,92-148
- **Makefile — up 동작** — make up 은 인자를 받으면 parse-time $(error) (positional 폐기). profile.stack.yaml 부재 시 exit 2. llm:real 이면 _check_aws_creds 가 IMDS(169.254.169.254) curl 로 EC2 IAM 확인 후 실패 시 exit 2. _full_reset 5단계 = ①.env.topology+.env.deploy 생성 ②down --rmi all -v --remove-orphans ③build --no-cache --pull ④up -d --force-recreate ⑤_wait_healthy(컨테이너별 최대 60회×2s). DOCKER = docker compose --env-file @deployment/.env.topology --env-file @deployment/.env.deploy. ambient ACTOR_TARGET 등 4개와 VIRTUAL_ENV, PROMPT/PERSONA/TIMEOUT/SPEC 을 unexport (env 오염·인젝션 차단)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/Makefile:14-24,197,217-221,237-313
- **make help 출력** — help 는 배너('Patent AI Agent Engine — DRC Make 인터페이스') + 5 섹션: 검증 7 track(no-stack 3 + stack 4), Stack utility(up/mode/topology/down/logs/ps), Deployment 구성(deploy init/set/show/vet/reset + knob 나열), probe sub-command 13종, Knowledge base(build/verify-classification·drafting·rejections). mode target 은 profile 의 auth/engine/llm/kipris 4 knob 을 grep 출력
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/Makefile:43-82,255-259
- **Dockerfile mock stage — actor/dro 만** — 300.Actor/Dockerfile = production(python:3.14-slim + plantuml/openscad/fonts-dejavu-core apt + shared/ COPY + engine.config.yaml → /app/engine.config.yaml 빌드타임 COPY + uvicorn src.main:app) + mock(300.Actor/mocks/ 만 COPY, uvicorn actor_app.app:app — minimal, production 과 독립) 멀티스테이지. 200.DRO/Dockerfile 도 production + mock(200.DRO/mocks/ COPY, dro_app.app:app) 동형. 100.Nexus·400.CM Dockerfile 은 production stage 단일 (mock stage·mocks/ 디렉토리 없음 — knobs available:false 와 일치). stage 선택 = compose build.target ${<UNIT>_TARGET} ← venezia_deployment/export.py 가 via:image knob 마다 fake→mock, 그 외 production 으로 .env.deploy 에 emit
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/Dockerfile:3,30,46-62; 200.DRO/Dockerfile:3,35-50; 100.Nexus/Dockerfile:5; 400.CM/Dockerfile:2; shared/venezia_deployment/export.py:20-27
- **Python 버전 요구** — requires-python = ">=3.14" — 5개 패키지(100.Nexus, 200.DRO, 300.Actor, 400.CM, shared) + 7개 테스트 트랙(validate/lint/invoke/probe/enact/play/endpoint) 전부 동일. Docker 베이스 이미지도 전 컨테이너 python:3.14-slim. README 의 'FastAPI (Python 3.14+)' 서술과 일치
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/200.DRO/pyproject.toml:4 외 12개 pyproject.toml(grep 전수), 각 Dockerfile FROM 라인

### tests/ 검증 7 track

tests/ 는 validate·lint·invoke·probe·enact·play·endpoint 7 개 동등 track 이며 각 track 이 자체 uv project(pyproject.toml + uv.lock) 로 존재한다. 실측 결과: validate 는 15 stage(실행 확인 — 22 pipeline, "15 stage 모두 통과" PASS), lint 는 ruff/mypy/bandit/pip-audit 4 runner 전부 게이트, invoke 는 5 suite(shared/cm/dro/actor/account) 각 fail_under=99 에 coveragerc 는 tests/invoke/coveragerc 단일, probe 는 sub-command 13 개, enact 는 시나리오 5 종 + 단건 모드, endpoint 는 phase 11 개(output 포함) + dro-tapes 43 케이스다. .docs/Verification/verification.md 는 실코드와 정합(15 stage·11 phase·5 suite·13 sub-command·시나리오 5 종 모두 일치)하나, 루트 README.md 는 validate 를 14 stage·endpoint 를 10 phase 로 적어 코드와 어긋나고, onboarding.instructions.md 의 endpoint phase 열거(10개)에는 output phase 가 빠져 있다.

- **track 구성** — tests/ 하위는 data + 7 track 디렉토리(validate/lint/invoke/probe/enact/play/endpoint)이며 각 track 은 자체 uv project(pyproject.toml, uv.lock, README.md, 동명 패키지 디렉토리)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/ (ls 실측), tests/validate/{pyproject.toml,uv.lock,validate/}
- **validate — stage 수** — validate 는 15 stage. cli.py 요약표에 Stage 1(schema)~Stage 15(parallel shape) 15 항목이 하드코딩되어 있고, 실제 실행 결과 22 pipeline 대상 15 stage 전부 pass, 출력 '✅ validate PASS — 15 stage 모두 통과.'
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/validate/validate/cli.py:203-219,235 + `cd tests/validate && uv run python -m validate` 실행 출력
- **validate — stage 구현 파일** — stages/ 에 stage_01_schema, stage_02_cascading, stage_03_cross_ref, stage_04_tool_registry, stage_05_inputs_placeholder, stage_06_cm_pointer, stage_10_ws_consistency, stage_11_dead_schema, stage_12_infra_config, stage_13_asyncapi, stage_14_census, stage_15_parallel_shape + contracts.py(Stage 7), contracts_extended.py(Stage 8), external_api.py(Stage 9) 파일이 존재
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/validate/validate/stages/ (ls 실측), cli.py:41-55 import 목록
- **validate — 실행 실측치** — 실행 시 pipeline 22 개(@pipelines P{NN} 파일), Actor tools 19 @register, llm_tools enum 6종(fetch_conversation/fetch_dialog/fetch_drawing/fetch_outputs/fetch_step_output/list_drawings). warning 1건(dead-schema — 02.director/stages 미참조 output_contract 3개)
  - 근거: `cd tests/validate && uv run python -m validate` 실행 출력 (2026-07-17)
- **lint — 구성** — lint 는 ruff / mypy / bandit / pip-audit 4 runner orchestrator 이며 4개 전부 게이트(advisory 없음, 전부 exit 0 이어야 PASS). ruff runner 는 항상 --fix + format write(별도 format 단계 없음). --runner 옵션으로 단일 runner 실행 가능
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/lint/lint/cli.py:1-57, tests/lint/lint/runners/{ruff,mypy,bandit,pip_audit}.py
- **invoke — suite 5개 + 99% 게이트** — invoke 는 5 suite(shared→shared venv, cm→400.CM venv, dro→200.DRO venv, actor→300.Actor venv, account→100.Nexus venv)를 각 컨테이너 venv 별 ephemeral pytest 로 실행하며 SUITES dict 의 fail_under 가 5개 모두 99. test_*.py 파일은 suites/ 전체에 76개
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/invoke/invoke/cli.py:1-82 (SUITES, fail_under=99 x5), tests/invoke/invoke/suites/ (ls·find 실측 76 파일)
- **invoke — coveragerc 위치** — coverage omit/exclude 는 tests/invoke/coveragerc 단일 파일(--cov-config 로 전달). omit 대상: src/main.py, src/secrets.py, src/llm/{claude,gemini,openai}.py, venezia_topology/export_env.py, venezia_secrets/*, venezia_contracts/models/dro_api/document.py
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/invoke/coveragerc:11-24
- **probe — sub-command 13개** — probe commands/ 는 정확히 13개 모듈: check, clean, dialogs, dump_rt, exercise, list, list_chains, models, seed, structure, trail, verify, view. cli.py 가 전부 add_parser 로 등록(list-chains, dump-rt 는 하이픈 표기). README 의 13개 주장과 일치
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/probe/probe/commands/ (ls 실측), tests/probe/probe/cli.py:30-42,52-134
- **probe — verify 게이트** — probe verify = 임시 세션에 exercise(CM /openapi.json 기반 전 API 전수 호출) + structure(실 S3 키 /tree ↔ scaffolding+manifest 대조) 실행 후 clean. 구조검증 로직은 tests/probe/probe/_structure.py (probe 트랙 내부)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/probe/probe/commands/{verify,exercise,structure}.py, tests/probe/probe/_structure.py, .docs/Verification/verification.md §3.4
- **enact — 시나리오 5종** — ALL_SCENARIOS = ("dispatch", "context", "tool", "concurrency", "errors") 5종. 無인자 = 전수(_run_scenarios(ALL_SCENARIOS)), 시나리오명 단일 실행 가능. 빈 checks 는 PASS 로 치지 않음(all([]) false-pass 방어)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/enact/enact/scenarios/__init__.py:9,20-22, tests/enact/enact/cli.py:246-251
- **enact — 단건 모드 문법** — 단건 모드: positional 'P{NN}.R{NN} [step]'(실 pipeline step RT 합성) | spec 파일 경로(YAML/JSON) | --persona N --prompt "…"(ad-hoc 인라인, --spec 과 XOR). make 경유 시 ENACT_PERSONA/ENACT_PROMPT/ENACT_SPEC env 로 전달(Makefile 이 PERSONA=/PROMPT=/SPEC= 을 매핑). --timeout 옵션 존재
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/enact/enact/cli.py:205-240,257-262, Makefile:114-118,190-201
- **play — 인터페이스** — play 는 無인자 = root pipeline 전수(*.R00.* 순차+집계), 'P{NN}.R{NN}' = 단일, --seed-iom-from(make SEED=), --ws-timeout(make WS_TIMEOUT=, default 1800). stack MODE 자동 감지(@deployment/profile.stack.yaml) — FIXTURE 일 때만 invariants check, PRODUCTION 은 skip. fixture mode + SEED 미지정 시 tests/data/iom-samples/smart_beverage_detailed.json 자동 seed
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/play/play/cli.py:1-86, Makefile:120-129
- **play — dual 관측** — dual 관측 = ① CM trail.jsonl polling(_run.py — trail follow + chain_dispatched event 로 spawned chain BFS 추적) + ② DRO RAW SSE(_sse.py — self-contained 미니 SSE 파서, trigger 전 구독 시작, 자동 assert 4종: ≥1건 수신 / 전건 raw-sse-event schema 통과 / seq 순단조증가 / consumer 무예외 — 실패 = play FAIL)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/play/play/_sse.py:1-12, tests/play/play/_run.py:58-85,151,237-274
- **endpoint — phase 11개** — _ALL_PHASES = [health, info, account, works, auth, work_resources, output, ws, ws_tape, error_envelope, secure] — 11개. phases/all_phases.py 의 _phase_map 도 동일 11개 등록. output phase 는 output/draft build·preview·download + proposal 501 검증, ws_tape 는 dro:fake 전용(dro:real 이면 skip-pass), secure 는 SECURE 전용(OPEN 이면 skip)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/endpoint/endpoint/cli.py:23-36, tests/endpoint/endpoint/phases/all_phases.py:839-853
- **endpoint — ws_tape 케이스 수** — tests/data/dro-tapes 의 tape JSON 은 총 43개 (P01.R00.CHAT_CONVERSATION 35개 + P02.R00.CONCEPT_MATURITY 8개). ws_tape phase 가 정렬순 playlist 를 미러해 tape JSON 의 expected 섹션으로 검증하며, TAPE=<pipeline>/<tape명> 으로 단일 tape 만 검증 가능
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/data/dro-tapes/ (find 실측 43), tests/endpoint/endpoint/phases/ws_tape.py:1-39,113
- **endpoint — call 모드** — make endpoint call REST="METHOD /path" [BODY='{…}'] = Nexus 1회 요청 → status+body 출력(exit 0 = 응답 수신, status 무관). call WS='<action> {json}' = fresh work 생성 → thread/stream 연결 → action 1건 송신 → 수신 이벤트 출력(message.send 는 correlation_id 자동 주입). Makefile 이 TAPE/REST/WS/BODY make var 를 --tape/--rest/--ws/--body 로 전달
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/endpoint/endpoint/call.py:1-80, Makefile:131-140
- **tests/data — fixture 종류** — tests/data 는 4종: llm-fixtures(5 pipeline dir — P01.R00 2 / P02.R00 5 / P03.R00 1 / P03.R01 2 / P03.R02 3 파일), kipris-fixtures(search_pool.json + details.json + README.md), dro-tapes(2 pipeline dir 43 tape + README.md), iom-samples(smart_beverage_detailed.json 1개 — play 의 default auto-seed IOM)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/tests/data/ (ls 실측), tests/play/play/cli.py:33 (DEFAULT_FIXTURE_IOM)
- **verification.md 정합** — .docs/Verification/verification.md 는 실코드와 정합: validate 15 stage(§3, 67행), invoke 5 suite·99%·coveragerc 위치(94-109행), probe 13 sub-command 구성·verify 게이트(§3.4), enact 시나리오 5종+단건 모드(§3.5), play dual 관측·SEED/WS_TIMEOUT(§3.6), endpoint 11 phase(197행 '**11 phase**')·ws_tape·call(§3.7)
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/.docs/Verification/verification.md:1-235 ↔ 각 track cli 실측
- **Makefile — track 인터페이스** — 7 track 전부 make target 존재(validate/lint/invoke/probe/enact/play/endpoint — 각각 cd tests/<track> && uv run python -m <track>). positional dispatcher 가 play P{NN}.R{NN} / probe <sub> / endpoint <phase|call> / enact <scenario|P{NN}.R{NN} step|spec> 을 처리
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/Makefile:92-140,150-227

### shared/

shared/ 는 단일 uv 패키지 venezia-shared (requires-python >=3.14, deps: boto3/structlog/httpx/jsonschema/pyyaml/pydantic) 안에 9개 venezia_* 패키지를 담는다 — 문서가 열거하는 8개(logging/secrets/contracts/topology/memory/pipeline_runtime/deployment/cm_client) 외에 venezia_media_config 가 실존한다. 각 컨테이너는 pyproject path dep (../shared) + Dockerfile `COPY shared/ /shared/` 로 동일 소스를 빌드타임에 내장한다. 런타임 설정류 3개(topology/deployment/media_config)는 컨테이너에 read-only 마운트된 /etc/*.yaml 을 lru_cache 로 read 하고, venezia_secrets 는 모듈 import 시점에 AWS Secrets Manager 를 fetch 해 env 를 주입한다. 컨테이너별 사용은 균일하지 않다 — Actor 는 venezia_logging 을 안 쓰고, CM 은 topology/deployment/cm_client/media_config 를 안 쓰며, Nexus 는 memory/pipeline_runtime 을 안 쓴다.

- **패키지 목록** — venezia_* 패키지는 9개: venezia_logging, venezia_secrets, venezia_contracts, venezia_pipeline_runtime, venezia_topology, venezia_memory, venezia_deployment, venezia_cm_client, venezia_media_config. 단일 배포 단위 venezia-shared (hatchling wheel).
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/pyproject.toml:23
- **패키지 목록** — venezia-shared 는 requires-python >=3.14, dependencies = boto3>=1.37.0 / structlog>=24.0.0 / httpx>=0.28.0 / jsonschema>=4.23.0 / pyyaml>=6.0 / pydantic>=2.0. venezia_memory/scaffolding.yaml 을 wheel force-include. 주석에 venezia_agent/venezia_pipeline 은 폐기 명시.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/pyproject.toml:5-26
- **venezia_logging** — structlog 기반 setup_logging(json_output, log_dir) — 콘솔 handler + LOG_DIR env/인자 존재 시 RotatingFileHandler(app.log, 10MB×5, JSON) 추가. get_logger 는 structlog BoundLogger 반환.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_logging/__init__.py:10-75
- **venezia_secrets** — 모듈 import 시 _load() 가 즉시 실행된다(모듈 말미 호출). AWS_SECRET_NAME(comma-separated 복수) 의 secret 들을 boto3 secretsmanager(region=AWS_REGION, default ap-northeast-2)로 fetch 해 env 주입. 기존 env 값이 있으면(빈 문자열 제외) 덮지 않음. MODE=PRODUCTION 인데 AWS_SECRET_NAME 미설정이면 RuntimeError, fetch 실패 시 raise(fail-loud). AWS_SECRET_NAME 없고 비-PRODUCTION 이면 no-op.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_secrets/__init__.py:53-112
- **venezia_secrets _KEY_MAP** — _KEY_MAP: ANTHROPIC_KEY→ANTHROPIC_API_KEY, OPENAI_KEY→OPENAI_API_KEY, KIPRIS_KEY→KIPRIS_API_KEY, 그리고 identity 매핑으로 GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET, NAVER_CLIENT_ID/NAVER_CLIENT_SECRET, KAKAO_CLIENT_ID/KAKAO_CLIENT_SECRET, JWT_SECRET_KEY. 맵에 없는 키는 이름 그대로 env 주입.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_secrets/__init__.py:15-28,85-91
- **venezia_secrets google-credentials** — secret JSON 이 type=service_account 이면 _install_google_credentials 가 /tmp/google-credentials.json (chmod 600) 저장 후 GOOGLE_APPLICATION_CREDENTIALS=그 경로, GOOGLE_CLOUD_PROJECT=project_id, GOOGLE_CLOUD_LOCATION setdefault "global", GOOGLE_GENAI_USE_VERTEXAI=true 를 set.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_secrets/__init__.py:30-50,79-83
- **venezia_secrets 컨테이너 배선** — compose 의 AWS_SECRET_NAME: DRO=llm-providers/prod/personal + google-credentials(:61), Nexus=llm-providers/prod/personal 만(:103), CM=personal + google-credentials(:139), Actor=personal + google-credentials + public-data-sources/personal(:177). 4 컨테이너 모두 src/secrets.py 가 `import venezia_secrets as _` 셔틀로 config read 전에 주입.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/compose.yaml:61,103,139,177; 300.Actor/src/secrets.py:1
- **venezia_contracts** — ContractLoader — @contracts/ 를 rglob 탐색해 contract id 로 JSON Schema 로드(.schema.json 우선, .json 폴백, dict cache), jsonschema Draft7Validator 로 validate(결과 반환)/assert_valid(raise). 디렉토리 탐지 = CONTRACTS_DIR env → 파일/cwd 상위 walk 로 @contracts 검색.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_contracts/loader.py:26-112
- **venezia_contracts models** — models/dro_api = 외부 표면(client 가 보는 REST+WS) 손작성 Pydantic 모델 9모듈: error(에러 envelope+ErrorCode), channels, message(MessageHistoryItem), work_api / account_api / upload(client REST 응답), document(출원서 빌드·다운로드), maturity(CMM 외부 응답), roadmap. models/__init__.py 는 빈 파일.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_contracts/models/dro_api/__init__.py:1-11
- **PERSONA_TO_CHANNEL** — PERSONA_TO_CHANNEL = {1: support, 2: analysis, 3: research, 4: thinking, 5: drafting, 6: review} — 문서 주장 6 라벨과 일치. CHANNEL_LABELS frozenset + channel_for_persona(범위 밖 KeyError) 제공. Nexus event_mapper 가 import (100.Nexus/src/event_mapper.py:19).
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_contracts/models/dro_api/channels.py:14-28
- **venezia_memory** — scaffolding.yaml(107줄, schema_version 1.0.0)을 import 시 1회 로드해 S3 key builder 함수 약 40개를 노출 — sessions/{user_id}/{work_id} 하위 runtime(00.dro conversation, persona queue/dialog/chain manifest·trail·rts·agent_state)/models(IOM·CMM·UR·CDS)/outputs/media/drawings + users/ 루트(identity·profile·idempotency·refresh_token). PERSONA_DIRS 1~6 → 01.buddy~06.inspector, DRO_DIR=00.dro, DIALOG_NAMES=페르소나별 allowlist(02.director: analysis/decisions/evaluation/workspace, 03.finder: research/rejection-cases, 06.inspector: evaluation).
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_memory/__init__.py:32-138,114-116; shared/venezia_memory/scaffolding.yaml:17-107
- **venezia_memory 레이아웃 상수** — key builder 외에 파일명/디렉토리명 상수(CONVERSATION_FILE, QUEUE_FILE, CHAIN_MANIFEST_FILE, CHAIN_TRAIL_FILE, CHAIN_RT_DIRNAME, CHAIN_AGENT_STATE_FILE, DRAWING_* 등)를 public 노출 — probe 구조검증(_structure.py)과 공유하되 검증 로직은 여기 없음.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_memory/__init__.py:362-375
- **venezia_topology** — /etc/topology.yaml(TOPOLOGY_FILE env override)을 lru_cache 로드. service_url(name) 은 TOPOLOGY_NETWORK=internal(default, 컨테이너 DNS host:port) | external(TOPOLOGY_EXTERNAL_HOST:host_publish_port) 분기. service_port / service_publish_port / all_service_names / account_callback_url(nexus URL + account_callback_path) 제공. export_env 모듈은 make topology 가 호출해 {SVC}_HOST/_PORT/_PUBLISH_PORT env 라인(.env.topology)을 stdout 출력 → compose interpolation.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_topology/__init__.py:29-93; export_env.py:22-30; Makefile:246
- **venezia_deployment runtime** — runtime.py 가 /etc/deployment.yaml(DEPLOYMENT_FILE env, = 마운트된 @deployment/profile.stack.yaml)을 lru_cache read. getter: auth() open|secure→OPEN|SECURE, engine() full|smalltalk→FULL|SMALLTALK, llm() real→PRODUCTION·fake→FIXTURE, kipris() raw lowercase, value(knob) raw. 파일 부재(RuntimeError) 시 _FALLBACK={auth: SECURE, engine: FULL, llm: PRODUCTION, kipris: real} 로 폴백(invoke import/host 경로용).
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_deployment/runtime.py:20-88
- **venezia_deployment CLI/스키마** — model.py = knobs.yaml Pydantic strict 스키마(KnobSpec: kind fidelity|behavior, values, default, available, realize.via image|config). loader.py = load_knobs/load_profile/default_profile/validate_profile(PROFILE_VERSION=1, 미지 knob·누락 knob·unavailable 값 ValueError). __main__.py = make deploy CLI(init/set/show/reset/vet — knob 이름·값을 knobs.yaml 로 검증). export.py = via:image knob 마다 <KNOB>_TARGET=production|mock 라인 출력(.env.deploy) → compose build.target 보간.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_deployment/model.py:13-43; loader.py:12-57; __main__.py:32-90; export.py:19-34; Makefile:144,252
- **venezia_pipeline_runtime** — loader 단일 모듈 — P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json 파일명 정규식 파싱(parse_pipeline_filename) + GLOBAL → persona.COMMON → pipeline.common → step 4-layer cascading 합집합 머지(load_pipeline_cascaded, override 없음·동일 name+source 충돌 검출), 루트 = PIPELINES_ROOT env / default /app/@pipelines. docstring 상 소비자 = 200.DRO pipeline_walker + tests/validate. 구 composer→300.Actor/src/composer.py, dispatch_resolver→200.DRO/src/dispatch_resolver.py 로 흡수.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_pipeline_runtime/__init__.py:1-21; loader.py:23-52
- **venezia_cm_client** — CMClientBase(httpx.AsyncClient, base_url=각 컨테이너 settings.CM_URL) — _model_get(RFC 6901 ?pointer= 부분 read, 404→None) / _get_or_none / 세 컨테이너 공통 model GET 4종(get_conversation, get_concept_maturity_model, get_user_roadmap, get_drawing_manifest) + 모듈 헬퍼 dict_to_add_ops(flat dict → RFC 6902 add ops). Nexus/DRO/Actor 의 src/cm_client.CMClient 가 상속(100.Nexus/src/cm_client.py:16, 200.DRO/src/cm_client.py:17, 300.Actor/src/cm_client.py:15). CM 자신은 사용 안 함.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_cm_client/__init__.py:22-79
- **venezia_media_config** — /etc/media.config.yaml(MEDIA_CONFIG_FILE env, = @deployment/media.config.yaml 마운트)을 lru_cache read — max_file_bytes / allowed_mime / max_files_per_work / presign.put_ttl / presign.get_ttl (필수 키 검증, 위반 시 RuntimeError). 코드에서 read 하는 곳은 Nexus router 의 미디어 업로드/다운로드 경로뿐(100.Nexus/src/router.py:27,834-842,896). compose 는 nexus·cm 두 서비스에 마운트(compose.yaml:110,147).
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/shared/venezia_media_config/__init__.py:20-69
- **컨테이너별 사용 매트릭스** — import 실측(각 컨테이너 src+mocks grep): Nexus = cm_client·contracts·deployment·logging·topology·media_config·secrets. DRO = cm_client·contracts·deployment·logging·pipeline_runtime·topology·memory·secrets. Actor = cm_client·contracts·deployment·topology·memory·secrets (venezia_logging import 0건 — kipris client 는 structlog 직접 사용). CM = contracts·logging·memory·secrets (topology·deployment·cm_client·media_config·pipeline_runtime import 0건).
  - 근거: grep -rE 'venezia_' 100.Nexus/src 200.DRO/src+mocks 300.Actor/src+mocks 400.CM/src; 300.Actor/src/tools/kipris/client.py:20
- **배포 방식** — 4 개 컨테이너 Dockerfile 모두 `COPY shared/ /shared/` 후 각 컨테이너 pyproject 의 path dep(venezia-shared = { path = "../shared" })로 uv sync 설치 — pip install 배포 아닌 소스 내장.
  - 근거: /home/ubuntu/workspace/repository/engine-prototype/300.Actor/Dockerfile:21; 300.Actor/pyproject.toml:22,35; 100.Nexus/pyproject.toml:17,21

### @contracts + @knowledge + tools/(루트) + .docs/Architectures/external_api

@contracts 는 git 트래킹 92 파일 — _shared/(횡단 데이터모델·RT·pipeline 메타 스키마 21종) + 00.dro/(WS event-catalog·internal control/SSE 계약 5종) + persona 별 stages/(output_contract 스키마 총 64종: buddy 3 / director 39 / finder 9 / thinker 9 / crafter 3 / inspector 1) 구조이며, 런타임 소비는 shared/venezia_contracts/loader.py 의 ContractLoader(파일명 rglob, Draft-07) 가 담당한다. @knowledge 는 classification(IPC+CPC, 1348 파일)·drafting(KIPO 심사기준 7 PDF 추출+요약)·rejections(summary+by-section A..H+Chroma cases[gitignored]) 3 도메인으로, 각각 tools/ 루트의 classification-indexer·manual-indexer·rejections-indexer 가 make build-* 로 빌드한다. tools/ 루트는 그 인덱서 3종 + openapi-export(make export-openapi) + 일회성 마이그레이션 스크립트 2종(migrate_cmm_keys.py, migrate_pipelines.py) 이다. .docs/Architectures/external_api/ 에는 openapi.nexus.json(OpenAPI 3.1, 26 paths)·asyncapi.yaml(AsyncAPI 3.0)·README.md·CLIENT-HANDOFF.md 4 파일이 존재한다. 문서-코드 어긋남으로 @knowledge/README 의 drafting/rejections "향후 예정" 표기, rejections-indexer README 의 "build=summary만", @contracts 스키마 description 의 구 chains/ 경로, external_api README 의 "JWT refresh 미구현" 표기가 실측과 어긋난다.

- **@contracts 구조** — git 트래킹 92 파일. manifest.contract.yaml + README.md + _shared/(13 스키마 + models/ 3 + runtime/ 8) + 00.dro/ 5 파일 + persona stages/ 64 스키마 (01.buddy 3 · 02.director 39 · 03.finder 9 · 04.thinker 9 · 05.crafter 3 · 06.inspector 1)
  - 근거: find @contracts 전수 목록 + git ls-files @contracts (92) + ls 0{1-6}.*/stages 카운트
- **@contracts/00.dro** — websocket-events.json = Nexus client WS envelope v2 event-catalog (type enum 9종: message.received/message.reply/work.progress/work.failed/model.maturity/model.roadmap/output.ready/system.resync_required/system.error, 봉투 {type,timestamp,seq,data}, type 별 payload 는 _payload_schemas 에 정의). raw-sse-event.schema.json = DRO→Nexus per-session SSE raw 이벤트. control-spawn-request/response.schema.json = Nexus→DRO POST /control/spawn 내부 계약(202, 인증 없음). dispatch-result.schema.json = Actor /dispatch SSE result(=완료된 RT output)
  - 근거: @contracts/00.dro/websocket-events.json (title/description/enum), 각 파일 title·description 실측
- **@contracts/_shared** — chain_manifest / reasoning_task / pipeline-definition(P{NN} 포맷, 구설계 키 폐기 명시) / drawing-manifest / health / invention-object-model(IOM) / manifest.context·models·outputs·runtime + models/{concept-discovery-stack, concept-maturity-model, user-roadmap} + runtime/ persona 누적 8종 (00.dro conversation, 02.director analysis·decisions·evaluation·workspace, 03.finder rejection-cases·research, 06.inspector evaluation)
  - 근거: @contracts/_shared/**/*.json title·description 전수 출력
- **@contracts 런타임 소비** — shared/venezia_contracts/loader.py 의 ContractLoader 가 contract id(파일명 줄기) 를 @contracts/ 하위 rglob 으로 탐색해 로드 (.schema.json 우선 → .json 폴백), jsonschema 로 검증. manifest.contract.yaml 을 읽는 코드 소비자는 repo 내 0건 (grep .py/.yaml/.toml/Makefile)
  - 근거: shared/venezia_contracts/loader.py:26-56; grep -rn "manifest.contract" 전수 0건
- **@contracts 검증 트랙** — tests/validate 의 contracts stage 가 @contracts/**/*.json 전수를 Draft-07 meta-schema 로 검증 + 필수 floor 13 파일 존재 확인. stage_10_ws_consistency 가 websocket-events.json 의 type.enum ↔ _payload_schemas 키 일치 검증. tests/endpoint 의 _ws_schema.py 가 수신 WS 프레임을 websocket-events.json 봉투+payload 로 실측 검증
  - 근거: tests/validate/validate/stages/contracts.py:1-34, stages/stage_10_ws_consistency.py:6-74, tests/endpoint/endpoint/phases/_ws_schema.py:1-17
- **@knowledge 구조** — 3 도메인: classification/ (ipc/·cpc/ 각각 tree.json + shards/ 4 파일[AB·CD·EF·GH] + subclasses/ [ipc 655 · cpc 681 파일], 32MB, git 트래킹 1348 파일) · drafting/ (raw/exammanual_01..07.md + summary.md + version.json, 1.5MB, 트래킹 10 파일) · rejections/ (summary.md + by-section/A..H.md 8 파일 + cases/[chroma.sqlite3 21MB + 세그먼트 dir + meta.json], 22MB). 각 도메인에 README.md + version.json
  - 근거: find @knowledge -maxdepth 2; ls shards/subclasses 카운트; du -sh; git ls-files @knowledge (1370)
- **@knowledge cases gitignore** — @knowledge/rejections/cases/ 는 .gitignore:210-211 로 미커밋 (build-rejections-cases 산출 large sqlite) — rejections 커밋분은 README + by-section 8 + summary.md + version.json 만
  - 근거: .gitignore:210-211; git ls-files @knowledge/rejections (10 파일, cases 0건)
- **@knowledge 빌드 메타** — classification built_at 2026-05-04 (wipo_ipc 20260101 · kipi_ipc · wipo_cpc 202605 등 출처별 URL·fetch 일시 기록). drafting extracted_at 2026-05-05 (KIPO 심사기준 7 PDF, KOGL 2.0, 총 ~167K est_tokens). rejections layer "1+2+3" — summary(claude-opus-4-7) + by-section A..H(claude-opus-4-7) + cases(KIPRIS 거절결정문 256건 인덱싱, gemini-embedding-001, collection rejection_cases)
  - 근거: @knowledge/classification/version.json · @knowledge/drafting/version.json · @knowledge/rejections/version.json
- **make build-* 3종** — build-classification = classification_indexer build (tools/classification-indexer, WIPO+KIPI+KIPRIS+data.go.kr 9 출처) · build-drafting = manual_indexer build (raw 추출 + summary; build-drafting-raw / build-drafting-summary 분리 타깃도 존재) · build-rejections = rejections_indexer build (summary + by-section; build-rejections-cases 는 별도 타깃). 각각 verify-classification/drafting/rejections + *-install 타깃 존재. Makefile 주석에 "Knowledge Base 빌드 (별개 도메인)"
  - 근거: Makefile:320-374
- **@knowledge 런타임 소비 (실측)** — compose.yaml 이 ./@knowledge 를 Actor 컨테이너 /app/@knowledge 에 :ro 마운트. 소비 경로 3곳: ① 300.Actor/src/llm/knowledge.py — drafting summary/raw·rejections summary static loader (claude.py 의 inject_knowledge 키 해석에서 호출) ② 300.Actor/src/tools/knowledge — knowledge.load_rejections_section tool 이 rejections/by-section/{A..H}.md 로드 (P02.R10 pipeline 의 tool step 이 사용) ③ 300.Actor/src/composer.py — fragments source 의 @knowledge/ prefix 해석
  - 근거: compose.yaml:184; 300.Actor/src/llm/knowledge.py:40-56 + llm/claude.py:60-85; tools/knowledge/__init__.py:64-80 + @pipelines/02.director/P02.R10.DIRECTOR_GAP_ANALYSIS.pipeline.json:34; composer.py:18
- **@knowledge 미배선 자산 (실측)** — classification/ 데이터(tree.json·shards·subclasses) 를 읽는 런타임 코드 0건 (분류 pipeline P02.R20/R21 은 존재하나 pipeline JSON 에 @knowledge 참조 0, 분류 tool 미등록). rejections/cases Chroma 인덱스를 읽는 코드 0건 (chromadb 는 300.Actor/pyproject.toml:27 의존성으로만 존재). inject_knowledge 키를 쓰는 pipeline/@deployment 설정 0건 (해석 코드만 claude.py 에 존재)
  - 근거: grep tree.json|shards|subclasses → 0 in 300.Actor/src; grep chroma → 0 in 300.Actor/src; grep inject_knowledge → @pipelines·@deployment 0건; @register(...) 전수 목록에 classification·cases 도구 없음
- **tools/ 루트 구성** — 6 항목: classification-indexer / manual-indexer / rejections-indexer (uv 프로젝트 3종 — @knowledge 빌더) + openapi-export (uv 프로젝트) + migrate_cmm_keys.py + migrate_pipelines.py (PEP 723 단일 스크립트 2종). git 트래킹 47 파일. .cache/·.venv/ 는 gitignored
  - 근거: ls tools/; git ls-files tools (47); git check-ignore .cache/.venv
- **tools/openapi-export** — make export-openapi → Nexus 의 GET /api/v1/openapi.json 을 fetch 해 .docs/Architectures/external_api/openapi.nexus.json 으로 저장. target 은 nexus 단독 (_TARGETS=[("nexus","nexus")]) — DRO 는 export 대상 아님. venezia_topology.service_url 로 base 해석, stack 가동 전제
  - 근거: tools/openapi-export/openapi_export/cli.py:1-30; Makefile:316-318
- **tools/migrate 스크립트** — migrate_cmm_keys.py = A-2 CMM 지표 키 long→short (concept_clarity→clarity 등 3키) 일회성 S3 마이그레이션, idempotent, --dry-run 지원. migrate_pipelines.py = 구 W{NN} pipeline → P{NN} 포맷 자동 변환 도구 (llm_task→LLM step, api_call→tool step, step output → stages/*-output.schema.json 자동 생성)
  - 근거: tools/migrate_cmm_keys.py:1-22 docstring; tools/migrate_pipelines.py:1-25 docstring
- **external_api 존재** — .docs/Architectures/external_api/ = 4 파일: openapi.nexus.json (113KB) · asyncapi.yaml (408행) · README.md (인덱스 문서) · CLIENT-HANDOFF.md (157행, frontend 핸드오프 노트 — 기준 2026-06-24 커밋 70f6a41, 소비 대상 계약 3개 = openapi.nexus.json + asyncapi.yaml + @contracts/00.dro/websocket-events.json 명시)
  - 근거: ls -la .docs/Architectures/external_api/; CLIENT-HANDOFF.md:1-20
- **openapi.nexus.json 요지** — OpenAPI 3.1.0, 26 paths — info/{providers,attributions} · user/auth(authorize/callback/connect/disconnect/refresh/logout) · user/account(+alias) · user/works · works/{id}(+meta·phase·thread/messages·estimate roadmap/maturity·media·output draft/proposal) + /health. info.title = "100.Nexus — mypage (auth + account + work CRUD/metadata)" (Nexus FastAPI app title 그대로)
  - 근거: openapi.nexus.json paths 전수 출력; 100.Nexus/src/main.py:38
- **asyncapi.yaml 요지** — AsyncAPI 3.0.0, info.version 2.0.0, server host nexus:59100 · pathname /api/v1/works/{work_id}/thread/stream · protocol ws · cookieAuth(nx_access). 채널 1개(work_session) 양방향 — server push 9 message (MessageReceived~SystemError) + client inbound(message.send). ring buffer maxlen 200, since_seq replay, close code 4401/4404/1001 등 운영 시맨틱 기술
  - 근거: .docs/Architectures/external_api/asyncapi.yaml:1-70 + operations 목록
- **external_api 검증 트랙** — tests/validate 에 external_api.py · stage_13_asyncapi.py · stage_14_census.py stage 가 존재해 openapi/asyncapi 문서를 검증 대상으로 참조
  - 근거: grep asyncapi tests → tests/validate/validate/stages/{external_api.py,stage_13_asyncapi.py,stage_14_census.py}

### .docs/Architectures/ 문서 신선도 (STATIC_BLOCK / DRC / AGENT_SDK / DIRECTION_PIPELINE_FLOW / EXTERNAL_API / external_api/*)

.docs/Architectures/ 는 6개 문서 + external_api/ 3개 파일로 구성되며, 최종 수정은 2026-06-12(STATIC_BLOCK)~06-29(EXTERNAL_API) 사이이고 그 이후 코드 커밋은 없다(HEAD 포함 최신 2 커밋은 docs-only, 마지막 코드 커밋 = 2026-06-28 8e41626). openapi.nexus.json 의 26 path 는 100.Nexus/src/router.py 라우트와 1:1 일치하고, asyncapi.yaml 의 이벤트 9종+inbound 1종은 event_mapper.py/ws_inbound.py 실측과 일치하며, DRO 4-표면·CM 76 endpoint·22 pipeline·P03 3-chain graph 등 DRC_ARCHITECTURE 의 핵심 주장 대부분이 코드와 합치한다. 어긋난 지점은 국소적 6건 — DRC 의 llm_tools "7개/7종"(실제 6), DRC §12 media tool 호출처(어떤 pipeline 도 미참조·P01.R10/R20/R21 부재), DRC §5 의 `{invention_uuid}` 라벨(실제 `{work_id}`), AGENT_SDK/DIRECTION 의 step 0 명 `extract_to_stack`(실제 `extract_stack.md`), external_api/README 의 "JWT refresh 미구현" 서술(회전 구현 완료), CLIENT-HANDOFF 의 model.* "SECURE 필요" 조건(코드에 auth 게이트 없음). 깨진 파일 링크는 0건 — 문서가 참조하는 모든 경로(Features/Issues/external_api/코드 파일)가 실존한다.

- **문서 최종 수정 시점** — 각 문서 최종 커밋: STATIC_BLOCK_ARCHITECTURE.md=f592a34(2026-06-12), AGENT_SDK_DESIGN.md=9b6773b(2026-06-20), DIRECTION_PIPELINE_FLOW.md=150e8da(2026-06-22), DRC_ARCHITECTURE.md=1810259(2026-06-28), external_api/(openapi·asyncapi·README·CLIENT-HANDOFF)=e44f9f2/b7dd786(2026-06-28), EXTERNAL_API.md=117bd54(2026-06-29). 이후 코드 변경 없음 — HEAD 포함 최신 2 커밋(47a0a50, 117bd54)은 docs-only, 마지막 코드 커밋은 2026-06-28 8e41626(100.Nexus/src/ws_inbound.py 만)
  - 근거: git log -1 -- <각 파일> + git log --since=2026-06-28 실행 결과
- **STATIC_BLOCK_ARCHITECTURE.md 성격** — 설계 의도 원본(수정 금지) — 6 페르소나 워커·옛 포트(59200~59210)를 기록하되, 머리의 '현행 implementation 매핑' 주석이 unified Actor(:59300)·Nexus SOLE gateway(:59100)·DRO(:59200)·CM(:59400) 현행 형상을 명시해 현재 코드와 정합
  - 근거: .docs/Architectures/STATIC_BLOCK_ARCHITECTURE.md:6
- **DRC_ARCHITECTURE.md 핵심 주장** — 현행 단일 진실 원천 종합 설계도 — 용어/4컨테이너/데이터흐름/S3 구조/P{NN} pipeline 포맷/composer/fail-loud 5위치/RT lifecycle/REST+WS 표면/CM endpoint/tool registry/모드 knob/검증 7 track/데이터 원칙을 §1~§16 으로 포괄
  - 근거: .docs/Architectures/DRC_ARCHITECTURE.md:1-620 (헤딩 outline 실측)
- **DRO 표면 — 문서 vs 코드 일치** — DRC·EXTERNAL_API 가 기술한 DRO 4 표면 {POST /control/spawn(202), POST /control/output, GET /events/{user_id}/{work_id}, GET /health} 이 코드와 정확히 일치 — 그 외 라우트 없음
  - 근거: 200.DRO/src/router.py:42,88,129 + 200.DRO/src/main.py:54
- **Nexus REST 표면 — openapi 스냅샷 일치** — external_api/openapi.nexus.json 의 26 path(info 2·auth 6·account 2·works 2·진입/meta/phase/thread/estimate 3/media 2/output 6/health)가 100.Nexus/src/router.py 의 @router 라우트 및 main.py /health 와 1:1 일치. openapi 재생성(e44f9f2) 이후 코드 커밋 3건(c5710fa·bfadb46·8e41626)은 WS 멱등(ws_inbound/message_flow/cm_client/store)만 건드려 REST 표면 불변
  - 근거: openapi.nexus.json paths 실측 vs 100.Nexus/src/router.py:208-1079; git log --name-only 8e41626~2..8e41626
- **WS 이벤트 — asyncapi vs 코드 일치** — asyncapi.yaml 의 server-push 9종(message.received/message.reply/work.progress/work.failed/model.maturity/model.roadmap/output.ready/system.resync_required/system.error) + inbound 1종(message.send) 이 event_mapper.py 의 emit(rt_started→work.progress, chain_completed[p1]→message.reply, chain_completed[p2]→model.maturity+model.roadmap{count}, output_ready→output.ready, rt_error/error→work.failed) 및 ws_inbound.py 와 일치. WS URL/close code(4401/4404/1001)도 router.py 실측과 일치
  - 근거: 100.Nexus/src/event_mapper.py:88-161, 100.Nexus/src/router.py:1079-1138, .docs/Architectures/external_api/asyncapi.yaml:197-398
- **CM endpoint 수 일치** — DRC §11 의 '76 endpoint' 주장이 400.CM/src/router.py 의 @router decorator 수(76)와 일치
  - 근거: grep -c @router 400.CM/src/router.py = 76; .docs/Architectures/DRC_ARCHITECTURE.md:433
- **pipeline 수·chain graph 일치** — DRC §15 '22개 모든 pipeline' = 실측 22개 *.pipeline.json. §13 P03 KIPRIS RAG 3-chain graph(R00→R01→[self|R02], R02 exit)가 실제 dispatch_to 와 일치. tool step 9곳(kipris 2·drawing.render·knowledge·staging.save·maturity.compute·roadmap.persist·cm.save_drawing_artifacts·cm.append_conversation) 실측과 §12 표의 해당 행 일치
  - 근거: find @pipelines -name '*.pipeline.json' = 22; @pipelines/03.finder/P03.R0{0,1,2}.*.json dispatch_to; grep '"tool"' @pipelines 결과
- **AGENT_SDK_DESIGN.md 핵심 주장** — agent_state = vendor 원형 envelope {schema_version, vendor, model, items} 포맷의 유일한 기록처(스키마 파일 없음)이며, vendor 별 export/restore 표·effort 번역(claude→effort, openai→ModelSettings.reasoning(=engine.config 의 reasoning_effort), gemini→ThinkingConfig.thinking_level)이 코드와 일치. fetch_* allowlist 를 6종으로 정확히 기술
  - 근거: .docs/Architectures/AGENT_SDK_DESIGN.md:36-50,93; 300.Actor/src/llm/openai.py:51-54, claude.py:110-113, gemini.py:76-85
- **DIRECTION_PIPELINE_FLOW.md 성격** — §1 = 현행 P02.R00.CONCEPT_MATURITY 8-step(문서 step 번호 0~7 이 flattened 런타임 step id 와 일치 — LLM fixture 파일 0/2/3/4/6.json 로 확인), 이후 본문 전체 = P02.R99.CENTRAL_AGENT 정식 흐름 PlantUML 로 '미구현 target·현재 미활성' 을 문서 자체가 반복 명시
  - 근거: .docs/Architectures/DIRECTION_PIPELINE_FLOW.md:5-22,64; tests/data/llm-fixtures/P02.R00.CONCEPT_MATURITY/ = 0,2,3,4,6.json; @pipelines/02.director/P02.R00.CONCEPT_MATURITY.pipeline.json steps 구조(6 top-level, 병렬 3 묶음)
- **EXTERNAL_API.md 성격** — 인덱스 문서(2.7KB) — 진실 원천을 external_api/{openapi.nexus.json, asyncapi.yaml, README.md} 로 위임. 'make export-openapi'(Makefile:315 존재)·'make endpoint 11 phase'(tests/endpoint/endpoint/cli.py _ALL_PHASES 11개와 일치)·DRO 내부 표면 서술 모두 실측과 일치
  - 근거: .docs/Architectures/EXTERNAL_API.md:1-33; Makefile:315; tests/endpoint/endpoint/cli.py:23-36
- **external_api/CLIENT-HANDOFF.md 성격** — frontend 핸드오프 노트 — REST/WS 계약 + 상태 범례(LIVE/조건부/501 placeholder/결제게이트/future). close code·ErrorCode 어휘·correlation_id 멱등 계약·maturity scores 단축 키(clarity/completeness/potential, C4)가 현행 코드와 일치. 최종 동기화 커밋 = b7dd786(2026-06-28)
  - 근거: .docs/Architectures/external_api/CLIENT-HANDOFF.md:94-136; 100.Nexus/src/ws_inbound.py:117-184; 100.Nexus/src/event_mapper.py:117-119
- **참조 링크 건전성** — Architectures 문서들이 참조하는 파일 전수 실존 — Features/CONCEPT_MATURITY_FLOW.md·DRAWING_FLOW.md, Issues/{AUTH-REDESIGN,EXTERNAL-API,MEDIA,DIRECTOR-R00}-RESIDUALS.md, @contracts/00.dro/websocket-events.json, shared/venezia_contracts/models/dro_api/channels.py(PERSONA_TO_CHANNEL), tests/probe/probe/commands/check.py, tests/invoke/invoke/suites/dro/test_pipeline_walker.py(인용된 테스트 함수 2개 포함), tests/data/iom-samples/smart_beverage_detailed.json 등. 깨진 링크 0건
  - 근거: 존재 확인 batch 실행 결과(전부 OK) + .docs/Issues/ 목록 실측
- **output/draft 빌드 현행** — Nexus POST /api/v1/works/{id}/output/draft 는 DRO POST /control/output 위임으로 IOM→DOCX 동기 변환이 실제 구현되어 있고(C6), DRC §10.1·EXTERNAL_API.md 의 해당 서술은 이 현행과 일치
  - 근거: 100.Nexus/src/router.py:959-985(control_output 호출); 200.DRO/src/router.py:88; 200.DRO/src/docx_generator.py 존재

### .docs/Features + Issues + Report + Verification 문서 신선도

Features 2개·Issues 8개·Report 7개·Verification 1개 문서가 있다. CONCEPT_MATURITY_FLOW.md 와 verification.md 는 코드·tests/ 실측과 전 항목 일치한다 (P02.R00 8 step 구성, ENGINE_MODE, 가중치, event_mapper, 7 track 디렉토리·15 stage·11 phase·5 suite·5 scenario 전부 확인). DRAWING_FLOW.md 는 파이프라인 7개 실재·P06/P04.R11/P05 dispatch 배선은 일치하나, P02.R12 의 step 명/개수·P02.R12→P04/P05 dispatch 배선·P04.R10 self-recursion·drawing.render SMILES 지원 등 4곳이 현행 pipeline JSON/코드와 다르다 (도면 그래프 자체가 P02.R99 미구현으로 현재 미가동인 점은 문서도 명시). Issues/ 는 onboarding 지침이 4개만 나열하지만 실제 8개 파일이며, 전부 "미해소 항목만" 형식으로 유지되고 있고 README 관점 핵심 미구현은 proposal 501·payment no-op·실 OAuth provider 수동검증·P02.R99 미구현이다. Report/ 7개는 dated 분석·결정·backlog 기록으로, INTERFACE-BOUNDARIES 와 CM-CONCURRENCY-MODEL 이 아키텍처 reference 성격이고 나머지는 README 와 무관한 내부 기록이다.

- **전수 목록 — Features** — Features/ 2개: CONCEPT_MATURITY_FLOW.md = P02.R00.CONCEPT_MATURITY(구체화 단계) 8-step chain + 3 산출물(CDS/CMM/UR) + roadmap REST 답변 경로 통합 reference. DRAWING_FLOW.md = 도면 생성 chain dispatch graph(P02.R12/R13, P04.R10/R11, P05.R00/R10, P06.R00) reference — 트리거인 P02.R99 미구현이라 현재 미가동임을 문서 자신이 명시.
  - 근거: .docs/Features/CONCEPT_MATURITY_FLOW.md:1-20, .docs/Features/DRAWING_FLOW.md:153
- **전수 목록 — Issues** — Issues/ 는 8개 파일: DIRECTOR-R00-RESIDUALS.md, EXTERNAL-API-RESIDUALS.md, AUTH-REDESIGN-RESIDUALS.md, DOC-INCONSISTENCY-FOLLOWUPS.md, DRO-ACTOR-INTERFACE-FOLLOWUPS.md(cosmetic 3건 C1~C3), MEDIA-RESIDUALS.md(media 표면 사실+후속 7건), REST-NORMALIZATION-RESIDUALS.md(REST 후속 5절), VERIFICATION-GAPS.md(자동검증 미보장 6영역).
  - 근거: .docs/Issues/ (ls 실측 8 파일)
- **전수 목록 — Report·Verification** — Report/ 7개: ACTOR-REDESIGN-CONSIDERATIONS, CLAUDE-CODE-APPROVAL-AUTO-VS-MANUAL, CM-CONCURRENCY-MODEL, DEFERRED-IDEA-EXECUTION-UNIT, DRO-ROBUSTNESS-BACKLOG, INTERFACE-BOUNDARIES, VERIFICATION-FOLLOWUP-BACKLOG. Verification/ 는 verification.md 1개(7 track 인벤토리).
  - 근거: .docs/Report/ (ls 실측), .docs/Verification/verification.md
- **Issues — DIRECTOR-R00-RESIDUALS** — open 4건: ①roadmap 답변 status=satisfied 가 다음 P02 사이클 LLM 재작성에 pending 으로 뒤집힐 수 있음 ②P03/P06 dialog write 시 schema validation 없음 ③LLM SDK native structured output 이 array root 미지원 — parsing fallback 으로 동작 ④probe view/check/trail/dump-rt 가 CM 의 legacy by-chain alias(/chains/{chain_id}) 에 의존.
  - 근거: .docs/Issues/DIRECTOR-R00-RESIDUALS.md:7-52
- **Issues — EXTERNAL-API-RESIDUALS** — 미해소 index 문서 — REST 8항목(atomic If-Match·OAuth 잔재·media 잔재·proposal 501·payment gate·work subtree 404/error code 통일·roadmap answer partial failure·phase state machine)·WS 8항목(ordered seq cursor·replay/live race·SSE resync·resumable spawn 재개(W5)·slow socket·rate/Origin controls·single-process invariant·scale-out broker)·output(proposal build/preview/download = 501, draft 는 기존 IOM 동기 DOCX 변환)·notifications(multi-device sync event 부재).
  - 근거: .docs/Issues/EXTERNAL-API-RESIDUALS.md:5-37
- **Issues — AUTH-REDESIGN-RESIDUALS** — 미해소 6절: ①PKCE 쿠키(nx_pkce) 멀티탭 덮어씀·실패시 ≤600s 잔존 ②마지막 provider disconnect 시 고아 계정 가능·providers 목록 last-write-wins ③refresh 회전 grace 는 직전 1 jti 만·라이브 WS 소켓 revocation 즉시 전파 미구현(12h 캡) ④Google/Naver/Kakao 실 provider SECURE 검증은 수동 영역 ⑤draft build/download 의 X-Payment-Token 검증 no-op(결제 게이트 미구현) ⑥alias/title 길이·문자 정책 미정.
  - 근거: .docs/Issues/AUTH-REDESIGN-RESIDUALS.md:5-47
- **Issues — DOC-INCONSISTENCY-FOLLOWUPS** — open 1건: validate-stage 단 음성 테스트 부재(tests/validate/tests 디렉토리 없음) — walker 단 음성 테스트는 해소됨(tests/invoke/invoke/suites/dro/test_pipeline_walker.py 실재). 위험도 낮음으로 기재.
  - 근거: .docs/Issues/DOC-INCONSISTENCY-FOLLOWUPS.md:5-11
- **Features — CONCEPT_MATURITY_FLOW 코드 일치** — 핵심 서술 전부 실측 일치: P02.R00 은 8 step(0 extract_stack / 1 staging.save / [2,3,4] score_* 정적 병렬 묶음 / 5 maturity.compute / 6 update_roadmap / 7 roadmap.persist)·dispatch_to null. ENGINE_MODE=FULL 일 때만 P02 spawn. 가중치 clarity 0.30/completeness 0.45/potential 0.25. roadmap 답변 = REST PATCH 단독(roadmap_submit → set_roadmap_item + handle_message). model.maturity/model.roadmap 은 Nexus 가 chain_completed(persona=2) 시 CM fetch 로 생성.
  - 근거: @pipelines/02.director/P02.R00.CONCEPT_MATURITY.pipeline.json(steps·dispatch_to 실측), 100.Nexus/src/message_flow.py:96, 300.Actor/src/tools/maturity/__init__.py:44-47, 100.Nexus/src/router.py:733-770, 100.Nexus/src/event_mapper.py:100-124
- **Verification — verification.md 실측 일치** — 7 track 디렉토리 전수 실재(tests/{validate,lint,invoke,probe,enact,play,endpoint} + data). validate 15 stage(stage_01~06 + contracts/contracts_extended/external_api + stage_10~15 파일·cli 등록 일치), lint 4 runner(ruff/mypy/bandit/pip_audit), invoke 5 suite(shared/cm/dro/actor/account, fail_under=99, coveragerc 실재), probe 13 command(verify/exercise/structure 포함), enact 5 scenario(dispatch/context/tool/concurrency/errors), endpoint 11 phase(_ALL_PHASES 리스트 일치), play flat(_run.py/_sse.py), data 4 dir(llm-fixtures/kipris-fixtures/dro-tapes/iom-samples). Makefile 타깃도 문서와 일치.
  - 근거: tests/validate/validate/stages/(15 파일), tests/validate/validate/cli.py:41-55, tests/lint/lint/runners/, tests/invoke/invoke/cli.py:51-72 + tests/invoke/coveragerc, tests/probe/probe/commands/, tests/enact/enact/scenarios/, tests/endpoint/endpoint/cli.py:23-36, tests/play/play/, tests/data/, Makefile:92-131
- **Report — 각 파일 성격** — ACTOR-REDESIGN-CONSIDERATIONS = Actor composer 미결 결정 9항 + 확정 경계 기록(README 무관, 내부 결정 기록). CLAUDE-CODE-APPROVAL-AUTO-VS-MANUAL = 이 repo 의 Claude Code 권한(자동/수동 승인) 운용 분석(제품 README 와 무관). CM-CONCURRENCY-MODEL = CM per-key asyncio.Lock 동시성 모델 현행 분석 + 다중 인스턴스/dual-writer 위험(강건화 이관) — CM 서술 참고용 reference. DEFERRED-IDEA-EXECUTION-UNIT = 비-AI 실행 유닛(Tool Registry/media) 분리 보류 아이디어(README 무관). DRO-ROBUSTNESS-BACKLOG = DRO 강건화 미착수 backlog + 일시/영구 실패 모델 정의. INTERFACE-BOUNDARIES = 외부↔Nexus·Nexus↔DRO·DRO↔Actor 3 경계 상세 reference(2026-06-28 C8 에서 코드 동기화). VERIFICATION-FOLLOWUP-BACKLOG = 검증 이연 4건(WS payload schema cross-check·restart 회귀 harness·dro:real dedup 폭주 e2e·preview 성공경로 통합테스트).
  - 근거: .docs/Report/*.md 각 파일 전문 + git log(b7dd786 2026-06-28)
- **README 관점 미구현/placeholder 집합** — Issues 문서들이 기록하는 현행 미구현: output/proposal 3 endpoint = 501, draft 결제 게이트(X-Payment-Token) = no-op, 실 OAuth provider(Google/Naver/Kakao) SECURE 검증 = 수동 영역, P02.R99.CENTRAL_AGENT(정식 7-way dispatch) = 미구현 target 이라 도면 그래프(P04/P05/P06 chain)·IOM writer 흐름 미가동, WS rate limit/Origin allowlist/connection cap 부재.
  - 근거: .docs/Issues/EXTERNAL-API-RESIDUALS.md:10-32, AUTH-REDESIGN-RESIDUALS.md:33-40, VERIFICATION-GAPS.md:5-42, .docs/Features/DRAWING_FLOW.md:153

