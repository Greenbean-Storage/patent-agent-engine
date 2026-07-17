# P03.R11.EVALUATE_NOVELTY :: match_elements

> 발명의 각 기술 요소와 선행기술 상세를 1:1 매칭하여 동일/유사/상이 판정 + 차별화 포인트 도출. synthesis 의 1차 근거.

## Instructions

**1. 입력 정리**: context.steps.analyze.technical_elements 를 행, context.steps.fetch_patents.search_results 를 열로 보는 매트릭스. 각 element 마다 fetch_patents 의 각 patent 와 의미적 거리 평가하여 가장 가까운 한 patent 를 prior_art_match 로 선정.

**2. similarity 판정 (동일/유사/상이)**: (a) **동일** — element 의 구조·기능·효과가 prior_art 의 청구항/명세서에 그대로 또는 자명한 변형으로 기재. 신규성(특허법 §29(1)) 부정 가능성. (b) **유사** — 기본 원리는 같으나 구성(소재/회로/알고리즘/임계값)이 다름. 진보성(§29(2)) 쟁점. (c) **상이** — element 의 기술적 본질이 다르거나 prior_art 에 명시되지 않음. 신규성 인정 가능성.

**3. prior_art_match 선정 기준**: 단순 relevance_score 가 아니라 이 특정 element 와의 의미적 거리. 매칭할 만한 patent 가 없으면 `prior_art_match=""` (빈 문자열) + similarity='상이'. **null 금지** — schema 가 string 만 허용.

**4. differentiation 도출 (element 단위)**: similarity ≠ '상이' 인 element 마다 본 발명과 prior_art 사이의 구체적 차이를 한 줄로. 예: '본 발명은 sigmoid 비선형 매핑이나 prior_art 는 3-step 임계값 분기'. 추상적('더 정밀하다') 금지, 구체적('정확도 ±0.5°C 한정').

**5. overall_novelty 등급 판정**: claim_elements 각각의 similarity 분포로 종합. (a) **높음** — 핵심 element 의 50% 이상 '상이' + '동일' 1개 이하. (b) **중간** — '상이' 일부 + '동일/유사' 핵심에 분포. (c) **낮음** — 핵심 element 대부분 '동일/유사'. 청구항 재설계 필요.

**6. differentiation_points 통합**: 위 4번의 element 별 차이 중 가장 강력한 차별점 2~5개를 추려 한 list 로. element-level 이 아니라 발명 전체의 차별화 narrative.

**7. context.context_manager.invention_object_model.claims 활용**: IOM 에 이미 청구항 초안이 있으면 그것을 element 분해 기준으로 사용 (technical_elements 와 매핑). 없으면 technical_elements 그대로.

**8. 보수적 판단 원칙**: 의심스러우면 더 가까운 쪽(예: 동일/유사 사이면 동일). 출원 후 OA 거절 위험을 미리 드러내는 게 본 step 의 가치 — 낙관적 판단은 sin.

**9. fetch_patents 결과가 빈 list 일 때**: 모든 element 의 `prior_art_match=""` (빈 문자열), similarity='상이', overall_novelty='높음(prior_art 없음)' 명시. caller 가 prior_art_numbers 를 잘못 입력했거나 KIPRIS 응답 실패 — synthesis 가 confidence_score 낮춤.

## Output Contract

`claim-chart-output`
