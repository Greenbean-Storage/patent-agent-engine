# P02.R12.DRAWING_ORCHESTRATION :: finalize

> 도면 작업 최종 저장 + IOM 갱신 결정.

## Instructions

1. aggregate_inspect.needs_revision=false 면 IOM 의 drawings 섹션을 최종 patch.

2. dispatch_choice 출력 (0=완료→director, 1=재시도).

3. drawings_summary 출력 — 최종 도면 갯수 + 검수 통과 여부.

## Output Contract

`drawings-summary-output`
