# P02.R12.DRAWING_ORCHESTRATION :: review_figures

> 도면 목록의 누락·중복·청구항 적합성 검토 후 최종 list 확정.

## Instructions

**1. 청구항 커버리지 검사**: context.inputs.patent_model.claims 의 각 독립항 element 가 context.steps.generate_drawing_list.drawings 어딘가의 key_elements 에 포함되는지. 누락된 element 가 있으면 check=fail + comment 에 '청구항 N 의 element X 누락'.

**2. 도면 종류 적합성**: 각 drawing.type 이 context.inputs.tool_params.technical_field 또는 발명 도메인과 부합하는지. 예: SW 발명에 perspective 만 있고 flowchart 없음 → fail. 화학 조성물에 circuit → fail.

**3. 중복·누락 검사**: drawings 의 key_elements 들이 서로 50% 이상 겹치면 중복(불필요한 도면). 반대로 발명의 핵심 동작이 어느 도면에도 안 나오면 누락.

**4. 대표도(is_representative) 정확히 1개**: is_representative=true 가 0개거나 2개 이상이면 fail. 대표도는 발명의 본질을 한 눈에 보여주는 도면 — 보통 시스템 전체도/사시도/architecture diagram.

**5. drawing_id 충돌·key_elements 빈값 검사**: drawing_id 가 중복되거나 'fig1','fig1' 같은 형식이면 fail. key_elements 가 빈 list 이거나 1개뿐이면 fail (도면이 의미를 가지려면 최소 2~3개 요소 표현).

**6. checks 배열 산출**: 위 5개 항목을 각각 {item: '청구항 커버리지', pass: bool, comment: string} 형식으로. 1번이라도 fail 이면 needs_revision=true.

**7. revision_comment 작성 (needs_revision=true 일 때)**: 한 단락으로 다음 generate_drawing_list 가 어떻게 보완해야 하는지 명확히. 예: '청구항 2 의 NTC 서미스터 측정 회로가 어느 도면에도 없음 → fig2 type=circuit 추가, key_elements 에 NTC, MCU, ADC 포함'. 추상적 지시('더 잘 그려라') 금지, 구체적 지시.

**8. 보수적 원칙**: 의심스러우면 fail 쪽으로 — 잘못된 도면 set 으로 후속 6개 step 을 모두 거쳤다가 마지막에 망가지는 비용이 큼.

## Output Contract

`review-drawing-list-output`
