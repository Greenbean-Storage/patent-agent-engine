# P02.R21.CLASSIFY_SHARD :: classify

> 단일 shard 분류 작업 (P02.R20 의 sub).

## Instructions

1. shard_input 의 element 들을 IPC/CPC 의 leaf 클래스로 매핑.

2. shard_result 출력 — {classifications: list[{code: string, confidence: number}]}.

## Output Contract

`classify-shard-output`
