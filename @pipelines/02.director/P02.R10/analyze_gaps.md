# P02.R10.DIRECTOR_GAP_ANALYSIS :: analyze_gaps

> known_facts 와 patent_model 의 필수 필드를 비교하여 명세서 완성도 gap 식별 + 우선순위 + 다음 질문 후보 도출.

## Instructions

**1. 두 가이드 + Section 특이 패턴 숙지**: system_prompt 상단의 (1) drafting_summary 와 (2) rejections_summary 를 우선 적용. user message 의 load_rejections_section.section_guide.text 가 있으면(IPC 분류 정해진 경우) 그 Section 분야 특이 거절 패턴도 함께 적용. text 가 null(분류 미정)이면 일반 가이드만.

**2. patent_model_updates 생성 (PATCH body)**: context.steps.extract_known_facts.known_facts 의 각 entry 를 IOM dot path 에 매핑한 dict. 형식: {'specification.problem': '...', 'specification.solution': {...}, 'claims[1]': {...}}. KIPO 작성 양식 — 명사형 종결('~한다', '~할 수 있다' 금지, '~하는 ~장치' 같은 명사구). 청구항은 '~인 것을 특징으로 하는' / '~를 포함하는' 같은 표준 어미.

**3. changed_sections 명시**: patent_model_updates 의 top-level 키 list — ['bibliographic', 'specification.problem', 'claims']. gateway 가 WS push 시 어떤 section 이 변했는지 client 에 알리는 source.

**4. gaps 구조화 list 생성**: empty_fields + 채웠지만 품질이 부족한 field 를 모두 gap 으로. 각 gap object 의 필드 — (a) **field**: IOM dot path. (b) **description**: 변리사 관점에서 왜 이 정보가 필요한지(거절 위험 명시, 예: 'specification.background 가 비면 §42 기재불비 가능성'). (c) **priority** — 'high'(거절 직결 / Section 특이 패턴에 걸림 / 청구항 필수 한정어 누락) / 'medium'(품질 저하지만 등록 가능) / 'low'(있으면 좋음). (d) **user_friendly_question**: buddy 가 사용자에게 그대로 던질 한국어 질문(존댓말, 1문장). 예: '온도가 어느 범위에서 색이 어떻게 바뀌는지 구체적으로 알려주실 수 있을까요?'. (e) **input_type** — 'chat'(자유서술 — 개방형 질문), 'selection'(1개 선택 — 정해진 후보 중 택1), 'checkbox'(복수 선택), 'keyword'(짧은 단어 입력). (f) **options**: selection/checkbox 일 때만 — 실제 가능한 선택지 list, 보통 3~6개. 그 외 null.

**5. options 생성 원칙**: gap.field 가 'technology' 면 후보 분야 list, 'classification.ipc' 면 IPC 후보 코드 list. 사용자가 막연한 경우의 선택 부담을 줄이기 위해. 단, '뭐든 가능' 같은 도피처는 넣지 말 것 — 사용자가 의미 있는 답을 강제하도록.

**6. completeness_score 산출 공식 (0.0~1.0)**: (a) 필수 필드 채움 비율(0.4): bibliographic.title / specification.problem / solution / effect / claims[1] 5개 중 채워진 비율. (b) 품질 가중치(0.2): 각 채운 필드의 길이와 구체성 — 한 줄 placeholder 면 0, 변리사 수준 명세 가능하면 만점. (c) KIPO 가이드 준수도(0.2): 명사형 종결·표준 어미·청구범위 명확성. (d) 거절 회피 항목 충족도(0.1): rejections_summary 의 항목별 회피 여부. (e) Section 특이 패턴 회피(0.1): section_guide.text 가 있을 때만, 없으면 (a)~(d) 를 1.1 로 정규화. 합산 후 0~1 clamp.

**7. ready_for_research**: completeness ≥ 0.55 AND 핵심 기술 요소(독립항 element 후보)가 최소 3개 정의됐으면 true. 그 미만이면 false — 선행기술 검색을 해도 의미 있는 결과가 안 나옴.

**8. ready_for_evaluation**: completeness ≥ 0.70 AND context.context_manager.context.research 가 존재하면 true. 둘 다 충족돼야 평가 의미가 있음. central_agent 가 다음 라운드에 evaluation 을 trigger 할지 결정하는 1차 신호.

**9. 보수적 판단·작성 톤**: 사용자 발화가 모호하면 채우지 말고 gap 으로 남길 것. 의심스러운 IOM 채움은 후속 OA(거절이유 통지)에서 보정 불가능한 자기모순으로 이어짐. user_friendly_question 은 변리사 어조(존댓말, 친근하지만 전문가).

## Output Contract

`analyze-gaps-output`
