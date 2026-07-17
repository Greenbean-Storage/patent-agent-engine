# P05.R00.GENERATE_DL :: generate_dl_code

> chosen_tool 의 DSL 코드 생성. key_elements + numerals 모두 표현, patent_model 본문 반영, existing_dl 보완 모드 지원.

## Instructions

PlantUML 구조 (dl_code_structure fragment 참고): @startuml/skinparam/본문/@enduml 짝 매칭. 라벨 형식 '한국어 명사 (부호번호)'.

OpenSCAD: 파일 상단 주석 + 수치 파라미터 변수 ([INPUTS].patent_model.hard_data) + module 분리 + union/translate + $fn=64. text() 는 2D 투영 우선.

schemdraw: import + d=Drawing() + elm.X().label('한국어 명사 (부호번호)') + d.save(OUT_PATH) (OUT_PATH 는 런타임 주입 — 코드에 정의 X).

[INPUTS].drawing_meta.key_elements + [INPUTS].numerals 모두 코드 라벨에 등장 — 누락 시 후속 검수 fail.

[INPUTS].patent_model.specification.disclosure / solution 의 동작 흐름 반영 (단순 구성요소 나열 X).

[INPUTS].existing_dl + revision_comment 가 있으면 incremental 수정만 — 기존 구조·변수·module 명 보존.

dl_code 출력: 코드 본문만 string. 마크다운 코드블록 금지, 설명 텍스트 금지.

[INPUTS].drawing_meta.drawing_id 를 output.drawing_id 에 복사 (fan_out 인덱스 매칭).

render_hint: suggested_width/height/orientation. circuit→landscape, sequence→portrait. 모르면 null.

generation_notes: 도구 선택 사유 + 부호 배치 + 단순화 부분 (검수 단서).

self-check: 짝 매칭, import 누락, 변수 선언 후 사용.

## Output Contract

`generate-dl-code-output`
