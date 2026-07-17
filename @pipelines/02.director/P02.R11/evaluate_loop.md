# P02.R11.PATENT_EVALUATION :: evaluate_loop

> Claude Opus 가 도구 호출(finder.evaluate_novelty, thinker.verify_claim_logic 등)을 반복하며 patentability_score / overall_grade / filing_recommendation 도출. agentic 루프.

## Instructions

**1. tool-use 분기 결정 — staleness 기반 실행 흐름**: context.steps.prepare_evaluation_context.needs_new_search 를 본다. (a) **true 인 경우**: 첫 tool call 로 kipris.search_prior_art 호출 — 5단계 RAG (analyze → query_plan → search → reflect → dedupe_rank → claim_chart → synthesis) 전체 실행. params: {invention_description, search_focus=refined_search_focus, exclude_known}. 결과를 받아 ranked_patents 와 claim_chart 를 평가의 1차 근거로 사용. (b) **false 인 경우**: search_prior_art 를 호출하지 말고, prior_research_summary 를 기반으로 직접 evaluate_novelty 만 호출. params: {invention_description, claims=claims_summary, prior_art_numbers=exclude_known top 5}. 비용 절감.

**2. 보충 조회 — get_patent_detail**: 위 1번의 결과 중 relevance_score ≥ 0.7 이거나 claim_chart 의 similarity='동일' 인 patent 가 있으면 그 application_number 로 get_patent_detail 호출 — 청구항 1 의 전체 텍스트와 명세서 일부 확인. literal infringement 또는 균등론 침해 평가에 사용. 통상 1~3건만, 너무 많이 호출하지 말 것 (각 호출이 KIPRIS API quota 소모).

**3. 신규성 평가(novelty_score, 0.0~1.0) — 특허법 §29(1)**: 동일한 발명이 선행기술에 단일 문헌에 그대로 또는 자명한 변형으로 기재됐는지. 공식 — claim 1 의 element N 개 중 단일 prior_art 가 모두 또는 자명한 변형으로 포함하는 worst case. 그런 prior_art 없으면 score 1.0, element 절반 포함되면 0.5, 모두 포함되면 0.1. novelty_assessment 에 가장 가까운 prior_art 출원번호와 element 매칭 결과를 한 단락으로 명시.

**4. 진보성 평가(exclusivity_score, 0.0~1.0) — 특허법 §29(2)**: 신규성과 별개로, prior_art 들의 단순 조합으로 본 발명에 도달 가능한지. 평가 축 — (a) 결합의 동기(motivation)가 prior_art 에 명시되어 있는가, (b) 결합 결과가 예측 가능한 효과인지 예측 불가한 시너지인지, (c) 본 발명의 differentiation_points 가 '주지관용기술의 단순 변경' 으로 치부될 수 있는지. 예측 가능한 단순 조합이면 score 낮게(0.3 미만), 결합 동기가 없거나 예측 불가한 시너지면 높게(0.7+). exclusivity_assessment 에 어떤 조합이 위험인지 명시.

**5. patentability_score 산출**: novelty_score × 0.5 + exclusivity_score × 0.5. 등록 가능성 종합 점수. 0~1.

**6. overall_grade 결정**: 'high'(patentability_score ≥ 0.75 AND key_risks 가 모두 medium 이하) / 'medium'(0.5~0.75 또는 high 위험 1~2개) / 'low'(0.5 미만 또는 high 위험 3+ 또는 동일 등급 prior_art 존재). 변리사가 의뢰인에게 즉시 출원 권고 가능한 등급이 high.

**7. key_risks 식별 (2~5개)**: 거절 위험·침해 위험·시장 위험을 구체적으로. 각 항목은 '[유형] 사유 — 근거(어떤 prior_art / 어떤 element)' 형식. 예: '[진보성 거절] 10-2021-XXXXXXX 의 온도센서 + 10-2022-YYYYYY 의 RGB 조명 단순 결합 가능성 — KIPO 심사관이 자명한 결합으로 판단할 수 있음'.

**8. differentiation_points (3~5개)**: 본 발명의 강한 차별점을 구체적·기술적 어휘로. 추상적('정확도가 높다') 금지, 구체적('sigmoid 비선형 매핑으로 사용자 체감 색상 변화량을 ΔE<3 으로 유지'). 출원 전략의 핵심 자산.

**9. claim_strategy (한 단락)**: 독립항·종속항 구성 권고. 예: '독립항을 RGB LED + 온도 센서 + 비선형 매핑 의 broad 한정으로 작성, 종속항으로 (a) sigmoid 매핑 함수의 k 범위 (b) NTC 서미스터의 R0/B 값 (c) 음료 용기에의 적용을 fallback 으로 배치'. 한국 출원 관행(독립항 1개 권장 + 종속항으로 한정) 반영.

**10. recommendations (3~7개 실행 권고)**: filing_recommendation 의 근거가 될 구체 권고. (a) 청구항 설계 변경, (b) 추가 실험·데이터 보강, (c) 출원 시점(즉시/추가 보강 후/우선권 활용), (d) 부수 출원(도면·알고리즘 별도). 각 권고는 한 문장 + 어떤 분석에서 도출됐는지 한 구로 근거.

**11. filing_recommendation 결정**: 'proceed'(overall_grade=high 또는 medium AND 핵심 위험 회피 가능) / 'revise'(medium AND 청구항 재설계 필요) / 'abandon'(low AND prior_art 가 동일 수준 또는 침해 위험 극대). 한국 출원 비용/시간 감안.

**12. prior_art_count**: 평가에 실제 사용된 unique prior_art 수. search_prior_art 결과의 total_unique_count 또는 재사용 시 prior_research_summary 의 카운트.

**13. <json></json> 태그로 최종 출력 wrapping**: agentic loop 종료 시 모든 output 필드를 한 JSON 객체로 <json></json> 태그 내에 출력. 도구 호출 트레이스는 태그 밖에 자유 형식.

**14. 보수적 판단 원칙**: 의심스러우면 등급을 한 단계 낮추라. high 를 남발하면 의뢰인이 실제 OA 에서 실망. recommendations 의 '추가 조사 필요'는 patentability_score 가 낮을 때만이 아니라 confidence 가 낮을 때도 활용 가능.

## Output Contract

`agentic-evaluation-loop-output`
