# Concept Maturity Flow

발명 *구체화 단계* (사용자 발화 → 7 필드 누적 → 3 지표 채점 → 다음 질문 로드맵) 의 통합 reference.

설계 의도 원본은 `.docs/Architectures/STATIC_BLOCK_ARCHITECTURE.md` (수정 금지). 현행 아키텍처 전반은 `.docs/Architectures/DRC_ARCHITECTURE.md`. 본 문서는 *Director (P02) 의 `R00.CONCEPT_MATURITY` chain* 한 가지가 사용자 발화 1건마다 어떻게 진행되는지를 정리한다.

---

## 개요

| 항목 | 값 |
|---|---|
| pipeline_id | `P02.R00.CONCEPT_MATURITY` |
| persona | P2 Director (Claude Opus 4.7) |
| step 수 | 8 (5 Agent + 3 tool) |
| dispatch_to | `null` (self-contained, 다른 페르소나 spawn 안 함) |
| spawn 시점 | 사용자 message.send 마다 (FULL 모드) |
| 평행 chain | P01 Buddy (응대) 가 같은 시점 별도 spawn |

`ENGINE_MODE=FULL` 에서만 spawn. `ENGINE_MODE=SMALLTALK` 은 P01 Buddy 만 spawn하여 응대만 진행 (CDS/CMM/UR 생성·갱신 없음). ENGINE_MODE 는 Nexus config — 코드 위치: `100.Nexus/src/message_flow.py:handle_message`.

---

## 3 산출물

`sessions/{user_id}/{work_id}/models/` 안 3 파일 — *구체화 단계 자체의 출력*.

### CDS — `concept-discovery-stack.json`

| 항목 | 값 |
|---|---|
| writer | P02.R00 step 1 (`staging.save` tool) |
| 의미 | IOM precursor — 사용자 발화 누적 7 필드. 모델 아님. |
| schema | `@contracts/_shared/models/concept-discovery-stack.schema.json` |
| 필드 (7) | `purpose / components / operation_sequence / causality / embodiments / differentiation / effects` |
| 누적 정합 | LLM (step 0) 이 *이전 CDS 위에* 새 사이클 발화 더해 작성. tool (step 1) 은 result 그대로 PUT. |

### CMM — `concept-maturity-model.json`

| 항목 | 값 |
|---|---|
| writer | P02.R00 step 5 (`maturity.compute` tool, 정확 계산) |
| 의미 | 3 지표 + 7 sub_scores + 가중 합산 |
| schema | `@contracts/_shared/models/concept-maturity-model.schema.json` |
| 가중 합산 | `overall = 0.30·clarity + 0.45·completeness + 0.25·potential` |
| sub_scores (7) | `clarity.{purpose, components}` / `completeness.{sequence, causality, embodiment}` / `potential.{differentiation, effect}` |

### UR — `user-roadmap.json`

| 항목 | 값 |
|---|---|
| writer | P02.R00 step 7 (`roadmap.persist` tool) |
| 의미 | "다음 무엇을 입력할지" 안내 — 시간선 자체 |
| schema | `@contracts/_shared/models/user-roadmap.schema.json` |
| 구조 | **top-level JSON array** (file-level meta 없음 — version/last_updated/schema_version 키 없음) |
| item 8 필드 | `id / title / description / status / priority / input_type / options / answer` |
| 누적 정합 | 같은 `id` 의 item 은 보존 + D 안 자연 누적. 해소된 item 도 list 안 남음 (시간선). |

---

## 8 step 흐름

