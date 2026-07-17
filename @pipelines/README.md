# @pipelines (DRC P{NN} 포맷)

AI Agent 파이프라인 정의 — DRC (Distributed Reasoning Chain) 의 chain dispatch graph.

## 디렉토리 구조

```text
@pipelines/
  manifest.pipeline.yaml      # P{NN} 인덱스 + dispatch 그래프 (persona 정의 SoT = @deployment/engine.config.yaml)
  _shared/
    GLOBAL.json               # GLOBAL layer (모든 persona·pipeline 공통)
  01.buddy/
    P01.COMMON.json           # persona layer (Buddy 공통)
    P01.R*.pipeline.json      # 10 entry/sub pipelines
  02.director/
    P02.COMMON.json
    P02.R*.pipeline.json      # 7 entry/sub pipelines
  03.finder/
    P03.COMMON.json
    P03.R*.pipeline.json      # 6 entry/sub pipelines
  04.thinker/
    P04.COMMON.json
    P04.R*.pipeline.json      # 4 sub pipelines
  05.crafter/
    P05.COMMON.json
    P05.R*.pipeline.json      # 2 sub pipelines
  06.inspector/
    P06.COMMON.json
    P06.R*.pipeline.json      # 1 sub pipeline
```

## 파일명 규칙: `P{NN}.R{NN}.{UPPER_SNAKE}.pipeline.json`

- **P{NN}** — Persona 번호 (01~06)
- **R{NN}** — Role 번호 (R00 = entry, R10~ = sub 흐름)
- **{UPPER_SNAKE}** — 의미 이름 (대문자 + underscore)

예: `01.buddy/P01.R00.CHAT_CONVERSATION.pipeline.json`

## 핵심 설계 (DRC)

- **chain dispatch graph** — pipeline 끼리 직접 `sub_pipeline` 호출 없음. 마지막 step 이 `dispatch_choice` (integer enum) 출력 → `dispatch_to.actions[choice]` 의 pipeline_id 들이 다음 chain 으로 생성됨.
- **chain self-recursion** — loop 폐기. 같은 pipeline_id 를 dispatch_to 에 넣으면 자기 chain 재호출 (max_self_recursion 가드).
- **list nesting = 정적 병렬** — `steps: [..., [s1, s2, s3], ...]` 의 nested list 가 fan-out group.
- **Actor 직접 통신 금지** — cross-persona 협력은 (1) DRO 의 user-driven 동시 enqueue (P01+P02 평행) 또는 (2) chain dispatch graph (자기 chain 의 dispatch*to 로 다음 페르소나 chain trigger, 예: P02→P05) 로만. P01 같은 응대 페르소나는 self-contained (다른 페르소나 dispatch 없음). LLM 의 `llm_tools` 는 self-chain `fetch*\*` 만 허용.

## 4-layer Cascading

각 step 의 `inject_context` / `recommended_context` / `fragments` / `llm_tools` 는 4 layer 머지:

```
GLOBAL.json
  → P{NN}.COMMON.json (persona)
    → pipeline.common (pipeline 레벨)
      → step (step 레벨)
```

같은 키 + 같은 source 가 두 layer 에 중복되면 validator error. 다른 source 면 OK.

## Step 타입 (단 2종)

| step      | 조건                   | 동작                                                  |
| --------- | ---------------------- | ----------------------------------------------------- |
| LLM step  | `instructions` 키 존재 | composer 가 prompt 합성 → Actor SDK 호출              |
| tool step | `tool` 키 존재         | DRO 가 Actor `POST /tool/{name}` 직접 호출 (LLM 없음) |

구설계 `step.type` / `step.next` / `parallel_task` / `sequential_conditional` / `api_call` / `http_response` / `sub_pipeline` / `service` 모두 폐기 — pipeline_walker 가 fail-loud (RuntimeError) 로 거부.

## dispatch_to syntax

```json
"dispatch_to": {
  "actions": [
    [],                                          // choice=0 → exit
    ["P03.R00.PRIOR_ART_SEARCH_ANALYZE"],        // choice=1 → 1 chain
    ["P02.R10.DIRECTOR_GAP_ANALYSIS", "P02.R11.PATENT_EVALUATION"]  // choice=2 → 2 chains
  ]
}
```

마지막 step 의 `output_contract` 의 `dispatch_choice` (integer enum) 가 인덱스 결정. `dispatch_to: null` 이면 chain 그래프 종료.

## $.path 표현식 (제한적)

- `$.inputs.{user_id,work_id,chain_id}` — orchestrator 가 박는 시스템 메타 (그 외 키 금지)
- `$.steps.<step_id>.<key>` — 같은 chain 내 이전 step 의 output
- `$.parent_outputs.<parent_step_id>.<key>` — dispatch_to 로 spawn 된 chain 에서 부모 chain 의 step output 참조
- `$.user_input.<key>` — `POST /messages` 로 들어온 사용자 payload (content / media / context_hint). user-message entry chain 만 해당.
- `$.<inject_name>.<path>` — tool step 의 `inject_context` 가 `cm://...` 로 사전 fetch 한 데이터 (예: `$.invention_object_model.bibliographic.classification.ipc`)

(구설계 `$.meta.loop_count` / `<item_var>` 등 폐기 — chain self-recursion 으로 대체. `caller_inputs` body 메커니즘도 폐기 — 모든 chain 간 데이터 전달은 cm:// 영속 상태 또는 `parent_outputs` spawn payload 로만.)

## 검증 도구

```bash
make validate                 # 15 stage 전수 (schema · cascading · cross-ref · tool registry · inputs placeholder · cm:// pointer · contracts meta(전수) · IOM · OpenAPI(풀) · WS 3원 · dead-schema · infra · asyncapi · census · 정적 병렬 묶음 형태)
cd tests/validate && uv run python -m validate --pipeline 02.director/P02.R00.CONCEPT_MATURITY
```

규칙:

1. 파일명 P{NN}.R{NN}.UPPER_SNAKE.pipeline.json
2. 4-layer 항목 이름+source 중복 conflict
3. `dispatch_to.actions` 길이 ↔ 마지막 step `output_contract` 의 `dispatch_choice.maximum` 일치
4. `step.output_contract` → `@contracts/<persona>/stages/<id>.schema.json` 파일 존재
5. `llm_tools` 의 각 도구가 self-chain `fetch_*` allowlist 안 (cross-persona 금지)
6. cm:// pointer 표기 (RFC 6901 slash 통일)
7. 구설계 키 발견 시 fail

## 파이프라인 목록 (22 P{NN})

진실 원천 = **`*.pipeline.json` 파일명 + 파일 자체** (pipeline_walker / tests/validate 가 파일 scan). `manifest.pipeline.yaml` 은 사람-읽기용 inventory 스냅샷이며 runtime 에 영향 없음.

- **P01 Buddy**: R00 단일 chain (응대원, 3 step — assess LLM + compose LLM + cm.append_conversation tool). Gemini multimodal SDK 의 reasoning 능력으로 멀티모달 + 의도 분류 + 가드레일 7 카테고리 + IOM 완성도 평가 통합. 자식 chain 없음 (self-contained, dispatch_to: [[]]).
- **P02 Director / P03 Finder / P04 Thinker / P05 Crafter / P06 Inspector**: 각자 chain dispatch graph 보유.
