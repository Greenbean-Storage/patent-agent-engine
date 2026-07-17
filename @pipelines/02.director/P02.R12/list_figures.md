# P02.R12.DRAWING_ORCHESTRATION :: list_figures

> IOM 의 부품·구조·기능 정보를 토대로 필요한 도면 목록(Figure 번호·역할·범위) 생성. 후속 fanout 의 단위.

## Instructions

**1. 발명 도메인 식별**: context.inputs.patent_model.specification.technical_field + context.inputs.tool_params.technical_field 를 보고 발명의 1차 도메인 분류 — 'mechanical'(기계/구조), 'electronic_circuit'(회로/PCB), 'software'(SW/알고리즘), 'chemical'(화학/조성물), 'system'(시스템 아키텍처), 'process'(공정/방법). 이게 type 과 format_hint 선택의 기준.

**2. 필수 도면 식별 — 청구항 커버리지 보장**: context.inputs.patent_model.claims 의 각 독립항 element 가 최소 1개 도면에 표현되어야 함. 청구항 본문에 부호가 인용된다면 그 부호는 어딘가에 그려져 있어야 KIPO 기재요건 충족. 청구항이 비어있으면 specification.solution.components 의 핵심 요소 기준.

**3. drawings 배열 생성 (최소 1, 최대 8)**: 통상 3~5개가 적정. 각 도면 object — (a) **drawing_id**: 'fig1', 'fig2'... 의 lowercase fig+숫자. (b) **type**: 'circuit'(회로도) / 'flowchart'(공정/알고리즘 흐름) / 'sequence'(시계열 동작) / 'perspective'(사시도, 3D 입체) / 'section'(단면도) / 'assembly'(분해/조립도) / 'chemical'(화학구조식/조성도) 중 1. (c) **title**: 한국 출원 표준 표기. 예: '도 1 - 본 발명의 일 실시예에 따른 스마트 텀블러의 사시도'. (d) **key_elements**: 도면에 표현될 구성요소 list (3~10개). (e) **is_representative**: 발명의 대표도 1개만 true, 나머지 false. 보통 fig1 또는 가장 포괄적인 시스템도가 대표도.

**4. format_hint 선택 가이드**: type 과 도메인의 조합에 따라. (a) circuit → 'schemdraw' (Python 회로도). (b) flowchart/sequence → 'plantuml' (또는 'mermaid'). (c) perspective/section → 'openscad' 또는 'cadquery' (3D 모델). (d) chemical → 'smiles' (화학구조식 표기). (e) assembly → 'openscad'. Crafter 가 최종 결정하지만 도메인 부합도 높은 힌트 제공.

**5. action_params.figures_needed 우선 처리**: context.inputs.action_params.figures_needed 가 list 로 와있으면(예: ['circuit', 'flowchart']) 그 종류를 우선 drawings 에 포함. caller(central_agent)가 명시 요청한 도면 type 은 반드시 반영.

**6. review_revision_comment 회귀 처리**: context.steps.review_drawing_list.revision_comment 가 있으면(자가 검수 fail 회귀) 그 지시를 우선 적용. 예: '대표도를 perspective 가 아닌 system architecture 로 변경', '청구항 3 의 element 가 누락됨 — 추가 도면 필요'. 회귀 시 drawings 가 완전히 새로 생성되지 않고 지시받은 부분만 보완.

**7. generation_notes 작성 (한 단락)**: 어떤 기준으로 N 개 도면을 선택했는지 — '청구항 1 의 4개 element 중 hardware 부분은 fig1 사시도, 회로 부분은 fig2 schemdraw, 알고리즘 부분은 fig3 plantuml 로 커버'. 다음 step(검수)이 도면 set 의 적정성을 평가하는 단서.

**8. 보수적 원칙**: 의심스러우면 도면 적게. 같은 정보를 표현하는 도면 두 개보다 다른 측면을 표현하는 한 도면이 낫다. 대표도는 발명의 핵심을 한 눈에 보여주는 도면 — 너무 추상적이거나 너무 세부적이면 안 됨.

## Output Contract

`generate-drawing-list-output`
