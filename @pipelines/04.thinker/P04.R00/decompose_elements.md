# P04.R00.INVENTION_REASONING :: decompose_elements

> 발명을 논리 element 로 분해 — 각 element 의 입력/출력/제약 명시. consistency_verification 의 평가 단위.

## Instructions

**1. components 분해 (5~12개가 적정)**: 발명을 청구항 element 후보가 될 수준으로 분해. 각 component object — (a) **id**: 'c1', 'c2'... 의 짧은 식별자. (b) **name**: 한국어 명사구('NTC 서미스터 측정부'). (c) **role**: 발명에서 이 요소의 기능('음료 온도 측정', '온도-색상 매핑 연산'). (d) **is_novel**: 본 발명의 독창적 구성인지(예: 'sigmoid 비선형 매핑' = true, 'USB-C 충전' = false). (e) **is_essential**: 발명 동작 필수 여부 (true=청구항 1 핵심 / false=종속항 한정). (f) **is_implicit**: 발명자가 명시하지 않았지만 동작에 필요한 암묵 요소 여부.

**2. causal_chain 작성 (한 단락)**: 구성요소 간 인과 화살표 — 'NTC(c1) 가 측정한 R 값을 ADC(c2)가 디지털화 → MCU(c3)가 Steinhart-Hart 식으로 온도 계산 → sigmoid 매핑(c4)으로 RGB 결정 → PWM 드라이버(c5)가 LED(c6) 점등'. 분기/병렬 구조도 표현 가능.

**3. operating_sequence (단계 list, 3~8개)**: 발명의 시간순 동작 단계. 각 단계 한 문장. 예: ['1. 사용자가 음료 부음', '2. NTC 서미스터가 1초 간격으로 저항 측정', '3. MCU 가 온도값 산출 + sigmoid 매핑 수행', '4. PWM 으로 RGB LED 색상 출력']. causal_chain 의 시간 축 표현.

**4. preconditions 나열 (2~6개)**: 발명이 동작하기 위한 필수 전제. 예: ['전원(배터리 또는 USB) 공급', '음료 온도가 NTC 측정 범위(-20~120°C) 내', 'MCU 펌웨어가 매핑 함수 탑재 상태']. 후속 enablement 검증의 source.

**5. operating_boundaries 객체 (수치 범위 명시)**: 발명이 유효한 작동 영역의 수치 경계. 예: {'temperature_range': '0~100°C', 'measurement_interval': '1~10s', 'voltage_range': '3.3~5V', 'color_gamut': 'sRGB'}. 청구항 한정어의 후보. hard_data 가 있으면 우선 반영.

**6. implicit_components 식별 (0~5개)**: components 중 is_implicit=true 인 것의 name list. 발명자가 명시 안 했지만 동작 필수. 예: ['ADC 회로', 'PWM 드라이버', '전류 제한 저항']. enablement 거절 위험 사전 식별.

**7. is_novel vs is_essential 구분 원칙**: is_novel 은 신규성·진보성 평가 단서(prior_art 와 차별되는 요소), is_essential 은 청구항 1 의 broad scope 결정(독립항에 들어가야 할 요소). 둘 다 true 인 것이 청구항의 황금 요소. is_novel=false but is_essential=true 는 종속항으로.

**8. context.inputs.hard_data 활용**: hard_data 가 수치·사양 dict 로 오면 operating_boundaries 와 components 의 role 에 반영. 없으면 기술 설명만으로 정성적 분해.

**9. 보수적 분해 원칙**: 의심스러운 구성요소는 is_implicit=true 로 분류 — 발명자에게 후속 질문 가능. 분해 수준은 청구항 작성 가능한 입자도 — 너무 크면 element 단일화, 너무 작으면 결합.

## Output Contract

`logical-decomposition-output`