```text
[Nexus] WS message.send 또는 REST PATCH .../estimate/roadmap/{item_id} (roadmap 답변)
  ↓ message_flow.handle_message (Nexus message_flow — Nexus 가 게이트웨이)
[P02.R00.CONCEPT_MATURITY chain spawn]  (FULL 모드만, P01 과 평행)
  │
  ├─ step 0  extract_stack            (Agent) — CDS 7 필드 갱신 LLM
  │     inject: conversation, current_stack(=CDS)
  │     output_contract: staging-stack-output
  │
  ├─ step 1  staging.save              (tool)  — CDS PUT
  │     params: $.steps.0 의 7 필드
  │     output_contract: staging-stack-saved-output
  │
  ├─ step 2  score_clarity             (Agent) — 아이디어 구체도 (purpose / components)
  │     inject: stack_purpose, stack_components (CDS 부분 pointer read)
  │     output_contract: clarity-sub-scores-output
  │
  ├─ step 3  score_completeness        (Agent) — 설명의 완전성 (sequence / causality / embodiment)
  │     inject: stack_sequence, stack_causality, stack_embodiments
  │     output_contract: completeness-sub-scores-output
  │
  ├─ step 4  score_potential           (Agent) — 특허성 잠재력 (differentiation / effect)
  │     inject: stack_differentiation, stack_effects
  │     output_contract: potential-sub-scores-output
  │
  ├─ step 5  maturity.compute          (tool)  — 가중 합산 + CMM PUT
  │     params: $.steps.{2,3,4}
  │     output_contract: maturity-compute-output
  │     → DRO 미발사. Nexus 가 chain 완료[persona=2] 시 CM 에서 CMM fetch 로 model.maturity WS 생성 (#12)
  │
  ├─ step 6  update_roadmap            (Agent) — top-level array, 4-mode reasoning
  │     inject: conversation, CMM, CDS, user_roadmap
  │     output_contract: update-roadmap-output (RFC 6901 array root)
  │     4-mode: 분화 / 해소 / 신설 / 유지 (같은 id 보존)
  │
  └─ step 7  roadmap.persist           (tool)  — UR PUT
        params: $.steps.6 (top-level array)
        output_contract: roadmap-persisted-output
        → DRO 미발사. Nexus 가 chain 완료[persona=2] 시 CM 에서 UR fetch 로 model.roadmap WS 생성 (#12)
  ↓ chain_completed → DRO 가 raw SSE 로 Nexus 통보 → Nexus 가 chain 완료[persona=2] 시 model.maturity/model.roadmap 생성 (P02 chain 은 reply 미발사 — reply 는 P01 응대 답장 전용)
```

step 2/3/4 채점은 **정적 병렬 묶음** (step list nesting `[step2, step3, step4]`, asyncio.gather — 독립 채점 동시 실행, D-6). Actor P02 cap=2 라 2씩 처리. 나머지 step 은 직렬.

---

## WS event 2 종

