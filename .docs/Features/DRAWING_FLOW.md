# Drawing Generation Flow

특허 도면 생성을 위한 페르소나·chain 흐름 reference.
설계 의도 원본은 `../Architectures/STATIC_BLOCK_ARCHITECTURE.md` (워커 정의), 현행 아키텍처는 `../Architectures/DRC_ARCHITECTURE.md`. 본 문서는 도면 생성에서 각 페르소나가 chain dispatch graph 로 어떻게 협력하는지를 정리한다.

> 도면 작업은 **chain dispatch graph** 로 진행된다 — Director (P02.R12) 가 도면 작업의 review/coordinate step 만 자체 처리하고, 부호 추출 / 청구항 매핑 / DL 생성 / 렌더 / 검수는 모두 **별도 chain spawn** (P04.R10 → P04.R11 → P05.R00 → P05.R10 → P06.R00) 으로 분리되어 진행된다. Actor 끼리 직접 호출하지 않음.

---

## 페르소나 역할 요약

| 페르소나                          | 역할                                              | IOM 권한 |
| ----------------------------- | ------------------------------------------------- | ---- |
| P2 Director (Claude Opus 4.7) | 전체 orchestrate, 단계별 검수, IOM writer | RW   |
| P4 Thinker (GPT o3)           | 부호 추출, 청구항 작성 (chain 2개)                  | RO   |
| P5 Crafter (Claude Opus 4.7)  | DL 생성, 이미지 렌더링 (chain 2개)                  | RO   |
| P6 Inspector (Gemini 3.1 Pro) | 완성 도면 검수 (chain 1개)                          | RO   |
| CM (400.CM)                     | drawings/* 저장소 — S3 단일 writer                | —    |

**IOM R/W 정책**: IOM 모든 도면 데이터(manifest, numerals, dl, figure)의 writer 는 Director (P2). 다른 페르소나는 RO.

---

## 흐름 (chain dispatch graph)

```text
[Nexus] WS `message.send` (사용자 메시지)
  ↓
[P02.R99.CENTRAL_AGENT chain]  (미구현 target, 작성 단계 마일스톤에서 활성화 예정)
  validate_and_plan → dispatch_choice=5 (drawing)
  ↓ chain dispatch
[P02.R12.DRAWING_ORCHESTRATION chain]
  │  step 0,1: generate_drawing_list + review_drawing_list (P02 LLM, self-check)
  │  step 2:   numerals coordinate (P02 LLM) → dispatch to:
  ↓
[P04.R10.EXTRACT_NUMERALS chain] (P04 Thinker, 도면별 self-recursion)
  ↓ chain dispatch
[P04.R11.CLAIMS_WITH_NUMERALS chain] (P04 Thinker, 청구항-부호 매핑)
  ↓ chain dispatch
[P02.R12 self-recursion] (P02 가 review_numerals + review_claims 처리)
  │  step 7-8: DL coordinate (P02 LLM) → dispatch to:
  ↓
[P05.R00.GENERATE_DL chain] (P05 Crafter, 도면별 select_tool + generate_dl_code)
  ↓ chain dispatch
[P05.R10.RENDER_DRAWING chain] (P05 Crafter, tool step: drawing.render)
  ↓ chain dispatch
[P06.R00.REVIEW_DRAWING chain] (P06 Inspector, Gemini Vision)
  │  dispatch_choice: 0=pass / 1=fail (P05.R00 재호출)
  ↓
[P02.R12 self-recursion] (P02 가 merge_renders + aggregate_inspect 처리)
  │  step 14: drawings_summary (P02 LLM) → dispatch_choice: 0=완료 / 1=재시도
  ↓
[P02.R99 재호출 또는 exit]  (R99 활성화 시 적용)
```

각 cross-persona 단계가 **별도 chain** 으로 spawn — DRO 가 spawn 시 즉시 RT 를 persona 큐에 push, 진행 후 끝나면 다음 chain spawn. play (tests/play) 의 spawned chain BFS 가 전체 흐름 추적.

---

## 검수 정책

- **Director self-check step**: P02.R12 의 generate_drawing_list / review_drawing_list 가 Director 자체 작업 — 다음 step 이 체크리스트로 검수.
- **Peer-review chain**: Director 가 cross-persona chain (P04/P05/P06) 의 결과를 자기 chain (P02.R12) 의 다음 review step 에서 검수.
- **Fail 시 회귀**: review step 의 마지막 LLM 의 `dispatch_choice` 가 결정. 회귀 chain 으로 dispatch 후 self-recursion 가드.
  - numerals review fail → `P04.R10.EXTRACT_NUMERALS` 재 dispatch (revision_comment input)
  - claims review fail → `P04.R11.CLAIMS_WITH_NUMERALS` 재 dispatch
  - DL review fail → `P05.R00.GENERATE_DL` 재 dispatch
  - Inspector fail → **DL 단계로 회귀** (P06.R00 의 dispatch_choice=1 이 P05.R00 로 dispatch)
- **Max retries**: 2회. P02.R12 의 `dispatch_to.max_self_recursion` + 각 cross-persona chain 의 자체 guard. 추후 조정 가능.

---

## P04 Thinker chain (2개)

### `P04.R10.EXTRACT_NUMERALS`

- **input**: `parent_outputs` 의 `drawing_meta`, `existing_numerals?`, `revision_comment?` + IOM (inject_context.invention_object_model)
- **동작**: existing_numerals + revision_comment 가 있으면 자동 보완 모드 (재생성 아닌 patch).
- **output**: `{numerals: [{ref, name, description, drawing_role}, ...]}`
- **dispatch_to**: `P04.R11.CLAIMS_WITH_NUMERALS`

### `P04.R11.CLAIMS_WITH_NUMERALS`

- **input**: `all_numerals` (모든 도면의 부호 통합), `patent_model`, `existing_claims?`, `revision_comment?`
- **output**: `{claims: [{number, type, text, refs_used}, ...]}`
- **dispatch_to**: `P02.R12.DRAWING_ORCHESTRATION` (review_numerals_batch + review_claims 로 재진입)

---

## P05 Crafter chain (2개)

### `P05.R00.GENERATE_DL`

- **input**: `drawing_meta`, `numerals`, `patent_model`, `existing_dl?`, `revision_comment?`
- **내부 step**: `select_tool` (LLM) + `generate_dl_code` (LLM)
- **output**: `{dl_code, chosen_tool, file_extension, figure_format}`
- **dispatch_to**: `P05.R10.RENDER_DRAWING`

### `P05.R10.RENDER_DRAWING`

- **input**: `dl_code`, `chosen_tool`
- **동작**: tool step `drawing.render` — 도구별 dispatch (PlantUML CLI / OpenSCAD CLI / SchemDraw / SMILES). LLM 없는 빠른 경로 (DRO direct).
- **output**: `{figure_bytes_b64, mime_type}`
- **dispatch_to**: `P06.R00.REVIEW_DRAWING`

---

## P06 Inspector chain (1개)

### `P06.R00.REVIEW_DRAWING`

- **input**: `figure` (b64 또는 svg text), `drawing_meta`, `numerals`
- **동작**: Gemini Vision (svg 는 텍스트, png 는 inline_data b64).
- **output**: `{drawing_id, review: {overall_pass, ...}, dispatch_choice}`
- **dispatch_to.actions[0]**: `P02.R12.DRAWING_ORCHESTRATION` (통과 → director 재호출)
- **dispatch_to.actions[1]**: `P05.R00.GENERATE_DL` (실패 → DL 재생성)

---

## 도구 매핑 (P05.R00.GENERATE_DL 의 `select_tool` step 지침)

| 도면 종류                   | 권장 도구          |
| --------------------------- | ------------------ |
| 기계 (사시도/단면도/조립도) | OpenSCAD           |
| 기계 (상세 부품)            | CadQuery           |
| 회로                        | SchemDraw          |
| SW / 플로우 / 시퀀스        | PlantUML / Mermaid |
| 화학                        | SMILES             |
| timing / chart              | PlantUML           |

LLM 이 최종 선택. 위는 instructions 에 명시되는 일반 가이드라인.

---

## CM Storage schema

```text
s3://venezia-bucket/sessions/{user_id}/{work_id}/drawings/
  manifest.drawing.yaml             W: director (P2)  RO: all
  {drawing_id}/
    numerals.json                   W: director (P2 가 tool step cm.save_drawing_artifacts 로 PUT)
    dl.{plantuml|scad|py|smiles}    W: director  (text)
    figure.{svg|png}                W: director  (binary)
```

CM endpoint 는 generic `drawings/{drawing_id}/{numerals|dl|figure}` 노출 (text/binary 분기). 도면 저장은 `P02.R13.SAVE_DRAWING_ARTIFACTS` chain 의 tool step `cm.save_drawing_artifacts` 가 담당.

---

## 동적 변경 정책

- **P02.R12 의 step 0/1 에서 도면 리스트 최대한 정확히 결정**. 이후 추가/삭제 동적 루프는 추후 개발.
- **트리거 (미구현)**: P02.R99.CENTRAL_AGENT 의 마지막 step `dispatch_choice=5 (drawing)`. 현재 미활성 — 임시 구체화 단계 (P02.R00.CONCEPT_MATURITY) 가 `dispatch_to: null` 이라 도면 trigger 안 함. 작성 단계 진입 시 R99 활성화와 함께 가동.

---

## 도면 chain graph 의 파이프라인 (7개)

| 파이프라인 (chain)               | 페르소나                         | 파일                                                      |
| ------------------------------- | ------------------------------- | --------------------------------------------------------- |
| `P02.R12.DRAWING_ORCHESTRATION` | director                         | `02.director/P02.R12.DRAWING_ORCHESTRATION.pipeline.json` |
| `P02.R13.SAVE_DRAWING_ARTIFACTS` | director (tool only: cm.save_drawing_artifacts) | `02.director/P02.R13.SAVE_DRAWING_ARTIFACTS.pipeline.json` |
| `P04.R10.EXTRACT_NUMERALS`      | thinker                          | `04.thinker/P04.R10.EXTRACT_NUMERALS.pipeline.json`       |
| `P04.R11.CLAIMS_WITH_NUMERALS`  | thinker                          | `04.thinker/P04.R11.CLAIMS_WITH_NUMERALS.pipeline.json`   |
| `P05.R00.GENERATE_DL`           | crafter                          | `05.crafter/P05.R00.GENERATE_DL.pipeline.json`            |
| `P05.R10.RENDER_DRAWING`        | crafter (tool: drawing.render)   | `05.crafter/P05.R10.RENDER_DRAWING.pipeline.json`         |
| `P06.R00.REVIEW_DRAWING`        | inspector                        | `06.inspector/P06.R00.REVIEW_DRAWING.pipeline.json`       |

`P02.R99.CENTRAL_AGENT` 의 drawing branch (dispatch_choice=5) → `P02.R12.DRAWING_ORCHESTRATION` chain dispatch. 현재 미활성 — 임시 P02.R00.CONCEPT_MATURITY 가 `dispatch_to: null`. 작성 단계 진입 시 R99 활성화와 함께 가동.
