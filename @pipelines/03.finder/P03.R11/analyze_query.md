# P03.R11.EVALUATE_NOVELTY :: analyze_query

> 발명 설명에서 핵심 기술 요소·IPC 분류·검색 쿼리 초안 추출. 후속 fetch_patents 가 prior_art_numbers 직접 로드하므로 query 는 보조용.

## Instructions

**1. 발명 요약**: context.inputs.invention_description 또는 context.context_manager.invention_object_model 을 읽고 한 문장 invention_summary. 형식: '{주체}가 {수단}으로 {효과}를 달성하는 {대상}'. claim_chart / synthesis 가 차별화 포인트 도출의 기준으로 사용.

**2. 기술 요소(technical_elements) 추출**: 발명을 청구항 element 단위로 3~7개로 분해. '기능 + 수단' 한 쌍씩. 예: ['NTC 서미스터로 음료 온도 측정', 'sigmoid 매핑으로 온도-색상 변환']. 후속 claim_chart 의 element 단위 매칭 base.

**3. IPC/CPC 코드 후보(ipc_codes)**: 각 element 의 기술 분야에 해당하는 IPC 그룹. 4~8개. 한국 출원 분야 특이성 파악 단서.

**4. context.inputs.prior_art_numbers 단서 활용**: prior_art_numbers 가 명시되어 있다면 그 특허들의 출원번호 패턴(예: '10-2023-XXX' = 한국 출원)에서 분야 단서 추출. 예: 10-2023-XXX 다수면 한국 분야 — ipc_codes 도 한국 분류에 맞춤.

**5. 검색 전략(search_strategy)**: fetch_patents 가 직접 로드하므로 본 파이프라인에서 search 단계는 없으나, 후속 caller 가 추가 검색을 원할 경우 어떤 분야·언어로 확장하면 좋을지 한 단락.

**6. 초안 검색 쿼리(search_queries) — 분석 보조**: 각 element 당 1~2개씩 1~3 단어. KIPRIS 의 token AND 특성 반영. 본 파이프라인에서 직접 사용은 안 하나 caller 가 추가 검색 시 참고용.

**7. 단일 step 책임 명확**: 본 step 은 분석만 — 신규성 / 진보성 판단은 후속 claim_chart / synthesis 가 담당. 본 step 은 element 정의를 명확히 하여 후속 비교의 일관된 기준을 제공.

**8. 보수적 원칙**: 분야가 모호하면 ipc_codes 에 두 prefix 모두 포함. element 정의가 모호하면 한 element 를 분리 — 후속 매칭 시 element 단위 정밀도가 중요.

## Output Contract

`analyze-output`
