# P04.R00.INVENTION_REASONING :: synthesize_questions

> gap 별로 구체적 follow-up 질문을 합성 — director 가 사용자에게 던지거나 자체 추론에 활용.

## Instructions

**1. 모든 미결 사항 통합**: context.steps.consistency_verification.contradictions (severity critical/major) + context.steps.gap_deepening.structural_gaps (priority critical/high) + ambiguous_terms + claim_boundary_issues 를 한 list 로. 중복 항목(같은 부분 가리키는 다른 type) 은 통합.

**2. 우선순위 평가 — 질문 후보 정렬**: 각 미결 사항이 청구항·심사에 직접 영향 미치는 정도 순. (a) critical_contradiction → 발명 성립 자체 위협 → 1순위. (b) structural_gap.novelty_risk + priority=critical → 진보성 거절 직결 → 2순위. (c) missing_parameter → 청구항 한정어 부재 → 3순위. (d) undefined_boundary → 청구항 명확성 → 4순위. (e) ambiguity → 청구항 표현 정량화 → 5순위.

**3. deep_questions 작성 (5~10개)**: 각 question object — (a) **priority**: 1~10 정수, 1이 최우선. (b) **question**: 발명자가 이해할 수 있는 한국어 1문장. 존댓말, 친근. 예: 'sigmoid 매핑의 임계값을 어느 온도(예: 35°C, 50°C) 에 두고 싶으신가요? 임계값에 따라 색상 변화 속도가 달라집니다.' (c) **rationale**: 변리사 관점에서 왜 이 질문이 필요한지 1줄 — '청구항 한정어로 임계값을 명시해야 진보성 확보'. (d) **type**: 4개 enum 중 하나 — 'clarification'(모호함 해소), 'constraint'(작동 경계·범위 명시), 'differentiation'(차별점 명확화), 'mathematical'(수치·수식 정의). (e) **target_gap**: 이 질문이 해소하는 gap 의 description (gap_deepening 또는 consistency_verification 에서).

**4. 개방형 질문 강제**: YES/NO 로 답할 수 있는 질문 금지 — '~ 인가요?' 형태 X. '~에 대해 알려주세요' / '~을 어느 수준으로 설계하시나요?' / '~ 의 우선순위를 어떻게 보시나요?' 같은 개방형. 발명자가 자유 서술하게.

**5. 사용자 친화 톤**: 변리사가 의뢰인 인터뷰하는 어조. 전문 용어는 풀이 첨부 — 'sigmoid 매핑(온도 변화에 따라 색상이 부드럽게 바뀌는 방식)' 같은 괄호 보충. 너무 형식적 금지.

**6. 중요도 내림차순 정렬**: priority 1번부터. 한 라운드에 사용자가 답할 수 있는 질문 수가 제한적이므로 가장 가치 있는 것부터.

**7. reasoning_summary 작성 (한 단락)**: 앞선 4단계의 종합 결론 — '본 발명은 [primary_domain] 분야 발명으로 [핵심 components] 로 구성. [N]개 critical 모순 + [M]개 구조적 허점 식별. 본 단계 [K]개 질문으로 해소 시 청구항 작성 가능 단계 진입.' caller 가 reasoning_trace 로 받아 출원 전략에 사용.

**8. prior_gaps 회피**: context.inputs.prior_gaps 가 있으면 이미 질문된 항목은 다시 묻지 말 것. 새로 식별된 심층 허점에 집중.

**9. ★ type 엄격 적용**: 4개 enum 외 금지. 매핑 헷갈리면 — 모호 표현 해소는 clarification, 수치 범위 정의는 constraint, prior_art 와의 차별은 differentiation, 수식/수치 정의는 mathematical.

**10. 작성 톤 메타지침**: 변리사가 의뢰인에게 보내는 자문서의 '추가 정보 요청' 섹션 톤. 절제·존중·구체적.

## Output Contract

`question-synthesis-output`
