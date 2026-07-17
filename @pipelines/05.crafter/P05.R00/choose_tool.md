# P05.R00.GENERATE_DL :: choose_tool

> 도면 type/title/key_elements/format_hint 기반 적합한 DL 도구 결정 + file_extension + figure_format.

## Instructions

[INPUTS].drawing_meta.type 별 권장 도구 (drawing_tool_selection fragment 참고): circuit→schemdraw, flowchart/sequence→plantuml, perspective/section→openscad, chemical→plantuml.

[INPUTS].drawing_meta.format_hint (Director hint) 우선 — 단 type 과 명백히 부합하지 않으면 hint 무시 + rationale 명시.

시스템 지원: plantuml/openscad/schemdraw 셋만. cadquery→openscad, smiles→plantuml 환원 필수.

[INPUTS].existing_dl 가 있으면 (검수 fail 회귀) 그 코드의 도구 유지 — 변경 금지. @startuml=plantuml, .scad=openscad, import schemdraw=schemdraw.

file_extension: plantuml→puml, openscad→scad, schemdraw→py (lowercase, 점 없음).

figure_format: 한국 출원은 svg 권장 (벡터). 또는 png. 기본 svg.

rationale 한 문장 — 왜 이 도구 적합 (구체적, 추상 금지).

보수적: type 모호하면 plantuml. 미지원 도구 선택 금지.

## Output Contract

`select-tool-output`
