# P02.R12.DRAWING_ORCHESTRATION :: numerals_decision

> 도면별 numerals review 결과 → 다음 step 으로 진행 결정.

## Instructions

1. context.steps.review_numerals_batch.drawings_with_numerals 검토 후 통과 여부 판단.

2. needs_revision 이면 self-recursion (dispatch_choice=1), 아니면 청구항 작업 단계로 진행 (dispatch_choice=0).

3. proceed_to_claims 출력 (bool).

## Output Contract

`numerals-batch-decision-output`
