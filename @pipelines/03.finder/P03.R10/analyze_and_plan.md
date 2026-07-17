# P03.R10.ANALYZE_PLAN :: analyze_and_plan

> 발명 설명에서 핵심 기술 요소·IPC 분류·1차 검색 쿼리 초안을 추출하는 분석·계획 step. 단일 step 파이프라인 — search_prior_art 의 Stage 1 만 분리.

## Instructions

**1. 발명 요약**: context.inputs.invention_description 또는 context.context_manager.invention_object_model 을 읽고 한 문장으로 invention_summary 작성. 형식: '{주체}가 {수단}으로 {효과}를 달성하는 {대상}'. 예: '음료 용기가 NTC 서미스터 + RGB LED 조합으로 온도-색상 매핑 표시 기능을 가지는 스마트 텀블러'.

**2. 기술 요소(technical_elements) 추출**: 발명을 청구항 element 단위로 3~7개로 분해. 단순 부품 나열이 아니라 '기능 + 수단' 한 쌍씩. 예: ['NTC 서미스터로 음료 온도 측정', 'MCU 기반 비선형(sigmoid) 온도-색상 매핑', 'RGB LED 발광부', 'USB-C 충전식 리튬이온 전원']. 각 element 는 검색 가능한 명사구로 정제.

**3. IPC/CPC 코드 후보(ipc_codes)**: 각 element 의 기술 분야에 해당하는 IPC 그룹 식별. 분야와 sub-class 까지(예: G01K1/02 — 온도 측정 일반 / H05B47/00 — 조명 제어 / B65D — 용기). 모르면 분야 prefix만이라도(G01K, H05B). 4~8개.

**4. 검색 전략(search_strategy)**: 어떤 element 부터 우선 검색할지, 한국어/영문 중 어느 쪽이 더 결과가 있을지, IPC 직접 검색이 효과적인지 판단을 한 단락으로 기술. context.inputs.search_focus 가 지정됐으면 그 축을 우선.

**5. 초안 검색 쿼리(search_queries) — KIPRIS 직접 투입 가능 수준**: 각 element 당 1~2개씩, 1~3 단어 이내. KIPRIS Plus 의 한국어 token AND 검색 특성 반영 — 4 단어 이상은 결과 급감. priority: 1=핵심 element, 2=보조, 3=배경.

**6. 제외 힌트(exclude_known)**: context.inputs.exclude_known 의 출원번호들은 caller 가 이미 검토한 특허이므로 후처리 제외 대상으로 기억. search_strategy 의 한 줄로 명시.

**7. search_focus 처리**: context.inputs.search_focus 가 있으면 그 기술 요소를 technical_elements 의 1번 위치로, search_queries 의 priority=1 로 정렬. 없으면 발명 의도가 가장 강한 element 를 1번으로.

**8. target_claims 활용**: context.inputs.target_claims 가 지정됐으면 해당 청구항 번호와 연관된 element 를 우선 추출. context.context_manager.invention_object_model.claims 가 있다면 그 청구항 번호 기준 element 식별.

**9. 보수적 원칙**: 한 element 가 두 IPC 분류에 걸치면 둘 다 ipc_codes 에 포함 — 검색이 한 분야에서 0건일 때 caller 가 다른 분야로 시도 가능. 분야 모호하면 더 일반적인 prefix(예: G01) 까지 보존.

## Output Contract

`analyze-output`
