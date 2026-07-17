# P03.R02.POST_REFLECT :: synthesize

> 신규성·진보성·배타성 3축 평가 + 청구항 전략 + 위험 + confidence 종합. 최종 보고.

## Instructions

1. novelty_assessment: claim_elements 의 similarity 분포 + overall_novelty 기반. element 별 '상이' 비율 명시. 한 단락.

2. non_obviousness_assessment (§29(2)): prior_art 단순 조합으로 본 발명 도달 가능성. 결합 동기, 예측 가능 효과, 주지관용 변경 여부 판단. 보수적.

3. exclusivity_assessment: ranked_patents 상위 (0.7+) 들과 침해 위험. 위험 patent 출원번호 + 침해 시나리오.

4. recommendations 3~7개: (a) 청구항 설계 (b) 회피 설계 (c) 출원 시점 (d) 부수 출원. 각 권고 + 근거 step 명시.

5. claim_strategy 한 단락: 독립항 N + 종속항 M 구조 제안. 한국 출원 관행 반영.

6. risk_factors 2~5개: 거절·침해·기술 변화·청구항 회피 용이성.

7. confidence_score (0.0~1.0): (a) coverage_score×0.4 (b) ranked_patents 수 (10+ 면 0.3) (c) overall_novelty 명확도 (높음/낮음 0.3, 중간 0.2). 합산.

8. total_patents_found: dedupe_rank.total_unique_count 그대로.

9. 톤: 변리사가 의뢰인에게 보내는 자문서. 출처 명시 (어느 step 산출에서 도출).

## Output Contract

`synthesis-output`
