# Agent SDK 설계 (P{NN} chain dispatch graph)

페르소나 정의는 `STATIC_BLOCK_ARCHITECTURE.md`, 도면 협력 흐름은 `../Features/DRAWING_FLOW.md`, 구체화 단계 (P02.R00) 흐름은 `../Features/CONCEPT_MATURITY_FLOW.md`, 종합 아키텍처는 `DRC_ARCHITECTURE.md`. 본 문서는 각 페르소나의 LLM 호출 자리에 **어떤 벤더 Agent SDK 인스턴스가 어떤 단위로 들어가는지** 정리한다.

---

## 한 줄 요약

각 Actor RT (Reasoning Task) 1회 = **벤더 Agent SDK 호출 1회**.
DRO 가 Actor `/dispatch` 를 호출하면 (body 의 `persona` 로 — DRO 가 dispatch 시점에 이미 persona 를 앎, 3a) Actor 가 그 persona 의 SDK 세션을 만들고 (또는 같은 chain 의 이전 RT 의 agent_state 를 복원하고), composer 가 합성한 single-text prompt 를 던져 응답을 받은 뒤 agent_state 를 CM 에 저장한다.

---

## 페르소나 ↔ SDK 매핑

| 페르소나 | 모델 가족 | 사용 SDK |
|---|---|---|
| P2 Director, P5 Crafter | Claude Opus 4.7 | `claude-agent-sdk` |
| P4 Thinker | OpenAI o3 | `openai-agents` |
| P1 Buddy, P3 Finder, P6 Inspector | Gemini 3.1 Pro Preview (Vertex AI, global endpoint) | `google-adk` + `google-genai` |

단일 진실 원천 = `@deployment/engine.config.yaml` 의 `personas` (sdk/model/fallback_model/effort/llm_settings — Actor 코드는 persona-제로, `src/engine_config.py` 범용 로더가 기동 시 read). P1/P3/P6 의 fallback 은 `gemini-3-flash-preview`. P2/P4/P5 는 same-model retry. effort 는 1급 공통 키 — claude→`ClaudeAgentOptions.effort`, openai→`ModelSettings.reasoning`, gemini→`ThinkingConfig.thinking_level` 로 어댑터가 번역.

---

## 컨텍스트 단위 — "1 RT = 1 SDK invocation, 1 chain = 누적 agent_state"

| 단위 | SDK 컨텍스트 처리 |
|---|---|
| RT 1개 | SDK 1회 호출 — composer 가 합성한 single-text prompt 를 던지고 응답 받음 |
| 같은 chain 의 다음 RT (같은 persona) | 이전 RT 의 agent_state (vendor 원형 envelope — 아래 절) 를 native 복원 — multi-turn 으로 진행 |
| 같은 chain 의 다음 RT (다른 persona) | 해당 chain 안에서는 발생하지 않음. cross-persona 는 별도 chain spawn (아래 참조) |
| chain dispatch (다른 chain spawn) | 새 chain → 새 agent_state. 부모 chain 의 컨텍스트는 IOM + context 파일 + `trigger.parent_outputs` (부모 step output dict) 로만 전달 |
| chain 종료 시 | agent_state 가 CM `runtime/{persona}/{chain_id}/agent_state.json` 에 영속화 |

### agent_state 포맷 — vendor 원형 envelope (컨텍스트 ②, A3·D-2)

`{"schema_version": 1, "vendor": "claude"|"gemini"|"openai"|"fixture", "model": <실사용 모델 — fallback 반영>, "items": […vendor 원형…]}` — Actor 가 PUT body 로 보내고 CM 이 `persona`/`updated_at` 스탬프 후 저장 (CM 은 내용 opaque — **본 절이 포맷의 기록처**, 스키마 파일 없음). 평문 role/content 가 아니라 **vendor 원형 블록/아이템 (thinking·tool_use·tool_result·text 포함 풀충실도)** 를 무변형 저장하고 다음 RT 가 native 복원 — 품질 ≈ vendor native. vendor 세션은 계속 RT-ephemeral (세션 ID 영속 없음 — claude 의 session id 는 opaque items 안에만 존재).

