# P02.R12.DRAWING_ORCHESTRATION :: review_render

> 도면 렌더링 결과 review 후 다음 단계 결정.

## Instructions

1. context.steps.review_dl_batch.drawings_with_dl 의 DL 코드 정합성 확인.

2. needs_revision 이면 self-recursion (dispatch_choice=1), 아니면 렌더 → 검수 단계로 진행 (dispatch_choice=0).

3. proceed_to_render 출력 (bool).

## Output Contract

`dl-batch-decision-output`
