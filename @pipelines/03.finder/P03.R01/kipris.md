# P03.R01.SEARCH_AND_REFLECT :: kipris

> KIPRIS Plus token AND 검색에 맞게 query 분해 + 3종 (ko_short/en/ipc).

## Instructions

1. KIPRIS 한국어 검색 동작 인지: 공백 split 후 AND 매칭. 1~3 token 만 사용.

2. 각 technical_element 당 3종 query 생성: (a) ko_short — 한국어 1~3 단어 핵심 명사 (b) en — 영문 동의어·기술 용어 (c) ipc — IPC code 그대로.

3. 동의어·축약·표기변형 분리 query 화 (같은 element 에 'RGB LED' / 'RGB 발광 다이오드' / 'multi-color LED' 등 각각).

4. query 개수: 보통 7~15개. priority=1 핵심, 2 보조, 3 배경. target_element 명시.

5. 너무 광범위한 단일 단어 (LED, 센서, 용기) 단독 금지 — 최소 2 단어 또는 IPC 함께.

6. 회귀 (재진입) 처리: previous_queries 가 있으면 그 token 조합 중복 금지. uncovered_elements 에 집중. retry_strategy 우선.

7. plan_notes 한 단락 — KIPRIS token AND 특성을 어떻게 우회했는지 명시.

## Output Contract

`query-plan-output`
