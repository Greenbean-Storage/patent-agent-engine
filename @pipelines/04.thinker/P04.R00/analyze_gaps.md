# P04.R00.INVENTION_REASONING :: analyze_gaps

> verification 에서 발견된 gap 을 심층 분석 — 무엇을 더 알아야 메우는지 question 후보 도출.

## Instructions

**1. missing_parameter 식별**: 청구항에 한정어로 들어가야 할 기술적 매개변수가 발명 설명에 누락된 경우. 예: 'NTC 서미스터를 사용한다' 만 명시되고 R0/B 값 미정 → 청구항 한정 불가. 'sigmoid 매핑' 만 명시되고 k 계수·임계값 미정 → 청구항이 너무 broad 해 진보성 거절.

**2. undefined_boundary 식별**: 발명의 작동 영역이 명시 안 된 경우. 예: '저온에서도 동작' — 저온이 -20°C 인지 0°C 인지 미정 → 청구항 경계 불명확. operating_boundaries 의 각 축이 청구항에 반영 가능한지 검토.

**3. hidden_dependency 식별**: 발명이 동작하기 위해 필수이지만 청구항/명세서에 누락된 의존. 예: 'RGB LED 색상 매핑' 이 인간 색채 인지(ΔE) 에 의존하지만 그 가정이 명시 안 됨. implicit_components 와는 다른 층위 — 외부 표준/조건의 가정.

**4. enablement_issue 식별**: 한국 특허법 §42(4) — 통상 기술자가 명세서만으로 실시 가능해야 함. (a) 핵심 알고리즘·구조의 구체 step 누락. (b) 학습 데이터(AI 발명) 미공개. (c) 제조 공정(화학 발명) 일부 비공개. → enablement 거절 위험.

**5. novelty_risk 식별**: 유사 기술에서 자명하게 예측 가능한 요소 — 진보성 부족(obvious) 위험. 예: 'IoT + sensor + display' 같은 단순 결합은 KIPO 심사관이 '주지관용기술의 단순 조합' 으로 거절. point_of_novelty 가 실제로 차별점이 되는지 critical 검토.

**6. structural_gaps 배열 작성**: 각 gap object — (a) **gap_type**: 반드시 5개 enum 중 하나 — 'missing_parameter', 'undefined_boundary', 'hidden_dependency', 'enablement_issue', 'novelty_risk'. 자유 서술 금지. (b) **description**: 한 문장으로 무엇이 누락/위험인지. (c) **patent_impact**: 청구항·심사 영향 한 문장 — '청구항 1 의 한정어 부족으로 진보성 거절 위험'. (d) **priority**: 'critical'(거절 직결) / 'high'(보정 한계) / 'medium'(예방 권장).

**7. novelty_risk_factors 별도 list**: 진보성·신규성 거절 위험 요인 list. structural_gaps 중 novelty_risk 인 것의 description 모음 + 추가 주지관용기술 조합 위험.

**8. enablement_concerns 별도 list**: 실시 가능성 의심 항목 list. structural_gaps 중 enablement_issue 의 description 모음 + 추가 통상 기술자 관점의 미흡 부분.

**9. claim_boundary_issues 별도 list**: 청구항 경계 모호 항목. structural_gaps 중 undefined_boundary 의 description 모음.

**10. prior_gaps 중복 회피**: context.inputs.prior_gaps 가 있으면(이전 라운드에서 이미 식별된 갭) 같은 gap 은 structural_gaps 에 다시 넣지 말 것. 본 단계는 새로운 심층 허점에 집중.

**11. consistency_verification 결과 활용**: context.steps.consistency_verification.contradictions 의 ambiguity 타입은 본 단계의 missing_parameter/undefined_boundary 와 겹칠 수 있음 — 같은 항목 중복 보고 회피, 다른 층위의 새 허점만.

**12. 보수적 식별**: 의심스러우면 priority='medium' 으로라도 포함. 거절 위험은 발명자가 미리 알아야 출원 전 보강 가능.

## Output Contract

`gap-deepening-output`
