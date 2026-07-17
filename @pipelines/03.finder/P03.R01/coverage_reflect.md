# P03.R01.SEARCH_AND_REFLECT :: coverage_reflect

> 검색 결과 커버리지 평가 + dispatch_choice 결정 (0=재시도, 1=진행).

## Instructions

1. 커버리지 평가 — element 단위: 각 technical_element 가 검색 결과 어딘가에 등장했는지. covered_elements / uncovered_elements 로 분리.

2. coverage_score 산출 (0.0~1.0): covered / 전체. 일반적으로 0.7 이상이면 충분.

3. 0건 query 진단: token 너무 많음 / 희귀 표기 / 분야 미스매치 등 원인 추정.

4. dispatch_choice 결정: coverage_score < 0.7 AND 0건 element 1개 이상 있으면 0 (재시도). 단 self-recursion 3 이상이면 강제 1 (진행).

5. retry_strategy 명시 (dispatch_choice=0 일 때): 한 문장으로 다음 cycle 의 query_plan 전략.

6. additional_queries 생성 (dispatch_choice=0 일 때만): uncovered_elements 직접 시도 query 2~3개.

7. previous_queries 누적: 이번 cycle 의 queries + 기존 previous_queries unique merge.

8. unique_patents_count 추정: search 결과의 application_number unique 어림 (±10% 충분).

9. 의미적 일치(semantic relevance)로 판단. 100건 있어도 무관 분야면 사실상 0건.

## Output Contract

`reflect-output`
