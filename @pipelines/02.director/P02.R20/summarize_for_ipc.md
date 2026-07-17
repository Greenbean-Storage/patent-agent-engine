# P02.R20.CLASSIFY_INVENTION :: summarize_for_ipc

> IOM 을 IPC 분류 적합한 압축 표현으로 요약. shortlist_per_shard 의 입력.

## Instructions

**1. 원본 source 통합**: context.inputs.patent_model 에서 (a) bibliographic.title.ko/en, (b) specification.technical_field, (c) abstract.text, (d) claims[0].text 를 모두 읽음. 비어있는 필드는 skip.

**2. 핵심 기술 요소 추출**: 발명의 (a) **기술 도메인** (예: '음료 용기', '의료 영상 처리', '전기차 배터리 관리'), (b) **수단·기능** (예: 'NTC 서미스터 + RGB LED', '딥러닝 기반 종양 영역 자동 segmentation'), (c) **용도·효과** 의 3축으로 구성. 분류표 매칭에 가장 중요한 것은 '도메인' 과 '수단'.

**3. invention_summary 작성 (1~2 단락, 300~600자)**: 위 3축을 1~2 문단으로 자연스럽게. 형식: '[기술 도메인]에 관한 발명으로, [수단·기능]을 통해 [효과]를 달성한다. 구체적으로 [기술 세부]를 포함하며, [부수 특징]이 가능하다.'

**4. 한·영 keyword 동시 노출**: 핵심 명사구마다 영문 병기 — 예: 'NTC 서미스터(Negative Temperature Coefficient thermistor)' / 'RGB 발광 다이오드(RGB light-emitting diode)' / '음료 용기(beverage container, drinkware)'. IPC/CPC 분류표는 영문이므로 영문 매칭 가능성을 높임. 일반 용어는 영문 병기 생략 가능하지만 핵심 기술 명사는 필수.

**5. 분류 비편향 작성**: 발명을 한 분류 영역으로 미리 단정하지 말 것. 예: SW + 화학 + 기계가 결합된 발명이면 셋 모두를 동등 비중으로 표현 — shard 별로 다른 후보가 나올 수 있게. 한 분야로 편향 작성하면 다른 분야 shard 가 false negative.

**6. 길이 조절**: 너무 짧으면(100자 미만) 분류 매칭 정보 부족, 너무 길면(1000자 초과) shard LLM 의 attention 분산. 300~600자가 적정.

**7. 보수적 작성**: 모호한 표현('혁신적', '독창적') 금지 — 분류 매칭에 무의미. 기술 용어 위주.

## Output Contract

`summarize-invention-output`
