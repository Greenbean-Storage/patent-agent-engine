# tests/enact — track 5: Actor 단일 RT 수행(enact) 격리 검증

> **시나리오 5/5 정식 게이트 + 단건 수행 모드.** 설계·사용법 = 본 README
> (구 설계 기록 `ENACT-TRACK-PLAN.md` 는 삭제됨 — git history).

- **UUT** = real Actor 1 컨테이너 (`actor:real`, unified :59300)
- **harness** = DRO 역할 대행 — RT 를 실 pipeline 합성으로 CM 에 seed → `POST /dispatch`
  (SSE 소비) / `POST /tool/{name}` 직접 호출 → CM 부수효과(RT done·agent_state envelope·trail) 관측.
- **mock-below** = 기존 `llm:fake`(FixtureSession) + real CM. **새 knob / mock 컨테이너 = 0.**

## 시나리오 5종 (게이트)

| 시나리오 | 표적 | 핵심 불변식 |
|---|---|---|
| dispatch | 정상 1 RT | SSE 순서(started→progress*→result) · RT done + dispatch-result 계약 · structured=response_schema · envelope · trail |
| context | 컨텍스트 ② | 같은 chain step0→step1, envelope items 2→4 + step0 items prefix 보존 |
| tool | POST /tool 계약 | 200 `{status:success,result}` · 404 not_found · 400 bad_params(params 비-dict / 미지 kwarg) · 500 exception |
| concurrency | persona cap 503 | P2(cap 2) RT 3개 gather 동시진입 → 정확히 1개 503 + Retry-After, `/health.slots` inflight |
| errors | SSE error 4경로 | persona 미등재 · RT 부재 · composer 키 결손 · legacy 평문 agent_state — 각 started→error(result 0) + message 패턴 |

## 사용법

```bash
make enact                      # 시나리오 전수 + 집계 (5/5 green = 정식 게이트, exit 0)
make enact concurrency          # 시나리오 단일 (dispatch | context | tool | concurrency | errors)
make enact P01.R00 0            # 단건: 실 pipeline step RT 합성·수행·관측 (step = 순번 문자열)
make enact specs/my.yaml        # 단건: ad-hoc spec 파일 (repo 루트 기준 상대경로 가능)
make enact SPEC=path.yaml       # 〃 (VAR — 상대경로 자동 abspath)
make enact PERSONA=2 PROMPT="…" # 단건: ad-hoc 인라인 (spec 의 persona+prompt 설탕)
make enact ... TIMEOUT=300      # dispatch timeout 초
```

ad-hoc spec 필드 (프롬프트 차터 그대로): `persona`(필수 1~6) · `prompt`(=`instructions.inline`
설탕 — RT.input.prompt 는 Actor 비소비) XOR `instructions{inline|reference}` · `persona_prompt` ·
`inject_context`(`cm://`·`@knowledge/` 만 — composer 계약) · `fragments{name:text}`(**literal
강제 텍스트의 정 경로**) · `llm_tools[]` · `context.inputs{}` · `response_schema` XOR
`output_contract`(id) · `pipeline_id`(default `ADHOC`)·`step_id`(default `"0"`) — llm:fake 에서
더미 id 는 fixture-miss echo 로 수행 관측, 기존 fixture 지정 시 재사용.

## 판정 (A4 — 자동 불변식 + 최소 expected)

SSE 시퀀스(started→progress llm_call_started→result, error 0) · RT done + output =
`@contracts/00.dro/dispatch-result` 계약 · structured = RT.input.response_schema ·
agent_state = vendor 원형 envelope (llm:fake 면 vendor `fixture`) · trail `llm_input_prepared`.
context 시나리오는 추가로 **컨텍스트 ② 실왕복** (items 2→4 + step0 items prefix 보존).

exit: **0 = green · 1 = 검증 FAIL · 2 = 사용법/환경**. 시나리오는
Actor `/health` `llm_mode==FIXTURE` 가드. FAIL 시 네임스페이스(`enact-*` work) 보존 —
`make probe view ...` 로 조사, PASS 시 자동 정리 (probe clean 재사용).

## RT 합성 (A3 — 실 pipeline, 박제 방지)

`venezia_pipeline_runtime.load_pipeline_cascaded` + DRO walker `_convert_single_step` 동형
coercion + `orchestrator._build_rt_input` 동형 미러 (`enact/_harness.py`). drift 가드 =
`reasoning_task` 계약 `assert_valid` + 실 Actor done. (구 `llm_spec` divergence 는 C7/D-2 로
해소 — DRO LLM-agnostic 확립으로 RT.input.llm_spec 을 DRO·enact 양쪽에서 제거.)

## 7 트랙에서의 위치

| # | 트랙 | 성격 |
|---|---|---|
| 1 | validate | JSON 정적 정합 (no-stack) |
| 2 | lint | 코드 정적 분석 (no-stack) |
| 3 | invoke | 스택 없는 로직 라인 99% (no-stack) |
| 4 | probe | 실 CM 블랙박스 |
| **5** | **enact** | **Actor 단일 RT 수행 (이 트랙 — 시나리오 5/5 게이트)** |
| 6 | play | DRO pipeline 실행 + dispatch BFS |
| 7 | endpoint | Nexus REST+WS contract e2e |
