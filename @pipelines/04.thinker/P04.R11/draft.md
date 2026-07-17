# P04.R11.CLAIMS_WITH_NUMERALS :: draft

> 추출된 참조부호와 발명 element 를 결합하여 청구항 초안 작성 — 부호 인용이 일관되게.

## Instructions

**1. 발명 핵심 추출**: context.inputs.patent_model 의 specification.problem/solution/effect + claims 에서 (a) 핵심 기술 요소(독립항 element 후보), (b) 동작 흐름, (c) 차별 포인트(point_of_novelty) 를 추출. all_numerals 의 각 부호 name 과 매핑 가능한지 확인.

**2. 독립항 1~3개 작성**: (a) **장치항** (Apparatus claim) 1개 — 발명을 물건/장치로 청구('~를 포함하고, ~를 더 포함하며, ~인 것을 특징으로 하는 음료 용기'). (b) **방법항** (Method claim) 1개 (해당 시) — 발명을 처리 흐름으로 청구('~ 단계와, ~ 단계를 포함하고, ~ 단계에서 ~ 인 것을 특징으로 하는 온도 표시 방법'). (c) (선택) **시스템항** (System claim) — 분산 발명일 때만. 같은 발명을 장치+방법으로 동시 청구(double protection)는 한국 출원에서 권장.

**3. 부호 인용 형식**: 모든 구성요소 인용에 괄호 부호 — '음료 용기(100)는 NTC 서미스터(110)와, 상기 NTC 서미스터(110)에 연결된 MCU(120)와, 상기 MCU(120)의 제어 신호에 따라 발광하는 RGB LED(130)를 포함하고'. all_numerals 의 ref 를 그대로 사용. 부호 없는 구성요소는 청구항에 사용 안 함.

**4. 종속항 트리 구성 (각 독립항당 3~7개)**: 종속항은 독립항의 한정어 추가. (a) 부품 한정('상기 NTC 서미스터(110)는 R0=10kΩ, B=3950 의 사양인 것을 특징으로 하는'). (b) 기능 한정('상기 MCU(120)는 sigmoid 함수 R(T) = R0 × exp(B/T - B/T0) 을 적용하는'). (c) 실시예 한정('상기 음료 용기(100)는 보온성 단열재로 감싸진 것을 특징으로 하는'). parent_number 필드에 부모 청구항 번호.

**5. 표준 어미 엄수**: (a) 독립 장치항 종결 — '~인 것을 특징으로 하는 [장치명]'. (b) 독립 방법항 종결 — '~를 포함하는 [방법명]' 또는 '~인 것을 특징으로 하는 [방법명]'. (c) 종속항 시작 — '제 N항에 있어서, '. (d) 명사형 종결만, '~한다' 같은 동사 종결 금지. (e) 한 청구항은 한 문장(긴 단일 문장).

**6. claims 배열 작성**: 각 entry — (a) **number**: 1부터 연속 정수. (b) **type**: '독립' | '종속' | '방법'. (c) **parent_number**: 종속항이면 부모 number, 독립이면 null. (d) **text**: 청구항 본문 한 문장. (e) **refs_used**: 본문에 등장한 부호 번호 list(예: ['100', '110', '120', '130']).

**7. 총 청구항 수**: 발명 복잡도에 비례. 단순 발명 5~8개, 보통 8~15개, 복잡 발명 15~25개. 너무 적으면 보호범위 손실, 너무 많으면 KIPO 출원료 증가(11항 이상 가산료).

**8. existing_claims + revision_comment 처리**: context.inputs.existing_claims 가 있으면 그대로 유지(절대 재작성 금지) + revision_comment 의 구체 지시에 따라 (a) 누락된 청구항 추가, (b) 잘못된 부호 인용 수정, (c) parent_number 오류 수정. 검수 회귀 시 통과까지 incremental 보완.

**9. drafting_notes 작성 (한 단락)**: 어떤 발명 요소를 독립항 1로 broad 하게, 어떤 요소를 종속항으로 fallback 으로 배치했는지 — '독립항 1 = 음료 용기 + NTC + MCU + LED 의 broad scope. 종속항 2 = sigmoid 매핑 한정(진보성 보강). 종속항 3 = 단열재 한정(상업 실시예)'. 다음 단계 검수의 단서.

**10. 보수적 작성 원칙**: broad 한 독립항이라도 prior_art 와 단순 결합으로 자명한 한정어만 사용하지 말 것 — 진보성 거절 위험. 구체 차별 한정어는 반드시 독립항에 포함.

## Output Contract

`draft-claims-output`
