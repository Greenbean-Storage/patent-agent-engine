# 검증 도구 (7 track)

본 프로젝트의 검증 도구 인벤토리. 7 동등 track — 각 track 가 자체 uv project,
`make <verb>` 단일 인터페이스, 동일 scaffolding (pyproject + README + `<verb>/{__init__,__main__,cli}.py`
+ sub-modules). (enact 는 시나리오 5/5 정식 게이트 + 단건 수행 모드.)

> 용어 — "track" 은 동등-위치 검증 도구 그룹. 위계 함축어 (layer/tier) 의도적 회피.
> Google Play 의 "test tracks" (internal/closed/open/production = N peer-equal groupings) 와 같은 결.

---

## 1. 7 track 개요

| # | track | dir / pkg | Make | Stack | 본질 |
|---|-------|-----------|------|-------|------|
| 1 | **validate** | `tests/validate/` | `make validate` | ✗ | JSON 산출물 schema · cross-ref · tool registry 정적 정합 |
| 2 | **lint** | `tests/lint/` | `make lint` | ✗ | 코드 자동수정+검사 일괄 (ruff --fix+format · mypy · bandit · pip-audit, 4개 다 게이트) |
| 3 | **invoke** | `tests/invoke/` | `make invoke` | ✗ | 스택 없이 로직 검증 — 5 패키지(shared·cm·dro·actor·account) 라인 99% (유일한 라인-커버리지 트랙) |
| 4 | **probe** | `tests/probe/` | `make probe <sub>` | ✓ | 실 CM 블랙박스 — 관찰/구성/제어 + `verify` 게이트(CM API 전수 + scaffolding 구조검증). 라인-커버리지 아님 |
| 5 | **enact** | `tests/enact/` | `make enact` | ✓ | Actor 단일 RT 수행 격리 — **시나리오 5/5 정식 게이트** (dispatch·context·tool·concurrency·errors) + 단건 수행 모드 (P{NN}.R{NN} step / ad-hoc spec·인라인) |
| 6 | **play** | `tests/play/` | `make play [P{NN}.R{NN}]` | ✓ | pipeline 실행 (無인자 = root 전수) + dual 관측 (CM trail polling + DRO RAW SSE) + dispatch chain BFS follow |
| 7 | **endpoint** | `tests/endpoint/` | `make endpoint [<phase>]` | ✓ | 외부 API REST + WS contract e2e (dual-scope — dro:fake 면 tape suite 포함) |

모든 Python 도구는 **uv** 로 실행 (`uv sync` / `uv run`). pip / poetry 금지.

---

## 2. 언제 무엇을 돌리나

| 시점 | track |
|------|-------|
| 개발 중 즉각 sanity | `make validate` (수초) |
| commit 직전 | `make lint` (ruff 자동수정+format + mypy/bandit/pip-audit) |
| PR 직전 / CI | `make validate` + `make lint` + `make invoke` (5 패키지 라인 99%) |
| pipeline 회귀 검증 | `make deploy init llm fake auth open` → `make up` + `make play P{NN}.R{NN}` |
| 외부 API contract 회귀 | `make deploy init llm fake auth open` → `make up` + `make endpoint` |
| CM 전 API + 메모리 구조 검증 | `make deploy init llm fake auth open` → `make up` + `make probe verify` (CM API 전수 + scaffolding) |
| Production smoke | `make deploy init` → `make up` + `make endpoint` + `make play P{NN}.R{NN}` |
| 빠른 응대만 dev | `make deploy init engine smalltalk llm fake auth open` → `make up` (P02 director OFF, P01 만) |
| 디버깅·관찰 (런타임) | `make probe <view\|trail\|check\|seed\|list\|list-chains\|dump-rt\|models\|dialogs\|clean\|structure\|exercise>` |

---

## 3. 각 track 상세

### 3.1 validate — JSON 정적 정합 검증

