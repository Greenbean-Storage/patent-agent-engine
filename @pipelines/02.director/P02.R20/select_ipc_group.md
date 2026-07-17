# P02.R20.CLASSIFY_INVENTION :: select_ipc_group

> subclass 정의와 발명 요약을 비교하여 최적 IPC group 1~3개 결정.

## Instructions

**1. 정적 자산 트리 분석**: context.steps.load_subclasses.ipc 는 후보 IPC Subclass 별 Group/Subgroup 트리 — {Subclass code, title, groups: [{code, title, subgroups: [...]}]} 형식. context.steps.load_subclasses.cpc 도 동일 형식. 각 노드의 title 을 발명 요약과 의미적으로 매칭.

**2. Subclass 내부 정밀 매칭**: 각 Subclass 산하의 모든 Group/Subgroup title 을 invention_summary 와 의미적 일치도 평가. 정확히 부합하는 1~3개 Subgroup 선별 — 너무 일반적인 Group(예: 'A47G 1/00 General') 은 피하고, 발명의 핵심 한정어와 매칭되는 구체 Subgroup 선호.

**3. 최종 IPC 코드 1~3개 (필수)**: 한국 출원은 IPC 분류 필수. 1개가 핵심 분야, 2~3개가 보조. 너무 많이 부여하면(>3) KIPO 심사관이 분류 정확도 의심. 형식 'A47G 19/22' — Subclass(A47G) + 공백 + Group/Subgroup(19/22). 4글자 Subclass 뒤 공백 1개, 그 다음 Group(숫자) / Subgroup(숫자).

**4. 최종 CPC 코드 1~3개 (선택)**: CPC 는 EPO·USPTO 가 사용하는 확장 분류. 한국 출원에는 직접 필요하지 않지만 PCT 출원·해외 출원 시 유용. 적절한 후보 없으면 빈 배열 — 강제 매칭 금지. 형식 'A47G 19/2277' — Subgroup 이 IPC 보다 더 세분화(4~6자리 숫자).

**5. rationale 작성**: 한 단락(2~5문장) — 어떤 발명 요소가 어떤 코드와 어떻게 매칭됐는지. 예: 'A47G 19/22 (음료 용기 — drinking vessels with means for indicating temperature) 는 본 발명의 음료 용기 + 온도 표시 핵심 요소와 직접 부합. H05B 47/00 (조명 제어) 는 RGB LED 의 색상 가변 측면을 커버.'

**6. 표기 표준 엄수**: IPC: 'A47G 19/22' (Subclass + 공백 + Group/Subgroup). CPC: 'A47G 19/2277' (Subgroup 자리 더 길게). 슬래시·공백·대소문자 위치 반드시 표준. 사용자가 후속 단계에서 KIPRIS 에 직접 쿼리할 때 표기 오류로 0건 검색되는 사고 방지.

**7. 보수적 분류**: 정확하지 않으면 부여하지 말 것. IPC 코드 1개라도 정확하면 충분 — 잘못된 3개보다 정확한 1개가 가치 있음. 의심스러우면 상위 Group 으로(Subgroup 까지 안 가고).

## Output Contract

`pinpoint-group-output`
