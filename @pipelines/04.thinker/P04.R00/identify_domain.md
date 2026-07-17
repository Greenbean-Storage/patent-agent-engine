# P04.R00.INVENTION_REASONING :: identify_domain

> 발명이 속하는 기술 도메인 식별 — 후속 step 들이 도메인 특화 추론을 수행할 단서.

## Instructions

**1. primary_domain 식별 (단수)**: context.inputs.technical_overview + context.inputs.point_of_novelty 를 보고 발명의 1차 도메인을 1개로 — '전기전자/IoT 센서', '의료영상 처리(SW)', '기계공학/유체역학', '바이오테크/단백질 공학' 등. 모호한 표현('IT 융합') 금지, 구체적 표현. reasoning_focus 가 있으면 그 요소가 속한 도메인 우선.

**2. sub_domains 식별 (0~3개)**: 발명이 여러 분야를 걸치는 경우. 예: 스마트 텀블러 = primary 'IoT 센서·임베디드', sub: '음료 용기 설계', '색채 표현(인간시각 ΔE)'. 단일 도메인이면 빈 배열.

**3. governing_principles 나열 (3~7개)**: 발명이 따르는 핵심 물리/수학 원리. 예: ['옴의 법칙(저항-전압-전류)', 'NTC 서미스터의 Steinhart-Hart 방정식', 'RGB 색공간의 sRGB ↔ HSV 변환', '열전도-측정 응답 지연 τ = RC']. 추상적('전기 원리') 금지, 구체적 법칙·방정식 명시.

**4. applicable_standards 식별 (0~5개)**: 발명이 따르거나 인용할 수 있는 산업 표준 — 형식 '[규격명] 표준번호: 표준명'. 예: ['IEC 60068-2-1: 환경시험 - 저온', 'ISO 8536: 의료용 수액 백', 'KS C 0223: 가전기기 안전']. 없거나 무관하면 빈 배열.

**5. ipc_range 추론 (2~6개)**: governing_principles + primary_domain 에서 합리적 IPC Class 또는 Subclass prefix. 정밀 분류(classify_invention)와 별개로, 본 추론 단계의 frame 식별용. 예: ['G01K', 'H05B', 'B65D'].

**6. known_patent_issues 식별 (이 도메인의 일반 거절 패턴, 0~5개)**: 한국 KIPO 심사에서 본 도메인의 발명이 자주 받는 거절 사유. 예: ['IoT 센서 분야 — 단순 sensor + display 조합의 진보성 부족', '의료영상 — 학습 데이터셋 미공개로 enablement 의심']. caller 가 빈번 위험을 미리 알게.

**7. fusion_analysis (sub_domains 가 있을 때만)**: 도메인 간 교차점이 발명의 핵심인지 한 단락(2~3문장). 예: '본 발명은 IoT 센서 분야의 NTC 측정 + 색채과학의 ΔE 일치 매핑 의 교차점에서 의의 — 단순 측정값 표시가 아니라 색상 변별 가능한 영역만 변환'. 없으면 null.

**8. reasoning_focus 처리**: context.inputs.reasoning_focus 가 있으면 governing_principles 와 ipc_range 를 그 요소 위주로 좁힘. 없으면 발명 전체에서 추론.

**9. 작성 톤·정확성**: 도메인 식별이 후속 4단계의 frame 이므로 정확성이 핵심. 의심스러우면 광범위한 sub_domain 으로 — 잘못된 단일 frame 보다 폭넓은 frame 이 안전.

## Output Contract

`domain-identification-output`
