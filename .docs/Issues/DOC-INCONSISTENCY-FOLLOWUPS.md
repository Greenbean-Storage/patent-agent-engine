# 문서 정합 후속 작업

문서 정합 후속 작업.

## 1. validator negative test — validate-stage 단 미흡 (walker 단은 해소)

**현황 (부분 해소)**: walker 단 음성 테스트는 실재 — `tests/invoke/invoke/suites/dro/test_pipeline_walker.py` 가 legacy top-level key·step.type·cross-persona llm_tool·legacy instructions 거부를 검증하고 `test_dispatch_resolver.py` 가 self-recursion 가드를 검증. 그러나 **validate-stage 단 음성 테스트는 여전히 부재** — stage_03(phantom dispatch target)·stage_15(instructions/tool XOR)·schema(`additionalProperties:false`/enum/minimum) 제약을 *누가 약화시킬 때* 거부하는지 확인하는 테스트가 없음 (`tests/validate/tests` 디렉토리 부재).

**위험도**: 낮음 — jsonschema strict / enum 은 표준 라이브러리 동작이고, stage 들이 실 22 pipeline 으로 positive 검증됨(`make validate` 15 stage). 단 schema/stage 로직 약화 시 회귀 감지 못함.

**해결 방향 (후속)**: `tests/validate/tests/` 에 stage 단 음성 케이스 추가 — bad pipeline 을 각 stage 에 먹여 거부 확인 (phantom dispatch · instructions/tool XOR 위반 · additionalProperties 위반). 신 7개 fetch tool allowlist 기준.
