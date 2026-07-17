# Roadmap 갱신 — 4-mode reasoning

매 사이클 *전체 list (해소 포함)* 보고 4-mode 중 어떤 reasoning 적용할지 결정.

## Input 자료

- `conversation`: 사용자 대화 누적 (DRO 가 user/assistant turn 모두 보존). `meta.kind == "roadmap.answer"` 인 user turn 은 *로드맵 항목 응답*.
- `concept_maturity_model`: 현재 CMM (3 지표 + 7 sub-score + rationales). 어떤 sub 가 부족한지 보고 새 질문 우선순위 결정.
- `concept_discovery_stack`: 사용자 말 7 필드 누적 (purpose / components / sequence / causality / embodiments / differentiation / effects). 이미 채워진 정보는 *반복 질문 X*.
- `user_roadmap`: 이전 사이클의 list (= 너의 직전 출력). 같은 id 는 *반드시 보존*.
- `invention_object_model`: 작성 단계 후 채워지는 IOM. 구체화 단계엔 대부분 비어있음.

## 4-mode reasoning

매 item 별로 어느 mode 인지 판단:

### 1. 유지 (preserve)
이전 사이클 item 중 *답변 없음* + *여전히 유효* 한 항목 — 같은 id 유지, status/priority 그대로.

### 2. 해소 (satisfy)
사용자가 답한 항목 — conversation 의 `meta.kind == "roadmap.answer"` 인 user turn 의 `roadmap_item_id` 가 어느 item 인지 매핑.
또는 *자유 대화* 로 사용자가 정보 제공한 경우 — CDS 의 해당 필드 채워진 게 명확하면 status=satisfied.
- `status = "satisfied"`
- `answer = {"value": "...", "answered_at": "<ISO timestamp>"}`
- 같은 id 유지

### 3. 분화 (branch)
큰 항목이 사용자 진행으로 *세분화 가능* 해진 경우:
- 큰 항목은 status=satisfied 처리 (만약 그 안의 큰 정보가 충분이 들어왔다면)
- 자식 항목 신설 (새 UUID, 새 item).

트리 구조 X — flat list 안 새 item.

### 4. 신설 (create)
conversation / IOM / CMM 가 *새 정보 필요* 시사 — 새 item:
- CMM 의 부족한 sub (점수 낮은 항목) 보강 질문
- CDS 의 비어있는 필드 채울 질문
- 새 UUID

## ★ id 보존 규칙 (D 안 자연 누적의 핵심)

- 같은 의미의 항목은 사이클 넘어가도 *반드시 같은 id 유지*.
- 사용자가 응답한 항목 (`status = "satisfied"`) 도 *list 에서 제거하지 말고 유지*. 해소된 item 도 list 안에 남음.
- 새 item 만 새 UUID 부여.
- ID 중복 금지 (tool 이 검증).

## 우선순위 (priority) 결정 기준

| priority | 의미 |
|---|---|
| 1 | 발명의 핵심 정체성 (purpose, components) — CMM 0.0~0.5 일 때 우선 |
| 2 | 동작·작동 메커니즘 (sequence, causality) — CMM completeness 부족 시 |
| 3 | 분류·맥락 (관심 분야, 적용 영역) — IPC hint |
| 4 | 특허성 차별점·효과 (differentiation, effects) — CMM potential 부족 시 |
| 5 | 부가 정보 (실시예 다양성, 응용 시나리오) |

## input_type 결정 가이드

| input_type | 사용 시점 |
|---|---|
| `chat` | 자유 서술 필요 (대부분의 핵심 질문) |
| `selection` | 객관식 1개 — 분류, 카테고리 (예: 관심 분야 1개) |
| `checkbox` | 다중 선택 — 효과 list, 응용 분야 list |
| `keyword` | 짧은 단어 1-2개 (Buddy 가 사후 검토할 키워드) |
| `none` | 정보 완성, 추가 입력 불필요 |

`selection` / `checkbox` 의 `options` 는 항상 3-5 개 권장.

## 출력 (JSON array only)

top-level JSON array. 각 item 은 8 필드 strict:

```json
[
  {
    "id": "uuid-string",
    "title": "사용자에게 보이는 질문",
    "description": "LLM 내부 reasoning 메모 (왜 이 항목 추가/유지)",
    "status": "pending" | "satisfied" | "skipped",
    "priority": 1 | 2 | 3 | 4 | 5,
    "input_type": "chat" | "selection" | "checkbox" | "keyword" | "none",
    "options": null | ["opt1", "opt2", ...],
    "answer": null | {"value": "...", "answered_at": "ISO date-time"}
  }
]
```

- `description` 은 사용자 비공개 — LLM 자신의 reasoning 메모.
- `status = "satisfied"` 면 `answer` 필수 (null 아님).
- `status = "pending" | "skipped"` 면 `answer = null`.
- `input_type = "selection" | "checkbox"` 면 `options` 는 string array (3-5개).
- 그 외 input_type 은 `options = null`.

## 첫 사이클 (current_roadmap 이 빈 array)

기본 5-7 개 핵심 질문 신설. 예시:
- "발명의 목적은?" (chat, priority 1)
- "핵심 구성요소?" (chat, priority 1)
- "관심 분야?" (selection, priority 3)
- "동작 순서?" (chat, priority 2)
- "기존 기술과 차별점?" (chat, priority 4)
- "어떤 효과가 있는지?" (checkbox, priority 4)
