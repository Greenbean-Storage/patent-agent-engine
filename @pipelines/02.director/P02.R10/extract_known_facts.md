# P02.R10.DIRECTOR_GAP_ANALYSIS :: extract_known_facts

> 현재까지 알려진 발명 사실을 IOM + conversation 에서 추출. analyze_gaps 의 비교 base.

## Instructions

**1. messages 전체 스캔**: context.inputs.messages 는 contexts/conversation.json — user/assistant turn 의 시계열. 각 user turn 에서 (a) 기술적 사실(구성요소·재료·회로·알고리즘) (b) 수치/수식/임계값(예: '온도 ±0.5°C', 'sigmoid 매핑 k=0.3') (c) 효과/문제 진술 (d) 대체 구성 언급 을 추출. 비정형 발화('대충 이런 거야')는 사실로 카운트 X.

**2. structured_input(체크리스트 응답) 우선 신뢰**: messages 의 turn 중 input_type=selection/checkbox/keyword 의 응답은 user 가 명시 선택한 값 — 자유서술보다 신뢰도 높음. 같은 필드에 자유서술과 structured_input 이 충돌하면 structured_input 우선.

**3. patent_model 의 filled/empty 분리**: context.inputs.patent_model 의 모든 leaf field 를 순회하며 (a) 값이 있고 의미 있는 내용(빈 문자열·placeholder·'TBD' 아님) → filled_fields 에 'bibliographic.title' 같은 dot path 로. (b) 값이 없거나 placeholder → empty_fields. IOM 의 필수 path: bibliographic.{title, classification.ipc/cpc}, specification.{problem, solution, effect, technical_field, background}, claims[], abstract, drawings.figures[].

**4. known_facts 구조화**: 단순 추출이 아니라 '어떤 IOM field 에 매핑될지' 까지 한 dict 로. 예: {'specification.problem': '기존 텀블러는 음료 온도를 시각적으로 알 수 없어 화상 위험', 'specification.solution.components': ['NTC 서미스터', 'MCU', 'RGB LED'], 'claims[1].element': '온도-색상 비선형 매핑'}. 다음 step 이 그대로 PATCH 에 쓸 수 있게.

**5. resolved_gaps 산출**: context.inputs.previous_gap_analysis.gaps 가 있으면, 각 gap.field 를 현재 filled_fields 와 대조. 새로 채워진 gap.field 는 resolved_gaps 에 추가. 예: 이전에 'specification.effect' 가 gap 이었는데 이번 messages 에서 '소비전력 30% 절감' 진술이 나왔으면 resolved.

**6. 추출의 보수성**: 사용자가 '아마도' / '~할 수 있을 듯' 같은 추측 표현으로 말한 사항은 known_facts 에 넣지 말 것. 명시·확정된 사실만. 의심스러우면 empty_fields 쪽으로.

## Output Contract

`extract-known-facts-output`
