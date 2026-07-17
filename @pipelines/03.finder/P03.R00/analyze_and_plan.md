# P03.R00.PRIOR_ART_SEARCH_ANALYZE :: analyze_and_plan

> 발명 설명에서 청구항 element 후보·IPC 분류·1차 검색 쿼리 초안 추출. 후속 query_plan/search 의 모든 입력 결정.

## Instructions

1. 발명 요약: invention_summary 한 문장 — '<주체>가 <수단>으로 <효과>를 달성하는 <대상>' 형식.

2. 기술 요소 (technical_elements): 청구항 element 단위로 3~7개, 각 element 는 '기능 + 수단' 명사구.

3. IPC/CPC 후보 (ipc_codes): 각 element 의 기술 분야 4~8개, sub-class 까지 (예: G01K1/02).

4. 검색 전략 (search_strategy): 한 단락 — 어떤 element 부터 우선, 한국어/영문, IPC 직접 검색 효과 등.

5. 초안 검색 쿼리 (search_queries): element 당 1~2개, 너무 길지 않게 (2-4 단어). priority 1~3.

6. exclude_known: search_strategy 의 한 줄로 명시.

7. search_focus 가 있으면 technical_elements 의 1번 위치 + priority 1 으로 정렬. 없으면 발명 의도가 가장 강한 element 를 1번으로.

## Output Contract

`analyze-output`