| vendor | items 원형 | export | restore (다음 RT) |
|---|---|---|---|
| claude | session transcript entries (JSONL line dict, `sessionId` UUID 포함) | in-memory SessionStore 미러 (`llm/state.py:ClaudeTranscriptStore` — uuid upsert, subpath 분리·제외). export 는 close(final flush) 후 | store 를 entries 로 pre-seed + `ClaudeAgentOptions(resume=<entries 의 sessionId — UUID 검증 fail-loud>, session_store=store)` → SDK 가 load→temp JSONL→subprocess 풀 resume |
| gemini | ADK `Event.model_dump(mode='json', exclude_none=True)` dict | close(delete_session) **전** `get_session().events` dump | 새 ADK 세션 생성 후 `Event.model_validate(d)` + `append_event` 루프 |
| openai | `result.to_input_list()` item dict | `_cumulative` (to_input_list 실패 시 export fail-loud — stale 저장 차단) | `Runner.run(agent, seed + [user msg])`. seed 정규화: 같은 model = reasoning item `id` strip, model 불일치(fallback 잔재) = reasoning item drop (타 모델 reasoning 재주입은 API 400) |
| fixture | 평문 `{role, content}` (llm:fake) | history 누적 | vendor 일치 시 items→history (replay 출력엔 무영향) |

- **vendor 교체 시에만 텍스트 강등** (`llm/state.py:items_to_plain`): 구 vendor items → 평문 turns → 신 vendor 에 native 주입 — openai 는 평문이 그대로 합법 input item, gemini 는 user/model Event 합성, claude 는 유일하게 native assistant-turn 주입 불가 → user prompt 앞 "## 이전 대화 (Continuation)" preamble.
- legacy 평문(`messages` 비어있지 않음) 발견 = fail-loud (`parse_agent_state` RuntimeError → SSE error).
- 캡처 의미론: **성공한 `_invoke` 만** export (export → close 순서) — schema retry / fallback 의 실패 교환은 다음 attempt 가 같은 prior 로 seed 되므로 자연 탈락.
- 알려진 비용: 멀티모달 첨부 chain 은 inline 미디어가 base64 로 envelope 에 박혀 RT 마다 왕복 (기능 무해 — 크기 개선은 후속). openai 서버측 reasoning 상태는 원형 복원의 예외 (A3 명시).

### 의미

한 chain 안에서 같은 persona 의 RT 가 여러 개 있으면 SDK 의 conversation 누적이 자동. 다른 chain 으로 dispatch 되면 새 SDK 세션 — 이게 **Actor 끼리 직접 통신 안하는 DRC 의 결과**: 페르소나 경계가 곧 chain 경계 = SDK 세션 경계.

### 예시 — P02.R00.CONCEPT_MATURITY chain 1회 처리 (P-C/P-D 완료 후)

