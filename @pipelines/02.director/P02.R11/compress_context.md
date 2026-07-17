# P02.R11.PATENT_EVALUATION :: compress_context

> IOM + research + completeness 를 종합하여 평가용 컨텍스트 압축. agentic_evaluation_loop 의 입력 정제.

## Instructions

**1. 발명 설명 추출**: context.inputs.patent_model 에서 (a) bibliographic.title, (b) specification.problem + solution + effect 를 합쳐 평가용 invention_description 작성 — 3~5문장. KIPRIS search 와 evaluate_novelty 도구가 받는 형식. 추상적·마케팅 어휘 금지, 기술 용어 우선.

**2. claims_summary 작성**: patent_model.claims 의 각 청구항을 1~2 문장으로 압축. 독립항(claim 1)은 element 단위로 분해해서 명시('A 를 포함하고, B 를 더 포함하며, C 인 것을 특징으로 하는 D'). 종속항은 추가 한정어만 명시('claim 1 에서 B 가 sigmoid 매핑'). 청구항이 없으면 specification 의 핵심 element 3~7개를 청구항 후보로 정렬.

**3. staleness 판단 — needs_new_search 결정**: context.inputs.research 와 현재 patent_model 의 diff 를 보고 다음 조건 중 **하나라도** 해당하면 true. (a) research 가 null 또는 비어있음. (b) research 이후 completeness_score 가 0.15 이상 증가(context.context_manager.context.completeness 와 research.completeness_at_search 비교). (c) 핵심 청구항(claim 1)의 element 가 추가/삭제/변경됨. (d) research.patent_model_snapshot 이 있으면 현재 patent_model 과의 dot-path diff 가 specification.problem/solution 또는 claims 에 변경 포함. 모두 false 면 needs_new_search=false (재사용).

**4. search_rationale 명시 (한 단락)**: 위 3번의 판단 근거를 한 단락으로. 예: '직전 research 시 completeness 0.55 였으나 현재 0.78 로 0.23 증가 → 새 검색 필요' / 'claim 1 의 element 변경 없음, research 5일 전 — 재사용으로 비용 절감'. evaluation 결과 신뢰도 보고에 사용.

**5. exclude_known 정리**: context.inputs.research.ranked_patents 의 application_number list. 새 검색 시 prior_art_search 에 전달되어 dedupe_rank 단계에서 제외됨. 재사용 시에도 evaluate_novelty 에 전달 — 이미 본 patent 와 중복 평가 회피.

**6. refined_search_focus 정제**: context.inputs.search_focus 가 caller 에서 왔으면 그대로 사용. 없으면 claims_summary 와 발명의 차별점에서 가장 위험한 element(prior_art 와 가장 비슷할 만한 element) 1개를 한 구로 표현. 예: 'sigmoid 비선형 온도-색상 매핑 알고리즘'. 너무 광범위('IoT 장치') 또는 너무 협소('k=0.3 의 sigmoid 계수') 금지.

**7. prior_research_summary (needs_new_search=false 일 때만)**: research.ranked_patents top 5개 + research.novelty_assessment 를 4~6문장으로 압축. 다음 step 이 evaluate_novelty 호출 시 입력으로 사용. true 면 null.

**8. 작성 톤**: 변리사 자문 어조. 의심스러운 staleness 는 보수적으로 true 쪽으로 — 잘못된 재사용으로 인한 부정확한 평가가 비용보다 큰 손해.

## Output Contract

`prepare-evaluation-context-output`
