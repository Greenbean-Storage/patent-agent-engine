# Concept Discovery Stack — 정보 추출

사용자와의 대화 (`conversation`) 와 현재 stack (`current_stack`) 을 보고 발명 구체화 단계의 7 정보 필드를 갱신한다. 사용자의 새 메시지에서 추가된 정보를 *기존 stack 에 더한다* — 덮어쓰지 말고 누적.

## 7 필드 정의

| 필드 | 무엇 | 형식 |
|---|---|---|
| `purpose` | 발명의 *목적* — "왜 이 발명이 필요한가". 해결하려는 문제 + 사용자 + 응용 분야. | string (1-2 문장) |
| `components` | 핵심 *구성요소* — 발명을 이루는 필수 element 들. 부품·모듈·하드웨어·소프트웨어 등. | list of string |
| `operation_sequence` | 동작 *순서* — 구성요소들이 어떤 순서로 동작하는지. 단계별 흐름. | list of string |
| `causality` | *인과* 관계 — "X 가 일어나면 Y" 형식. 메커니즘·원리·조건. | list of string |
| `embodiments` | *실시예* — 구체적 사용 사례·시나리오·구현 방식. 다양할수록 좋음. | list of string |
| `differentiation` | 종래기술 대비 *차별점* — 기존 기술과 무엇이 다른가. | string |
| `effects` | *효과* — 발명으로 얻는 결과·이점·개선. | list of string |

## 규칙

- **누적 우선**: 기존 stack 의 항목은 *유지*. 새 메시지에서 발견한 정보만 *추가/보완*.
- **사용자 말 그대로**: AI 가 임의 해석·추측 금지. 사용자가 명시한 내용만.
- **empty 허용**: 정보가 아직 없는 필드는 빈 string `""` 또는 빈 list `[]`. 첫 사이클에는 대부분 empty 가능.
- **중복 제거**: list 항목이 의미적으로 같은 것은 1개로 통합 (e.g., "스마트폰 거치대" + "휴대폰 거치대" → 1 항목).
- **간결**: list 항목은 1 문장 이하. 길면 분할.

## 출력 (JSON only)

```json
{
  "purpose": "...",
  "components": ["...", "..."],
  "operation_sequence": ["...", "..."],
  "causality": ["...", "..."],
  "embodiments": ["...", "..."],
  "differentiation": "...",
  "effects": ["...", "..."]
}
```

`last_updated` 는 *tool 이 추가*. JSON 키 7개만 응답.
