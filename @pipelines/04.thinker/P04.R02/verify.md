# P04.R02.VERIFY_CLAIM_LOGIC :: verify

> 청구항의 element 정합성·종속 관계·뒷받침 명세서 일관성·신규성 element 잔존 여부를 종합 검증.

## Instructions

**1. 논리 모순·순환 탐지**: claim_text 의 한정어들이 서로 충돌하지 않는지. 예: '저전력(<10mA) 으로 동작하는' AND '고속 응답(<1ms) 으로 동작하는' — 두 요건이 한 회로에서 동시 가능한지 power budget 검증. 청구항이 자기 자신을 인용(순환)하거나 모순 한정어 결합 시 issue.

**2. 수학·물리 오류 검출**: claim_text + hard_data_json 의 수치를 governing principles 로 검증 — (a) 단위 일관성, (b) 범위(min < max), (c) 물리 법칙 위반(예: 음료가 자연 냉각으로 5초 만에 80→25°C 불가능), (d) 차원 일치. hard_data_json 이 있으면 청구항 한정어의 수치가 그와 일치하는지 cross-check.

**3. 모호·주관 표현 식별**: '약', '대략', '적절한', '충분한', '신속한', '효과적인', '약 0.5초' 같은 정량화 안 된 표현. 한국 특허청은 이런 표현을 §42 명확성 위반으로 거절. 각 모호 표현마다 issue 등록 + suggestion 에 정량 대안 제시('약 0.5초' → '0.4초 이상 0.6초 이하').

**4. claim_scope 평가**: (a) **appropriate** — 발명의 핵심 차별점이 한정어로 충분히 명시되었고 prior_art 차별 가능 한 범위. (b) **too_broad** — 한정어가 부족해 prior_art 의 유사 발명까지 포괄(진보성 거절 위험). (c) **too_narrow** — 너무 구체적 수치 한정으로 회피 설계 용이(상업적 가치 손실). technical_overview 의 발명 본질과 한정어의 균형 검토.

**5. issues 배열 작성**: 각 issue object — (a) **type**: 'logical_contradiction' / 'mathematical_error' / 'physical_impossibility' / 'ambiguity' / 'over_generalization' / 'unenablement' / 'lack_of_support' 등. (b) **description**: 한 문장으로 무엇이 문제인지 + claim_text 의 어느 부분인지 인용. (c) **severity**: 'critical'(발명 성립 불가 / 거절 확정) / 'major'(거절 가능성 high) / 'minor'(보정 권장). (d) **suggestion**: 해결 방향 한 줄 — 구체적 대안 표현 제안.

**6. is_valid 결정**: critical issue 가 1개라도 있으면 false. major 만 있고 critical 없으면 true (개선 권고 동반). minor 만 있으면 true.

**7. improved_claim 제시 (선택)**: claim_scope='too_broad' 또는 issues 중 critical/major 가 있을 때, 개선된 청구항 한 문장을 제시. 한국 표준 어미('~인 것을 특징으로 하는') 적용, 모호 표현을 수치로 정량화, 모순 제거.

**8. 청구항 트리 컨텍스트 인지**: claim_text 가 독립항인지 종속항인지 한정어 구조로 판단. 종속항이면 parent 청구항을 가정해 추가 한정어가 의미 있는지 평가. 독립항이면 stand-alone 으로 검증.

**9. context.context_manager.invention_object_model.specification 활용**: lack_of_support(청구항이 명세서에 의해 뒷받침되지 않음, §42(4)) 검출 — claim_text 의 한정어가 specification 의 어디에도 명시 안 됐으면 issue.

**10. 보수적 판단**: 의심스러우면 issue 추가 — false positive 가 출원 전 보완 기회 제공. severity 는 보수적으로 한 단계 높게(major 의심 시 critical 로).

## Output Contract

`verify-output`
