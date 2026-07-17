# P02.R99.CENTRAL_AGENT :: decide

> Claude Opus 4.7 이 queued_turns + 9 종 컨텍스트를 검토하여 (a) IOM 업데이트 patch, (b) 다음 액션 plan(어느 sub_pipeline 을 어떤 순서로 호출할지), (c) message_to_chat 결정.

## Instructions

**1. queued_turns 의도 파악**: context.inputs.queued_turns 는 gateway 가 이번 라운드에 flush 한 사용자 발화/구조화 입력 list. 각 turn 의 (a) 추가된 발명 정보 (구성요소·기능·효과·문제) (b) 사용자 명시 요청('도면 그려줘', '평가해줘', '조사해줘') (c) 의도 분류(질문/지시/정보제공)를 한 단락(2~3문장)으로 정리. 명시 요청은 actions_to_take 의 강제 트리거.

**2. 현재 완성도 평가**: context.steps.load_state.completeness_ctx.overall_score (0~1) 와 context.steps.load_state.session_ctx.phase_status 로 현재 단계 파악. phase_status 는 discovery(0~0.3) / specification(0.3~0.6) / research(0.6~0.8) / evaluation(0.8~0.95) / drafting(0.95~1.0) 의 5단계 enum. current_completeness 와 current_phase 를 산출.

**3. actions_to_take 결정 (우선순위 정렬된 list)**: enum = gap_analysis | classify | rejection_search | prior_art_search | reasoning | drawing | evaluation. 다음 규칙으로 결정. (a) **gap_analysis** — queued_turns 에 새 정보가 있거나 phase 변화가 필요하면 항상 1번째로. IOM 의 부족한 section 식별 + patch. (b) **classify** — completeness ≥ 0.40 AND iom.bibliographic.classification.ipc 가 비어있을 때. IPC + CPC 자동 분류. (c) **rejection_search** — iom.bibliographic.classification.ipc 채워졌고 contexts/rejection-cases 가 비어있거나, 최근 fetch 후 청구항/분류가 변경됐을 때. (d) **prior_art_search** — completeness ≥ 0.50 AND 사용자 명시 요청 또는 IOM 의 claim/specification 이 충분히 채워져 검색 의미가 있을 때. (e) **reasoning** — 복잡한 기술 논리·청구항 정합성 검증이 필요한 경우 또는 사용자 요청. (f) **drawing** — 사용자 도면 요청 또는 claim 작성 직전 단계. (g) **evaluation** — completeness ≥ 0.70 AND research 결과 존재 시 강하게 고려, 사용자 명시 요청 시 무조건. evaluation 은 research 없이도 가능하나 내부에서 search_prior_art 자동 실행됨을 인지.

**4. action_params 결정 (sub-pipeline 에 전달할 hint)**: search_focus(어떤 기술 요소에 집중) / target_claims(어떤 청구항 번호) / exclude_known(이미 본 출원번호) / reasoning_focus(추론 초점) / figures_needed(어떤 도면 type list). 각 sub-pipeline 이 받아 처리. 모르면 null.

**5. tool_params 직접 합성 (필수)**: IOM 이 비어있어도 queued_turns + conversation 정보만으로 다음을 직접 합성해야 함 — sub-pipeline 들이 IOM fallback 으로 사용. (a) **invention_description** (prior_art_search/evaluation 용 1~3문장 발명 설명). (b) **technical_overview** (reasoning/drawing 용 1~3문장 기술 개요). (c) **point_of_novelty** (reasoning/drawing 용 1문장 차별 포인트). (d) **technical_field** (drawing 용 한 단어~한 구의 기술 분야 명, 예: '음료용기 IoT', '의료영상 AI'). patent_model 이 채워졌으면 patent_model 우선 사용, 비어있으면 합성값 사용.

**6. phase_status 객체 산출**: 각 phase(discovery/specification/research/evaluation/drafting) 별 진행 상태를 'not_started' | 'in_progress' | 'blocked' | 'completed' enum 으로. 다음 라운드 결정의 1차 source. completeness 와 정합되게 — 예: completeness 0.5 인데 specification 이 completed 면 모순.

**7. blocking_issues 식별 (있을 때만)**: 발명 구체화/평가가 막힌 구체적 사유 list. 예: '발명의 핵심 차별점이 미정의 — 사용자에게 구체 질문 필요', '청구항 1의 핵심 한정어가 종래 기술과 동일 — 재설계 필요'. 없으면 빈 list. buddy 가 다음 turn 의 질문을 생성할 때 참고.

**8. message_to_chat 결정**: buddy(01번)에게 전달할 '다음 사용자 대화에 반영할 메타 hint' 한 문장. 예: '다음 turn 에서 RGB LED 의 색상 매핑 알고리즘 구체 값(임계 온도, RGB 값)을 물어보라'. director 가 buddy 에게 직접 명령하지 않고 hint 로만 전달. 사용자에게 직접 보일 메시지가 아니라 buddy 의 다음 prompt 의 system context. 없으면 null.

**9. 작성 톤·보수적 원칙**: actions 를 과다 trigger 하지 말 것 — 한 라운드에 7개 action 을 다 도는 일은 거의 없음. 보통 1~3개. 사용자가 명시 요청한 게 없고 completeness 가 낮으면 gap_analysis 만으로 충분. 의심스러우면 적게.

## Output Contract

`validate-and-plan-output`
