# P03.R02.POST_REFLECT :: match_elements

> 발명 element 와 ranked patent 1:1 매칭 + 동일/유사/상이 판정 + 차별화 포인트.

## Instructions

1. 입력 정리: technical_elements 행, ranked_patents 열. element 별 1개 prior_art_match 선정.

2. element 별 가장 가까운 prior_art_match: matched_elements + title/abstract 의미적 거리. 매칭 없으면 빈 문자열 `""` (null 금지 — schema 가 string 만 허용).

3. similarity 판정: 동일 (그대로 또는 자명한 변형) / 유사 (기본 원리 같으나 특정 구성 다름) / 상이 (기술적 본질 다름).

4. differentiation 도출 (element 단위): similarity ≠ 상이 인 경우, 구체적 차이 한 줄. 추상적 금지.

5. overall_novelty 등급: 높음 (50% 이상 '상이' + '동일' 1개 이하) / 중간 / 낮음 (대부분 동일/유사).

6. differentiation_points 통합: 가장 강력한 차별점 2~5개. 발명 전체 narrative.

7. [INVENTION].claims 있으면 그것을 element 분해 기준으로.

8. 보수적 판단: 의심스러우면 더 가까운 쪽 (동일/유사 사이면 동일). 출원 후 OA 거절 위험 미리 드러내야.

## Output Contract

`claim-chart-output`
