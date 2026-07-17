# P04.R10.EXTRACT_NUMERALS :: extract

> 도면 또는 명세서에서 참조부호 후보(숫자+라벨 짝) 를 추출 + 표준화 + 누락 부호 신규 부여 제안.

## Instructions

**1. 도면 컨텍스트 파악**: context.inputs.drawing_meta 의 (a) drawing_id, (b) type, (c) title, (d) key_elements 를 읽음. context.inputs.patent_model 의 specification + claims 도 참조해 부호 라벨의 한국어 표준 명사 확정.

**2. drawing_meta.type 별 추출 전략 적용**: (a) **circuit**: 능동/수동 부품(저항·콘덴서·트랜지스터·IC·다이오드), 회로 노드, 신호 라인, 전원/접지 — 부품 단위 부여. (b) **perspective / section / assembly**: 외형 부품(케이스·뚜껑·표면), 결합부(나사·힌지), 내부 핵심 기구(서미스터·LED·MCU 모듈) — 형상 단위 부여. (c) **flowchart / sequence**: 처리 단계(S100, S110...), 모듈, 결정 분기, 데이터 흐름 — 단계 단위 부여(번호 prefix 'S'). (d) **chemical**: 작용기, 화합물, 반응 경로 — 분자 단위 부여. type 에 맞는 추출 단위 적용.

**3. 참조번호 패턴 부여**: 주요 구성요소 base 100/200/300... 의 단위. 같은 base 의 자식 110/120/130... — 예: 'PCB' = 100, 'PCB 상 NTC' = 110, 'PCB 상 MCU' = 120, 'PCB 상 LED 드라이버' = 130. base 단위는 도면 1당 1개 base(100 단위)만 사용하는 게 일반적이나 도면이 여러 sub-system 을 보이면 2개(100, 200) 사용.

**4. existing_numerals 보완 모드 처리**: context.inputs.existing_numerals 가 list 로 오면 — (a) 그 기존 부호는 ref/name 절대 변경 금지(보존). (b) revision_comment 의 지시에 따라 누락된 부품만 추가, 잘못된 description 만 수정. (c) ref 재할당 금지. existing 없으면 신규 모드 — 새로 부호 set 생성.

**5. numerals 배열 작성**: 각 entry — (a) **ref**: 번호 문자열('100', '110', 'S100'). (b) **name**: 한국어 명사구('NTC 서미스터', '제어부', '온도 측정 단계'). 영문 약어는 한국어 뒤 괄호 병기 가능('마이크로컨트롤러(MCU)'). (c) **description**: 1문장 — 이 부품의 발명 내 역할('음료 온도를 저항 변화로 측정하는 NTC 형 서미스터'). (d) **drawing_role**: 도면 내 위치·역할 한 구('PCB 좌상단 측정부', '제어부의 입력 단자', 'S100~S130 의 시작 단계').

**6. drawing_id echo**: context.inputs.drawing_meta.drawing_id 를 그대로 output.drawing_id 에 복사 — fan_out 결과를 다음 review_numerals_batch step 이 인덱스 매칭하는 source.

**7. extraction_notes 작성**: 한 단락 — (a) drawing_meta.type 에 맞춰 어떤 추출 전략을 적용했는지, (b) 도면에서 제외한 요소(예: '환경 라벨, 일반 명사는 부호 부여 대상에서 제외'), (c) existing_numerals 가 있었으면 어떤 보완을 했는지. 다음 단계 검수의 단서.

**8. 한국어 라벨 강제**: 모든 name 은 한국어 명사구. 영문만('Thermistor') 또는 영문 위주 라벨 금지. 영문 약어는 괄호 병기.

**9. 부호 개수**: 한 도면당 5~15개 부호가 적정. 너무 적으면(< 3) 도면 정보 부족, 너무 많으면(> 20) 청구항·명세서 정합성 부담. drawing_meta.key_elements 의 element 수 ± 3 이내가 일반적.

**10. 보수적 추출**: 핵심이 아닌 일반 부품(전원선·접지·일반 라벨)은 제외. 청구항 인용 가능성·발명 본질 관련 부품만 부호 부여.

## Output Contract

`extract-output`
