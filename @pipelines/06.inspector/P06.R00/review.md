# P06.R00.REVIEW_DRAWING :: review

> Gemini Vision multimodal 호출: 도면 이미지 + drawing_meta + numerals → 6 항목 검수표 + overall_pass + revision_comment 생성.

## Instructions

[INPUTS] 의 figure_b64 (multimodal image — figure_mime 으로 type 식별) 를 직접 시각 분석.

검수 항목 6개 — 각각 {item, pass, comment}: (1) 도면 종류가 [INPUTS].drawing_meta.type 과 부합 (2) [INPUTS].drawing_meta.key_elements 모두 표현 (3) [INPUTS].numerals 가 도면에 표시 — 누락·오타 (4) 부호 위치가 가리키는 부품 옆에 적절 (5) 도면 가독성·구조 명확성 (6) 한국 특허청 도면 형식 적합 (배치·여백·텍스트).

overall_pass: high-severity 항목 (1, 2, 3) 모두 pass 면 true. medium (4, 5, 6) 은 권고.

revision_comment: fail 시 DL 단계 회귀에 사용할 보완 지시 한 단락 — 어떤 element 보강·어떤 부호 추가·어떤 형식 수정. pass 면 빈 문자열.

## Output Contract

`review-drawing-output`
