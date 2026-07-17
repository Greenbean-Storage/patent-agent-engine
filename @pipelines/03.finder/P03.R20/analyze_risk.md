# P03.R20.ANALYZE_REJECTION_RISK :: analyze_risk

> 입력 청구항·명세서와 KIPRIS 거절결정문 사례를 패턴 매칭하여 전반적 거절 위험 등급·top_risks·avoidance_recommendations 합성. cases 가 비어 있으면 일반론적 분석.

## Instructions

**1. claim_text 분석**: context.inputs.claim_text 의 element 단위 분해 — 주체 / 수단 / 효과 명시. 한 claim 에 여러 element 가 있으면 각각 분리하여 거절 위험 평가.

**2. cases 패턴 매칭**: context.inputs.cases 의 각 case 의 rejection_reason 과 legal_basis 를 분석. 입력 claim 과 어느 element 가 비슷한지 식별 — 부품 / 알고리즘 / 효과 / 명세서 표현. 의미적 유사도 평가.

**3. 법조항 적용 평가 — 5 축**: (a) **§29(1) 신규성** — 입력 element 가 prior_art 와 동일. (b) **§29(2) 진보성** — 단순 조합으로 도달 가능. (c) **§42(3) 명세서 기재요건** — 명세서가 청구항을 충분히 뒷받침하지 못함. (d) **§42(4) 청구항 명확성** — 청구항 표현 모호. (e) **§47 보정 제한** — 출원 후 보정 범위 초과 가능성. cases 의 legal_basis 가 입력에 적용 가능한지 평가.

**4. overall_risk 산출**: (a) **level** — low / medium / high / critical. cases 중 입력과 유사도 0.7+ 인 case 의 법조항 분포로 결정. critical = §29(1) 매칭 강함. high = §29(2) 매칭 강함. medium = §42(3)(4) 매칭. low = 매칭 없음. (b) **score** 0.0~1.0 — 매칭된 case 의 유사도 가중 평균. (c) **summary** 1~3 문장.

**5. top_risks 도출 — 3~7 개**: 각 risk 에 legal_basis(예: '특허법 §29(2)'), pattern(어떤 패턴이 위험인지 1 문장), severity(low/medium/high), evidence_case_indices(matched_cases 중 어느 인덱스가 근거인지 list).

**6. avoidance_recommendations 작성 — 구체 권고**: 각 권고에 target(예: 'claim 1' 또는 'specification.disclosure'), action(어떻게 보정할지 한 줄), addresses_risk_index(top_risks 의 어느 인덱스를 해결하는지). 구체적이고 실행 가능 — '명세서 보강' 같은 추상 권고 금지.

**7. matched_cases 압축 — 5개 이내**: cases 중 입력과 유사도 가장 높은 5개를 application_number / rejection_reason / legal_basis / similarity 4 필드로 보존. caller 가 원문 거절결정문 참조 가능.

**8. confidence_score 산출**: (a) cases 수가 10+ 이고 유사도 0.7+ 가 3+ → 0.85+. (b) cases 부족(5 미만) → 0.5 미만. (c) cases 비어 있음 → 0.3 이하 + matched_cases 빈 list. 사용자가 본 보고서의 신뢰도 인지하도록.

**9. cases 빈 처리**: cases 가 빈 list 면 (a) matched_cases=[], (b) top_risks 는 입력 claim 의 일반적 법조항 위험만 일반론적으로(예: '청구항이 광범위해 §29(1) 신규성 검토 권장'), (c) confidence_score 0.3 이하 + summary 에 '거절 사례 부재로 일반론적 분석' 명시.

**10. 보수적 원칙**: 의심 시 severity 한 단계 높게 + addresses_risk_index 충분히 포함. 사용자가 출원 전 보정 기회를 잃지 않게 — false positive 거절 경고가 false negative 보다 안전.

## Output Contract

`synthesize-risk-output`
