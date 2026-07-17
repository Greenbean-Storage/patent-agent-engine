# P02.R12.DRAWING_ORCHESTRATION :: review_dl_code

> 생성된 도면 코드의 청구항 부합성·시각 가독성 검토.

## Instructions

**1. drawings_with_numerals ↔ dl_results 매칭**: context.steps.review_numerals_batch.drawings_with_numerals 와 context.steps.generate_dl_fanout.dl_results 를 인덱스 또는 drawing_id 로 매칭.

**2. chosen_tool ↔ drawing.type 부합성**: dl_results 의 chosen_tool 이 drawing.type 에 적합한지. (a) circuit → 'schemdraw' (적합) / 'plantuml' (부적합). (b) flowchart/sequence → 'plantuml' 또는 'mermaid'. (c) perspective/section/assembly → 'openscad' 또는 'cadquery'. (d) chemical → 'smiles'. 부적합 조합이면 fail.

**3. DL 문법 무결성 검사**: (a) **plantuml**: @startuml 으로 시작 @enduml 으로 종료, 짝 매칭, skinparam·class·actor 등 구문 정상. (b) **openscad**: module/translate/rotate/cube/cylinder 등 키워드, ; 종결, {} 짝 매칭. (c) **schemdraw**: import schemdraw / d=schemdraw.Drawing() / d.save() 호출 포함, element 추가 d += elm.X 구문. (d) **mermaid**: graph TD/LR 시작, --> 화살표 문법. (e) **smiles**: 화학 SMILES 표기 규칙 (괄호/숫자 매칭). 문법 깨지면 fail.

**4. 부호 누락 검사**: drawing.numerals 의 각 ref 가 dl_code 본문에 등장하는지(주석 또는 라벨로). 예: schemdraw 에서는 `d += elm.Resistor().label('NTC 서미스터(110)')`. 부호가 빠지면 도면-청구항 정합성이 깨져 fail.

**5. 용어/부호 불일치 검사**: dl_code 의 라벨 텍스트가 numerals[*].name 과 일치하는지. 예: numerals 에는 'NTC 서미스터' 인데 dl_code 에는 'NTC sensor' 로 영문 → fail. 한국어 라벨 우선.

**6. drawings_with_dl 배열 생성**: 각 drawing object 에 다음 필드 추가 — dl_code(string) / chosen_tool(string) / file_extension(string: 'puml', 'scad', 'py', 'smi') / figure_format(string: 'svg', 'png', 'pdf' 등 렌더 출력 포맷) / dl_payload({drawing_id, dl_code, chosen_tool, file_extension, figure_format, render_hint}) — save_drawing_artifacts 가 사용하는 wrapper.

**7. checks + needs_revision**: 위 4축의 검사 결과를 {item, pass, comment} 배열로. 1개라도 fail 이면 needs_revision=true.

**8. revision_comment 작성**: 도면별 구체 지시를 모은 한 단락. 예: 'fig2 의 chosen_tool 을 plantuml 에서 schemdraw 로 변경, 부호 (200,210,220) 모두 라벨로 표기. fig3 의 @enduml 누락 — 추가'. generate_dl_fanout 의 다음 라운드에 전달.

**9. 보수적 검수**: DL 문법 결함은 무조건 fail (렌더 단계에서 어차피 깨짐). 부호 누락도 무조건 fail.

## Output Contract

`review-dl-batch-output`
