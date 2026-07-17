# P03.R11.EVALUATE_NOVELTY :: synthesize

> 신규성·진보성·배타성 3 축 평가와 청구항 전략·위험·confidence 를 종합. caller 의 최종 의사결정 base.

## Instructions

**1. novelty_assessment (신규성 평가, 특허법 §29(1))**: context.steps.claim_chart.claim_elements 의 similarity 분포와 overall_novelty 등급 기반. element 별 '상이' 비율과 가장 강한 prior_art 매칭의 거리감을 근거로 KIPO 심사에서 신규성 거절 회피 가능성을 한 단락(3~5 문장).

**2. non_obviousness_assessment (진보성 평가, §29(2))**: 신규성과 별개로 prior_art 들의 '단순 조합' 으로 본 발명에 도달할 수 있는지 판단. 단서: (a) 결합 motivation 이 prior_art 에 명시되어 있는가, (b) 결합 결과가 '예측 가능한 효과' 인지 '예측 불가한 시너지' 인지, (c) differentiation_points 가 '주지관용기술의 단순 변경' 으로 치부될 수 있는지. 보수적 판단.

**3. exclusivity_assessment (배타성 / 침해 위험)**: context.steps.fetch_patents.search_results 의 각 patent 청구항 1번과 본 발명의 element 가 모두 포함되는지(literal infringement) 또는 균등론 침해 가능성. 위험 patent 의 출원번호와 침해 시나리오 명시. 위험 없으면 '식별된 직접 침해 위험 없음'.

**4. recommendations (실행 권고 3~7개)**: (a) **청구항 설계** — 어떤 element 를 독립항/종속항에, 어떤 한정어로 좁힐지. (b) **회피 설계** — exclusivity_assessment 의 위험 patent 를 피하는 구체적 구성 변경. (c) **출원 시점** — 즉시 / 추가 실험 후 / PCT 우선권 활용. (d) **부수 출원** — 도면 / 알고리즘 / UI 별도 출원 검토. 각 권고는 한 문장 + 근거.

**5. claim_strategy (청구항 구성 전략)**: 한 단락 — 독립항 N개 + 종속항 M개 구조. 어떤 element 가 broad claim core 이고 어떤 것이 fallback 종속항인지. 한국 출원 관행(독립항 1개 권장 + 종속항 다수) 반영.

**6. risk_factors (출원·심사·시장 위험)**: 2~5개 항목. (a) 거절 위험(어떤 prior_art / 어떤 element), (b) 침해 위험(어떤 타사 patent), (c) 기술 변화로 인한 가치 변동, (d) 청구항 회피 용이성(경쟁사가 회피 설계로 우회 가능한 element).

**7. confidence_score 산출 (0.0~1.0)**: 본 보고서의 신뢰도. 공식: (a) fetch_patents 의 search_results 가 prior_art_numbers 와 일치율 0~1 × 0.4, (b) ranked patents 의 의미적 매칭률 × 0.3, (c) overall_novelty 의 명확도(높음/낮음=0.3, 중간=0.2) × 0.3. 합산 후 0~1 clamp.

**8. total_patents_found**: context.inputs.prior_art_numbers 의 길이 그대로. caller 가 명시한 비교 모수.

**9. 작성 톤**: 추측 자제, 출처 명시(어떤 step 의 어떤 산출에서 결론을 도출했는지 본문에 녹임). 변리사가 의뢰인에게 보내는 자문서 톤. 한국어 표준.

## Output Contract

`synthesis-output`