**Stage 15 종** (모든 구조적 파일 전수 — discover, don't hardcode):
- Stage 1 — Pipeline JSON jsonschema Draft 7 strict (`@contracts/_shared/pipeline-definition.schema.json`)
- Stage 2 — 4-layer cascading (`shared/venezia_pipeline_runtime.loader`) + `effective_llm_tools` allowlist
- Stage 3 — Cross-reference (step.output_contract 파일 존재, 4-layer name+source 중복, dispatch_to.actions 길이 ↔ dispatch_choice maximum, actions[*][*] pipeline_id 실재, **step.instructions.reference .md 파일 존재**)
- Stage 4 — Tool registry 정합 (pipeline tool step ↔ `300.Actor/src/tools/` 의 `@register`)
- Stage 5 — `$.inputs.<custom>` placeholder 금지
- Stage 6 — cm:// pointer 표기 (RFC 6901 slash 통일)
- Stage 7 — Contracts meta-schema (`@contracts/**/*.json` **전수** Draft 7)
- Stage 8 — Contracts extended (IOM schema + sample IOM, **hard-fail**)
- Stage 9 — 외부 API OpenAPI **풀 메타검증**(openapi-spec-validator) + D6/D9/A3/A4 hygiene
- Stage 10 — WS contract 3원 cross-consistency (`websocket-events.json` ↔ `asyncapi.yaml` ↔ `channels.py:PERSONA_TO_CHANNEL`)
- Stage 11 — dead contract schema 탐지 (미참조 stage schema, **WARN**)
- Stage 12 — 인프라 설정 YAML (`scaffolding.yaml` / `topology.yaml` / `compose.yaml` / `knobs.yaml` 구조·파생 정합 + `engine.config.yaml` — `engine-config.schema.json` Draft 7 검증 + **persona-id 4원 정합 게이트** (engine.config personas ↔ channels.py ↔ venezia_memory PERSONA_DIRS ↔ @pipelines 디렉토리))
- Stage 13 — `asyncapi.yaml` 풀 메타검증 (AsyncAPI 3.0.0 vendored, 오프라인)
- Stage 14 — 커버리지 census (모든 구조적 파일이 stage 또는 data-allowlist 로 분류되는지 보장) + pyproject 정합
- Stage 15 — 정적 병렬 묶음(nested list) 형태 (D-6: 명시 id 필수·id 유일·instructions XOR tool·깊이 1)

**호출**:
```
make validate                                                 # 22 P{NN} + 전 구조적 파일 전수 (15 stage)
cd tests/validate && uv run python -m validate --pipeline P03.R00.PRIOR_ART_SEARCH_ANALYZE
```

---

### 3.2 lint — 코드 자동수정+검사 일괄

`make lint` 한 명령이 **자동수정·포매팅·검사를 모두 수행**(별도 format 단계 없음). 4 runner 모두 게이트 —
전부 exit 0 이어야 PASS (advisory baseline 없음). auto-fix 불가분(E501 등)만 잔여로 남아 FAIL.

**4 runner**:
- **ruff** — lint + format **자동 적용**(`ruff check --fix` + `ruff format`, write) → 검사
- **mypy** — type check (각 패키지 별 호출, `<pkg>/src/` 패턴 자동 처리)
- **bandit** — code security pattern (SAST)
- **pip-audit** — dependency CVE (pyproject.toml + uv.lock)

**호출**:
```
make lint                                # 4 runner 일괄 (자동수정+검사)
cd tests/lint && uv run python -m lint --runner ruff
```

---

### 3.3 invoke — 스택 없이 로직 검증 (유일한 라인-커버리지 트랙)

"이슈 날 만한 로직 스니펫을 스택 없이 검증" → 라인 커버리지 **99%** 로 확대. **5 suite**
(각 컨테이너 venv 별 ephemeral pytest, path-scoped `suites/{pkg}/`). 전부 `--cov-fail-under=99`:
- **shared** — `venezia_*` (pipeline_runtime / memory / topology / contracts / logging / deployment)
- **cm** — 400.CM/src (가짜 S3 + ASGITransport 로 스택 없이 CM 로직 구동)
- **dro** — 200.DRO/src
- **actor** — 300.Actor/src
- **account** — 100.Nexus/src

**제품 코드에 검증 흔적 0** — coverage 의 omit/exclude 설정은 제품 pyproject 가 아니라
검증 트랙(`tests/invoke/coveragerc`)에만 둔다. `cli.py` 가 각 suite pytest 에 `--cov-config` 로
전달. 제품 src 에 `# pragma: no cover`·pyproject 에 `[tool.coverage]` 두지 않음 (방어 분기는 99% 슬랙으로 흡수).

**호출**:
```
make invoke                                # 5 suite (각 라인 99%)
cd tests/invoke && uv run python -m invoke --suite cm
```

contracts / pipeline_validator self-test 등 static 검증은 validate 가 흡수했으므로 invoke 에서 제외.
CM 의 *실 동작*(실 S3·전 API)은 probe `verify` 가 라이브로 별도 검증 — 레이어가 다름(중복 아님).

---

### 3.4 probe — 실 CM 블랙박스 도구 (관찰/구성/제어 + 검증 게이트)

probe 는 **실제로 띄운 CM 을 제품 밖에서 블랙박스로** 다룬다. **라인-커버리지가 아니다**(그건 invoke).
검증은 ① CM 의 *전 API* 가 실제로 도는지, ② 세션의 *실 S3 메모리 구조* 가 scaffolding 과 맞는지.

**검증 게이트** (라이브 stack 필요):
- **`probe verify`** — probe 트랙의 단일 게이트. 임시 세션 하나에 **(가) exercise + (나) structure** 를
  돌리고 정리(clean). 둘 다 통과해야 exit 0. CM 무인증 → OPEN/SECURE 무관(mode-agnostic).
  - **(가) exercise** — CM `/openapi.json` 으로 전 endpoint 열거 → resource-type별 모든 API(정상+에러) 전수 호출. "CM 코드 다 활용"(API 표면 100%, 라인 계측 아님).
  - **(나) structure** — 세션의 실 S3 키(`/tree`) ↔ scaffolding + manifest 4종 대조: orphan 0 · 필수 충족 · manifest 일치 · resource-type 관찰 ≥99%.
- **`probe exercise`** / **`probe structure <inv>`** — 위 (가)/(나) 를 단독으로도 실행.

**관찰/구성/제어** (디버깅용 sub-command):
- 관찰: `view` / `trail` / `check`(9 invariants) / `list` / `list-chains` / `dump-rt` / `models` / `dialogs`
- 구성/제어: `seed`(IOM 적재) / `clean`(invention 삭제)

**호출** (`make probe <sub>` + 필요 시 `IOM= USER_ID= INVENTION_ID= YES=1` make var):
```
make probe verify                       # probe 게이트 (CM API 전수 + scaffolding) — 임시 세션, 자동 clean
make probe exercise                     # CM 의 모든 API 전수 호출
make probe structure <work_id>     # 세션 S3 구조 ↔ scaffolding + manifest 대조
make probe view <chain_id>              # chain 전체 (RT + trail + IOM + drawings) 표시
make probe check <chain_id>             # 9 invariants 정합 검사
make probe seed IOM=<path>              # IOM JSON CM 적재
make probe list / list-chains / dump-rt / models / dialogs / trail   # 관찰
make probe clean <work_id> YES=1   # invention 삭제 (DELETE, 되돌릴 수 없음)
```

구조검증 로직(`classify_key` / `verify_structure`)은 **probe 트랙 안**(`tests/probe/probe/_structure.py`)에 둔다 —
오직 probe 만 소비하므로 제품 라이브러리(`venezia_memory`)엔 두지 않음. venezia_memory 는 레이아웃 *사실*
(파일명/경로 상수·key-builder)만 제공. CM `GET /tree`(세션 실 키 전수) 는 정당한 CM read 기능.

play track 이 probe 의 `seed` / `check` 를 **라이브러리** 로 import 사용 (CLI 와 별개).

---

### 3.5 enact — Actor 단일 RT 수행 (track 5 — 정식 게이트, 시나리오 5/5)

**UUT = real Actor 1 컨테이너** (`actor:real`) · harness = DRO 역할 대행 (RT 를 실 pipeline
합성으로 CM 에 seed → `POST /dispatch` SSE 소비 / `POST /tool` 직접 호출 → CM 부수효과 관측)
· mock-below = `llm:fake` + real CM. 설계·사용법 = `tests/enact/README.md`.

- **시나리오 5종 (게이트)**: `make enact` 無인자 = 전수 + 집계 / `make enact <scenario>` 단일.
  - **dispatch** — 정상 1 RT: SSE 순서(started→progress*→result)·RT done+dispatch-result 계약·structured=response_schema·agent_state envelope·trail.
  - **context** — 컨텍스트 ② 실왕복: 같은 chain step0→step1, envelope items 2→4 + step0 items prefix 보존.
  - **tool** — `POST /tool` 계약: 200 `{status:success, result}` · 404 not_found · 400 bad_params(params 비-dict / 미지 kwarg) · 500 exception (순수 tool — CM-write 0). 503 은 concurrency 가 동일 계약 커버.
  - **concurrency** — persona cap 503: P2(cap 2) chain 에 RT 3개 → `dispatch_concurrent`(gather 동시 진입, release 가 SSE body 소진 시점이라 acquire 몰림이 먼저 → 결정적 cap+1 째 503) → 정확히 1개 503+`Retry-After`, `/health.slots` inflight 관측.
  - **errors** — SSE error 4경로: persona 미등재·RT 부재·composer 키 결손·legacy 평문 agent_state, 각 started→error(result 0) + message 패턴.
  - 전수 green = **정식 게이트** (exit 0). FIXTURE 가드(`/health.llm_mode`)·환경 부재 = exit 2.
- **단건 수행 모드 (관측 도구 — B4)**: `make enact P01.R00 0` (실 pipeline step RT 합성·수행·관측)
  / `make enact <spec.yaml>`·`make enact PERSONA=2 PROMPT="…"` (ad-hoc — persona+프롬프트 차터
  직접: instructions(지침)/inject_context(cm://·@knowledge/)/fragments(literal 강제 텍스트)/
  llm_tools/response_schema·output_contract). 수행 + SSE/불변식 출력, PASS 시 네임스페이스 정리.
- exit 규약: 0=green · 1=검증 FAIL · 2=사용법/환경. RT 합성은 loader+walker+`_build_rt_input`
  동형 미러 — drift 가드 = `reasoning_task` 계약 `assert_valid` + 실 Actor done.

---

### 3.6 play — pipeline 실행 (단위 트랙)

순수 pipeline runner. 부팅·환경 관리 같은 비-검증 동작 X (stack utility 별도).
**stack MODE 자동 감지** (`@deployment/profile.stack.yaml` 의 llm knob 직접 read — `venezia_deployment.runtime.llm()`)
— FIXTURE 일 때만 invariants check 자동 호출, PRODUCTION 일 때 skip. 수동 flag 없음.
**dispatch_to spawn chain BFS** 자연 follow + **dual 관측**: ① CM trail polling ② DRO RAW SSE
(`raw-sse-event` schema·seq 단조·≥1건 자동 assert). **raw_asserts**: 완료된 RT.output 전건을
`dispatch-result` 계약으로 검사 (drift guard) — 위반 = FAIL.

**호출**:
```
make play                                                        # 無인자 = root pipeline 전수 (*.R00.* 순차 + 집계)
make play P03.R00                                                # 단일 pipeline
make play P03.R00 SEED=path/to/iom.json WS_TIMEOUT=1800
```

stack 사전 부팅 필요 — `make deploy init [<knob> <value>...]` (모드 설정) → `make up`. 모드 = profile knob (engine=full|smalltalk · llm=real|fake · auth=open|secure), positional 없음.

---

### 3.7 endpoint — 외부 API REST + WS contract e2e (통합검증, dual-scope)

**11 phase** (새 트리 info/user/works, OPEN 모드 기준):
- `health` — `GET /health` (DRO·Nexus): auth_mode/engine_mode/llm_mode, 두 컨테이너 일치
- `info` — `GET /api/v1/info/{providers,attributions}`
- `account` — `GET /user/account` + `GET·PUT /user/account/alias` (PII 0)
- `works` — `POST /user/works` + `GET /user/works` + `GET·PATCH /works/{id}/meta`
- `auth` — `GET /user/auth/{google,naver,kakao}/authorize` (URL+state, 실 IdP 미호출) · unknown provider 404
- `work_resources` — `GET·PATCH phase` · `thread/messages` · `estimate/{GET roadmap, maturity}` · `PATCH estimate/roadmap/{item_id}` · `media`(POST·목록·GET {id}·{id} DELETE) (전부 Nexus — DRO 는 client REST 없음)
- `output` — draft build/download/preview + proposal placeholder와 output error contract
- `ws` — WS `thread/stream`: message.send(correlation_id 멱등)→message.received(unicast, `{correlation_id,id}`) · 같은 correlation_id 재send 멱등 무에러 · envelope v2 `{type,timestamp,seq,data}`(scope/subject_id 없음) · chain 구동 이벤트(work.progress/message.reply/work.failed 등) (dro:fake = hard / dro:real = warn)
- `ws_tape` — **포괄 tape suite** (dro:fake 전용, dro:real 이면 skip-pass) — `tests/data/dro-tapes` 케이스별 expected assert
- `error_envelope` — 404 `work_not_found` + 422 `validation_failed`
- `secure` — SECURE 전용 (무토큰→401 · 토큰→200 · WS 쿠키 인증·무토큰 4401 close) — OPEN 이면 skip

phase 명은 **외부 API 표면의 도메인 객체 그대로** — `legacy_*` / `deprecated_*` 명명 사용 X.

**호출**:
```
make endpoint                            # 모든 11 phase
make endpoint health                     # 단일 phase
make endpoint ws_tape TAPE=P01.R00.CHAT_CONVERSATION/02-rt-error-message   # 그 tape 만
make endpoint call REST="GET /api/v1/info/providers"   # 단건 호출 UI (탐색/디버그)
make endpoint call WS='message.send {"content":"..."}'
```

---

## 4. Stack utility (검증 verb 아님)

> 모드 = `@deployment/profile.stack.yaml` knob (마운트 → `venezia_deployment` 런타임 read). `make deploy` 로 설정, `make up` 은 positional 없음. profile 부재 시 `make up` fail-loud.

```
make deploy init llm fake auth open       # 로컬/검증: FULL + FIXTURE + OPEN
make deploy init engine smalltalk llm fake auth open  # P01 만 (director OFF) + FIXTURE
make deploy init                          # 실 운영: 전 default = FULL + PRODUCTION + SECURE (EC2 IAM)
make up                  # profile 대로 풀 reset (positional 없음)
make down                # stack 종료 + image/volume 제거
make ps / make logs      # 컨테이너 상태 / 로그
```

> `up` 은 `docker compose down/build/up` (모드 = profile, build.target = `.env.deploy`) 만 — pipeline runner (play) 와 본질 무관.
> 스택 기동은 반드시 `make up` (profile → `.env.topology`/`.env.deploy` 생성 후 build/up). 직접 `docker compose up` 은
> 그 생성 단계를 건너뛰어 stale/미생성 `.env.deploy` 로 기동되니 금지. play 는 부팅 방식 일절 모름 (DRO REST + CM trail polling 만).

---

## 5. 설계 원칙

1. **기능·효과 보존, 코드/구조 자유 변경** — 기존 검증 기능 (pipeline 정적 검증 / chain 9 invariants / viewer trail / seed IOM 적재 / endpoint phase / smoke 모듈 import 등) 은 새 위치·새 인터페이스에서도 **동일 효과**. 코드/구조/모듈 분할은 마음껏 재작성.
2. **chain dispatch graph 자연 follow** — play 는 1 pipeline 실행이지만, dispatch_to spawn 된 후속 chain (P02→P03 등) 도 BFS follow.
3. **probe 는 실 CM 블랙박스 도구** — 라인-커버리지가 아니라 실 CM 의 *전 API 동작* + *실 S3 메모리 구조* 검증(`verify`). play 가 probe 의 일부 기능(`seed`/`check`)을 라이브러리로 import.
4. **uv 만 사용** — Python 도구는 `uv sync` / `uv run` 만.
5. **play 는 stack 무관 디버깅 채널** — Docker 일절 모름. DRO REST(/control/spawn + /control/output[docx 빌드, C6] + /events SSE) + CM trail polling 만.
6. **play 가 stack MODE 자동 감지** — `@deployment/profile.stack.yaml` 직접 read → fixture 면 invariants 자동, production 이면 skip. 수동 flag 없음.
7. **제품 코드에 검증 흔적 0** — 라인 커버리지는 **invoke 가 유일**(5 패키지). coverage omit/exclude 설정은 검증 트랙(`tests/invoke/coveragerc`)에만, 제품 src/pyproject·`shared` 엔 `# pragma`·`[tool.coverage]`·검증 전용 로직을 두지 않는다. invoke(스택 없는 고립 로직 99%) 와 probe(실 CM 라이브 API+구조) 는 **레이어가 다른 검증** — CM 이 양쪽에 나오는 건 중복이 아니라 의도된 다층 검증.

---

## 6. 인벤토리 (track / dir / pkg / Make 한 표)

```
tests/
├── validate/                 — make validate         (no stack)
├── lint/                     — make lint             (no stack)
├── invoke/                   — make invoke           (no stack)
├── probe/                    — make probe <sub>      (stack)
├── enact/                    — make enact            (시나리오 5/5 정식 게이트 + 단건 수행 모드)
├── play/                     — make play [P{NN}.R{NN}] (stack — 無인자 = root 전수)
├── endpoint/                 — make endpoint [<phase>] (stack)
└── data/                     — llm-fixtures / kipris-fixtures / dro-tapes / iom-samples (data, 검증 도구 아님)
```

각 track 동일 scaffolding:
```
tests/<verb>/
├── pyproject.toml           # hatchling, [project.scripts] entry, [tool.ruff] py313
├── README.md                # 목적 / scope / 호출 / 의존 / 산출
├── <verb>/
│   ├── __init__.py
│   ├── __main__.py          # `uv run python -m <verb>` entry
│   ├── cli.py               # argparse 분기
│   └── <stages|runners|suites|commands|phases>/   # play 는 sub-dir 없이 flat (_run.py·_sse.py)
└── .venv/                   # uv sync 산출 (gitignore)
```
