# P02.R20.CLASSIFY_INVENTION :: load_subclass_defs

> shortlist subclass 정의 로드 작업의 trigger.

## Instructions

1. shard_a_result + shard_b_result 의 후보 IPC group 들의 subclass 정의 로드 plan.

2. 실제 fetch 는 tool step 또는 next chain 으로 처리.

3. subclass_load_plan 출력 — 각 그룹의 {group_code, subclasses_needed: list[string]}.

## Output Contract

`subclass-load-plan-output`