DRO 는 model WS 를 발사하지 않는다 (#12). Nexus 가 P02 chain 의 `chain_completed`(persona=2) raw SSE 를 받으면 CM 에서 CMM/UR 를 fetch 해 외부 비즈니스 event (`model.maturity` / `model.roadmap`, envelope v2 `{type,timestamp,seq,data}`) 를 생성하고 WS 로 broadcast 한다. 이벤트는 best-effort 알림 — 진실은 CM 이고, 누락 시 client refresh 로 복구 (#15).

| event | payload | trigger | client 동작 |
|---|---|---|---|
| `model.maturity` | `{overall_score, scores, weights}` | chain 완료[persona=2] 시 Nexus 가 CM 에서 CMM fetch | UI 의 게이지·점수 갱신. `GET /api/v1/works/{id}/estimate/maturity` 로 fresh fetch (선택). |
| `model.roadmap` | `{count?}` | chain 완료[persona=2] 시 Nexus 가 CM 에서 UR fetch | UI 의 로드맵 list 갱신. `GET /api/v1/works/{id}/estimate/roadmap` 으로 fresh fetch. |

스키마: `@contracts/00.dro/websocket-events.json`. 코드 위치: DRO 는 model WS raw emit 안 함; Nexus 측 chain_completed fetch·변환·발사 = `100.Nexus/src/event_mapper.py` + `event_consumer.py`.

---

## Roadmap 답변 입력 경로

사용자가 roadmap item 에 답하는 경로는 **REST 단독**이다 (WS inbound action 아님 — WS inbound 는 `message.send` 1종(멱등 correlation_id)).

`PATCH /api/v1/works/{work_id}/estimate/roadmap/{item_id}` + body `{value}`:

1. CM item 을 atomic update — `answer` + `status=satisfied` 기록, 갱신된 item 반환. `input_type` 은 저장된 item 에서 도출.
2. 이어서 structured user turn append + chain spawn — `message_flow.handle_message(content, user_turn_meta={kind:"roadmap.answer", roadmap_item_id, input_type})`:
   - Nexus 가 `runtime/00.dro/conversation.json` 에 user turn `{role:"user", content, meta:{kind,roadmap_item_id,input_type}, timestamp}` append.
   - P01.R00 + P02.R00 chain spawn (FULL 모드).
3. 다음 P02 사이클의 LLM 이 conversation 을 보고 UR 을 재평가 — `models/user-roadmap.json` 해당 id item 의 `status/answer` 확정 (D 안 정합, 매 사이클 LLM 전체 재작성).

`meta.kind = "roadmap.answer"` 는 conversation turn 의 메타데이터일 뿐, WS action 이 아니다.

코드: `100.Nexus/src/router.py` 의 roadmap_submit → `set_roadmap_item` + `message_flow.handle_message`.

---

## ENGINE_MODE 분기

| ENGINE_MODE | P01 Buddy chain | P02 Director chain | CDS/CMM/UR 생성·갱신 | maturity/roadmap WS event |
|---|---|---|---|---|
| `FULL` | spawn | spawn | yes | 발사 |
| `SMALLTALK` | spawn | **미 spawn** | no | **0건** |

코드: `100.Nexus/src/message_flow.py:handle_message`. ENGINE_MODE 는 Nexus config. 별도 환경변수 신설하지 않음.

---

## R/W contract (RFC 6901 / 6902)

구체화 단계의 모든 CM 자료 (CDS/CMM/UR/conversation) read·write 는 다음 표준 따름.

### 부분 read — RFC 6901 JSON Pointer

```
GET /sessions/{u}/{i}/models/concept-discovery-stack?pointer=/purpose
```

- `pointer` 미지정 = 전체 root
- `pointer=/sub/path` = 해당 subtree 만 서버측 응답 (`jsonpointer.resolve_pointer`)
- 모든 model GET endpoint 에 `?pointer` 인자 적용 (IOM/CMM/CDS/UR/conversation)

### 부분 write — RFC 6902 JSON Patch

```
PATCH /sessions/{u}/{i}/models/concept-maturity-model
Content-Type: application/json
[
  {"op": "add", "path": "/scores/clarity", "value": 0.7}
]
```

- body = `list[dict]` (ops array)
- 6 operations: `add / remove / replace / move / copy / test`
- `path` = RFC 6901 표기 (같은 표준)

### `cm://` 표기 (pipeline.json 의 inject_context)

| 표기 | 의미 |
|---|---|
| `cm://invention_object_model` | IOM root 전체 |
| `cm://concept_discovery_stack/purpose` | CDS 의 `/purpose` subtree |
| `cm://conversation` | conversation 전체 |
| `cm://user_roadmap` | UR top-level array 전체 |

dot-path 표기 (`cm://X.dot.path`) 는 허용 안 됨 — validate stage 6 (`tests/validate/validate/stages/stage_06_cm_pointer.py`) 가 발견 시 fail.

코드 path: composer 의 `_cm_fetch` (300.Actor/src/dispatcher.py) + orchestrator 의 `_resolve_inject_context` (200.DRO/src/orchestrator.py) 가 *항상* server-side `?pointer=` 로 forward. client-side walk 코드 자체 없음.

---

## P02.R99.CENTRAL_AGENT 와의 관계

`P02.R99.CENTRAL_AGENT` 는 정식 메인 루프 (7-way dispatch graph) — **미구현 target**. 작성 단계 마일스톤에서 활성화 예정. 현재는 본 P02.R00.CONCEPT_MATURITY 가 구체화 단계 전용 임시 self-contained chain 으로 동작한다 (`dispatch_to: null`).

`P02.R10.DIRECTOR_GAP_ANALYSIS` / `P02.R12.DRAWING_ORCHESTRATION` 등 R99 의 dispatch graph 노드들은 **활성화 시점을 위해 보존**.

---

## 설계 결정 근거

| 결정 | 근거 |
|---|---|
| weights `0.30·clarity + 0.45·completeness + 0.25·potential` | completeness 가중 (sequence/causality/embodiment 가 특허 명세서 작성에 가장 직결) |
| UR top-level array (file-level meta 없음) | *시간선 자체* — `version` 같은 추상화 layer 없이 같은 id 보존이 자연. 해소 item 도 남아 history |
| CDS 와 IOM 분리 | CDS = 사용자 발화 누적 (모델 아님). IOM = 정형화된 발명 객체 모델 (작성 단계 — 별도 마일스톤). 구체화 단계는 IOM 안 채움 |
| ENGINE_MODE FULL/SMALLTALK | 별도 환경변수 신설 안 함. SMALLTALK 은 응대만 빠르게 — Director 비용 절감 |
| roadmap 답변 = REST PATCH 단독 (WS action 아님) | 즉시 atomic 확정(answer+status=satisfied) + 인터페이스 단순화 — WS inbound 는 `message.send` 1종(멱등 correlation_id) |
| `cm://` server-side pointer 강제 | R/W 비대칭 해소 — 둘 다 RFC 6901 통일 |

---

## 검증

| 트랙 | 명령 | 통과 기준 |
|---|---|---|
| validate | `make validate` | 15 stage 모두 pass (stage 15 = 정적 병렬 묶음 형태). stage 6 (cm:// pointer notation) 이 dot-path 불허 강제 |
| play | `make play P02.R00.CONCEPT_MATURITY` | probe `verify_chain` 9 invariants 통과 (FIXTURE 모드에서 자동 — RT state=done / composer keys / prompt_chars / context.steps 누적 / response_schema / placeholder + tool 3종은 트레일 데이터 있을 때) |
| endpoint | `make endpoint` | `ws` phase 통과 (message.send full-cycle + 멱등 재시도) · roadmap 답변은 REST `work_resources` phase |
| 4 모드 | `make deploy init engine {full,smalltalk} llm {real,fake} && make up` | 모두 `make endpoint` 통과 |

`ws` phase는 message.send 후 message.received/work.progress/message.reply와 멱등 재시도(같은 correlation_id) 정상 처리를 검증한다. dro:fake에서 message.reply는 hard assertion이다. model.maturity/model.roadmap은 dro:fake의 CM 값이 비어 있어 `ws` phase에서는 발생을 요구하지 않고, mapper unit test와 real 경로가 담당한다. Roadmap 답변은 REST `work_resources` phase에서 검증한다.

---

## 인접 영향 (별도 마일스톤)

- **작성 단계** (IOM 채움 + 출원서 작성) — 구체화 단계가 *충분히 성숙* 했을 때 진입. 본 문서 scope 외.
- **P03 Finder / P04 Thinker / P05 Crafter / P06 Inspector** — 구체화 단계에서 spawn 안 함. dispatch_to=null 보장.
- **`STATIC_BLOCK_ARCHITECTURE.md`** — 설계 의도 원본, 수정 금지.

---

## 잔재·미해결 issue

`.docs/Issues/DIRECTOR-R00-RESIDUALS.md` 참조 — 구체화 단계 도입 이후 알려진 잔재 (status=satisfied 자동 처리, manifest.context enum 미정의 등).
