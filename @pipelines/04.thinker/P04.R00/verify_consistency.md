# P04.R00.INVENTION_REASONING :: verify_consistency

> decomposition 의 element 간 논리적 정합성 검증 — 모순 / 누락 / 순환 식별.

## Instructions

**1. hard_data 수치 일관성 검증**: context.inputs.hard_data 의 모든 수치 — 단위(°C vs K, mA vs A, Hz vs RPM), 범위(min < max 인지), 물리 한계(절대영도 미만, 광속 초과 등), 차원 일치(P=VI 검증). 불일치 시 contradiction 또는 mathematical_error.

**2. 암묵 전제 검증**: context.steps.logical_decomposition.preconditions + implicit_components 의 각 항목이 현실에서 가능한지. 예: '실온 25°C 에서 동작' OK / '평균 -300°C 에서 동작' 불가능 → physical_impossibility.

**3. 구성요소 간 모순 탐지**: context.steps.logical_decomposition.components 중 동시에 만족 불가능한 제약 — 예: 'c1=초저전력 < 1mA' AND 'c5=고속 LED 응답 > 1ms 펄스 100Hz' 가 함께 명시되면 power budget 검증해 contradiction. operating_boundaries 의 모든 축에서 cross-check.

**4. 물리/열역학 한계 위반 검출**: governing_principles 의 각 법칙으로 발명 동작 가능성 평가. 예: 음료 용기에서 '음료 온도가 5초 만에 80°C 에서 25°C 로 냉각' = 음료 열용량과 환경 열전달 계수 고려 시 physical_impossibility.

**5. 청구항 모호 표현 식별**: 'about', 'approximately', '적절한', '충분한', '신속한' 같은 주관/정성적 표현. ambiguous_terms list 에. KIPO §42(4) 명확성 요건 위반 가능성. 각 ambiguous_term 마다 추후 청구항에서 수치 범위로 정량화 필요.

**6. contradictions 배열 작성**: 각 발견된 모순/오류 — (a) **type**: 반드시 5개 enum 중 하나 — 'contradiction'(논리적 충돌), 'ambiguity'(모호함/주관적 표현), 'invalid_assumption'(잘못된 전제), 'mathematical_error'(수학/단위 오류), 'physical_impossibility'(열역학·물리 한계 위반). 자유 서술 절대 금지. (b) **description**: 한 문장으로 무엇이 문제인지. (c) **location**: 'hard_data.temperature_range' 같은 dot path. (d) **severity**: 'critical'(발명 성립 불가) / 'major'(청구항 거절) / 'minor'(보정 가능). (e) **suggestion**: 해결 방향 한 줄.

**7. verified_claims (검증 통과 주장 list)**: 발명 설명 중 본 검증을 통과한 핵심 주장들 — 후속 단계에서 신뢰할 수 있는 사실. 예: ['NTC 측정 정밀도 ±0.5°C — 통상 NTC 사양 부합', '소비전력 < 100mA — sigmoid 매핑 연산 부담 고려해도 가능'].

**8. mathematical_analysis 객체**: 수치·수식 검증의 정량 결과 dict. 예: {'power_budget': 'OK, NTC+MCU+LED 합산 80mA < 100mA spec', 'heat_dissipation': 'WARNING — 봉인 케이스 내 LED 발열 5℃ 상승, NTC 측정 오차 가능'}.

**9. ★ contradictions[].type 엄격 적용**: 위 6번의 5개 enum 외 어떤 값도 금지. 매핑 헷갈리면 보수적으로 — 모호 표현은 ambiguity, 단위 오류는 mathematical_error.

**10. 보수적 검증 원칙**: 의심스러우면 contradictions 에 추가 — false positive 가 false negative 보다 안전. severity='minor' 라도 명시하면 발명자가 인지.

## Output Contract

`consistency-verification-output`
