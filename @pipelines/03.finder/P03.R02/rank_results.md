# P03.R02.POST_REFLECT :: rank_results

> fan-out 검색 결과 application_number 단위 dedupe + 의미적 relevance 로 ranking. 상위 30개 압축.

## Instructions

1. 중복 제거 (application_number 기준): 여러 query 에서 등장한 같은 patent 는 unique. N개 query 에서 매칭됐다면 가산점 (+0.1×N, max +0.3).

2. relevance_score 산출 (0.0~1.0) 공식: (a) element 매칭 0.5 + (b) IPC 일치 0.2 + (c) 출원 시점 0.1 + (d) 다중 query 가산 0.2. 의미 동등성으로 판단.

3. relevance_score < 0.3 제외 (노이즈 차단).

4. top-N 제한 (max 30) — 너무 많으면 claim_chart prompt 비대해짐.

5. matched_elements 명시 — 각 ranked patent 에 어떤 technical_element 매칭됐는지 1~3개.

6. exclude_known 처리: caller 가 검토한 출원번호와 일치하는 patent 제외.

7. total_unique_count: 중복 제거 후 총수 (filtering 전).

8. dedupe_notes: 한 단락 — '몇 개 query 결과 합쳐 N건 unique → M건 선별. 주요 제외 사유: ...'

## Output Contract

`dedupe-rank-output`