1. Nexus (message_flow) 가 user message 받으면 DRO 에 POST /control/spawn 으로 P01.R00 + P02.R00.CONCEPT_MATURITY chain 을 요청 (FULL mode).
2. P02.R00 의 8 step 순회:
   - step 0 `extract_to_stack` (Agent) — conversation + 이전 stack → CDS 7 필드 갱신
   - step 1 `staging.save` (DRO tool) — CM PUT models/concept-discovery-stack.json
   - step 2/3/4 `score_clarity / completeness / potential` (Agent) — 7 sub-score
   - step 5 `maturity.compute` (DRO tool) — 가중 합산 + CMM PUT (DRO 미발사 — Nexus 가 chain 완료[persona=2] 시 CM 에서 CMM fetch 로 `model.maturity` WS 생성, #12)
   - step 6 `update_roadmap` (Agent) — conversation + IOM + CMM + CDS + UR → 새 items list
   - step 7 `roadmap.persist` (DRO tool) — top-level array CM PUT (DRO 미발사 — Nexus 가 chain 완료[persona=2] 시 CM 에서 UR fetch 로 `model.roadmap` WS 생성, #12)
3. 각 Agent step 마다: Actor (300.Actor) 가 새 SDK 세션 (`ClaudeSDKClient`) 으로 composer 합성 prompt → 응답 → agent_state PUT.
4. P02.R00 의 `dispatch_to: null` → chain 완주. **다른 chain spawn 안 함** (구체화 단계 self-contained).

**미구현 target (P02.R99.CENTRAL_AGENT)** — 정식 7-way dispatch (gap/classify/rejection/prior_art/reasoning/drawing/evaluation) 는 `P02.R99` 로 보존 (현재 미활성). 작성 단계 마일스톤에서 활성화 예정.

---

## venezia 파이프라인과의 관계 — 누가 팀장인가

venezia 파이프라인 (= `@pipelines/**/*.json` + `tests/validate`) 은 도메인 흐름의 자산이다. **이게 팀장이다.** SDK Agent 는 그 팀장이 부르는 sub-actor 일 뿐이다.

이 합의의 결과:

- **step 타입 2종**: `instructions` 키 (LLM step — composer + SDK 호출) 또는 `tool` 키 (DRO direct `POST /tool/{name}`, LLM 없는 빠른 경로) 만. `llm_task` / `agentic_llm_loop` 같은 legacy stage type 은 허용 안 됨 — 발견 시 fail-loud (`_assert_no_legacy_keys` RuntimeError).
- composer (`300.Actor/src/composer.py`) 가 RT.input 의 `persona_prompt` + `inject_context_spec` (cm:// resolve) + `recommended_context_spec` + `fragments` + `instructions` + `dispatch_choice_guide` 를 single-text prompt 로 합성. SDK 에는 raw text 하나만 전달.
- system_prompt 는 빈 문자열 (composer 가 합성).
- `output_contract` 가 step 마다 명시 → composer 가 SDK 의 structured-output 옵션 (response_schema) 으로 전달. 마지막 step 의 contract 에 `dispatch_choice` (integer enum) 가 있으면 그 값이 다음 chain 결정.

즉 venezia 파이프라인 JSON 의 의도는 그대로 살아 있고, **모델 호출 자리만 진짜 Agent 인스턴스로 바뀌었다. 단 stage 타입과 분기 메커니즘이 모두 단순화되었다.**

---

## SDK 가 자체 처리 vs venezia 가 처리

SDK 가 자체 처리:
- 모델 API 호출과 응답 파싱
- structured output (response_schema) 강제
- SDK 내부의 self-chain `fetch_*` tool 호출 (function calling) — `fetch_dialog` / `fetch_step_output` / `fetch_drawing` / `list_drawings` / `fetch_outputs` / `fetch_conversation` 6종 allowlist 만. cross-persona 도구 금지 (`_assert_no_cross_persona_tools` 가 fail-loud).
- transient 에러 retry (Actor `with_backoff`)
- conversation 누적 (한 chain 안에서 agent_state vendor 원형 복원 — 컨텍스트 ②)

venezia (DRO + CM + pipeline JSON) 가 처리:
- chain dispatch graph (마지막 step `output_contract` 의 `dispatch_choice` → `dispatch_to.actions[choice]` 의 next chain spawn)
- chain self-recursion (`max_self_recursion` 가드)
- step list nesting (정적 병렬, asyncio.gather)
- 4-layer cascading (GLOBAL.json → P{NN}.COMMON.json → pipeline.common → step) 합성
- step 간 데이터 매핑 (`$.steps.<id>.<field>` placeholder, dot-notation only — bracket indexing 미지원)
- tool step (DRO direct `POST /tool/{name}`, LLM 없는 빠른 경로)
- IOM 단일 writer 정책 (P2 만 IOM patch — composer 가 합성 후 SDK 가 응답)

---

## 외부화 정책

페르소나 운영에서 환경마다 달라지는 값 (API 키, AWS Secret 이름, region) 은 AWS Secrets Manager 가 단일 source — `shared/venezia_secrets/__init__.py:_load()` 가 `AWS_SECRET_NAME` (comma-separated) 의 secret 들을 모듈 import 시 자동 fetch + env 주입. silent fallback 없음 — secret 없으면 raise.

도메인 정책 (persona_prompt, fragments, llm_tools, output_contract 등) 은 이미 P{NN} pipeline JSON + persona.COMMON.json + GLOBAL.json 에 적혀 있고, 그것이 외부화의 기본 단위이다. 새 형식이 필요하지 않다.

---

## chain dispatch 와 SDK 세션의 경계

같은 persona 의 두 chain 끼리는 **agent_state 가 공유되지 않음** — 각 chain 이 자기 `runtime/{persona}/{chain_id}/agent_state.json` 을 가짐. 즉 chain A 의 reasoning 이 chain B 에 흘러들지 않는다.

cross-persona 호출은 항상 chain dispatch — 별도 chain spawn, 별도 agent_state. 부모 chain 의 컨텍스트는 다음 chain 의 `trigger.parent_outputs` (부모 step output dict — placeholder `$.parent_outputs.<step_id>.<key>` 로 참조) 와 CM 에 영속화된 IOM / contexts 로만 전달된다. (caller_inputs body 메커니즘 없음 — 외부에서 chain 내부 placeholder 에 임의 데이터를 박는 통로 없음.)

list nesting (정적 병렬) 안의 N 개 LLM step 은 같은 chain 안이라 같은 persona 의 agent_state 를 동시에 만지지만, asyncio.gather 로 동시 실행되므로 SDK 마다 race condition 가능성 — 현재는 list nesting 안의 각 step 이 작은 단위 작업이라 conflict 발생 가능성 낮음. 필요 시 격리 옵션 추가 (별도 작업).

---

## 결과 — 우리가 얻은 것

- 각 페르소나가 진짜 Agent 인스턴스로 보인다. 단순 모델 호출 wrapper 가 아니다.
- 벤더 SDK 가 검증한 structured output, tool-use, retry, conversation 관리 등의 자산을 그대로 쓴다.
- chain dispatch graph + composer 로 venezia 파이프라인의 흐름 정의가 매우 단순화 — step 타입 2종 + dispatch_choice 만으로 분기와 루프 모두 표현. validator 가 모든 잔재 fail-loud.
- 한 chain 안에서 같은 persona 의 RT 가 누적 agent_state 로 multi-turn — stage 가 끊어져도 SDK 컨텍스트는 이어진다.

## 결과 — 우리가 안 한 것

- venezia 파이프라인의 분기를 SDK 의 sub_agents/handoffs 로 흡수하지 않았다. chain dispatch graph + 4-layer cascading 이 도메인 정책의 단일 표현 방식.
- 새 외부 config 파일 형식 (yaml, toml 등) 을 도입하지 않았다. AWS Secrets Manager + P{NN} pipeline JSON / persona.COMMON.json / GLOBAL.json 으로 충분하다.
- raw 모델 SDK 의존성 (anthropic / openai / google-genai) 은 Actor pyproject 에 명시 유지. tool step 의 일부 (예: `drawing.render` 의 vision 호출, `document.parse` 의 vision 호출) 가 직접 호출하기 때문. Agent SDK 가 아닌 자리는 raw SDK 그대로 둔다.
- cross-persona 직접 호출 (Actor 끼리 통신) 은 일관되게 금지 — SDK 의 function calling allowlist 도 self-chain `fetch_*` 만. 외부 chain graph 로 모든 cross-persona 협력 표현.
