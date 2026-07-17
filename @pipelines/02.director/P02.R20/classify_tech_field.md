# P02.R20.CLASSIFY_INVENTION :: classify_tech_field

> 분류 shard A: 발명의 기술분야 + 응용분야 식별.

## Instructions

1. IOM.specification.technical_field + IOM.bibliographic 을 보고 IPC/CPC 의 1차 분류 추정.

2. shard_a_result 출력 — {tech_field_top: string, ipc_hint: list[string]}.

## Output Contract

`classify-shard-a-output`
