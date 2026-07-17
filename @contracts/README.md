# @contracts

API 계약(Contract) 및 데이터 스키마 정의.

## 목적

- 컨테이너 간 통신 인터페이스 정의 (REST / WebSocket / SDK)
- 영속 데이터(IOM / context / chain 메타 등) 모델 표준화
- LLM 응답 강제 (persona 별 stage output contract)
- 파이프라인 정의 메타 스키마

## 구조

```
@contracts/
├── manifest.contract.yaml           # codegen 입력 + 사람 inventory (id·file·kind·owner·consumers)
├── README.md
├── _shared/                          # 워커 횡단 공유 (데이터 모델·인프라 스키마)
│   ├── chain_manifest.schema.json
│   ├── drawing-manifest.schema.json
│   ├── health.schema.json
│   ├── invention-object-model.schema.json
│   ├── manifest.context.schema.json     # 세션 정체성·status·current_phase
│   ├── manifest.models.schema.json      # models/ 인덱스
│   ├── manifest.outputs.schema.json     # outputs/ 인덱스
│   ├── manifest.runtime.schema.json     # runtime chain 인덱스
│   ├── pipeline-definition.schema.json
│   ├── reasoning_task.schema.json
│   ├── models/                          # AI 산출 정량 모델 스키마 (CDS / CMM / UR)
│   │   ├── concept-discovery-stack.schema.json
│   │   ├── concept-maturity-model.schema.json
│   │   └── user-roadmap.schema.json
│   └── runtime/                         # persona 별 runtime 누적 (dialogs 등)
│       ├── 00.dro/
│       ├── 02.director/
│       ├── 03.finder/
│       └── 06.inspector/
├── 00.dro/
│   └── websocket-events.json        # event-catalog (DRO → client push 이벤트)
├── 01.buddy/stages/                 # P01 Buddy
├── 02.director/stages/              # P02 Director
├── 03.finder/stages/                # P03 Finder
├── 04.thinker/stages/               # P04 Thinker
├── 05.crafter/stages/               # P05 Crafter
└── 06.inspector/stages/             # P06 Inspector
```

각 persona 의 `stages/*-output.schema.json` 은 해당 pipeline step 의 `output_contract`
대상 — LLM 이 강제로 따라야 하는 응답 JSON 형식. `@pipelines/0{N}.{persona}/P{NN}.R{NN}.*.pipeline.json`
의 step 에서 `"output_contract": "<id>"` 로 contract id 만 참조하고, [`ContractLoader`](../shared/venezia_contracts/loader.py)
가 파일명으로 lookup.

## 파일 종류 (kind)

| kind            | 확장자          | 설명                                                  |
| --------------- | --------------- | ----------------------------------------------------- |
| `schema`        | `.schema.json`  | JSON Schema (Draft-07). runtime 검증 대상             |
| `data-model`    | `.schema.json`  | 영속 데이터 (IOM·contexts·manifest 등) reference 스키마 |
| `event-catalog` | `.json`         | WebSocket 이벤트 envelope + payload 카탈로그          |

`.schema.json` 은 jsonschema 로 검증 가능. `.json` 은 doc-shaped (정확한 JSON Schema 아닐 수 있음).

## 사용 예시

### Python 에서 schema 로드 + 검증

```python
from venezia_contracts import contracts

# contract id 만 알면 됨 — 디렉토리 위치는 rglob 으로 자동 탐색
result = contracts.validate("chat-assess-output", payload)
assert result.valid, result.errors
```

`ContractLoader.load(name)` 은 `<name>.schema.json` → `<name>.json` 순으로 폴백.

### LLM prompt 주입

```python
prompt += contracts.as_prompt_instruction("chat-assess-output")
```

`_compact_schema` 가 root-level 메타(`title`/`description` 등) 를 strip 한 compact JSON 을 instruction 문자열로 변환.

## 매니페스트

`manifest.contract.yaml` 은 **사람·CI 문서용** 인덱스. contract 의 `id` / `file` 을
한 곳에 명시. runtime validator(`ContractLoader`) 는 manifest 가 아니라 파일명 rglob 으로 동작.

## 규칙

1. JSON Schema 파일은 **Draft-07** 준수 (코드의 `jsonschema.Draft7Validator` 와 정합).
2. 새 contract 추가 시:
   - persona output contract → `0{N}.{persona}/stages/<id>-output.schema.json`
   - 횡단 공유 데이터 모델 → `_shared/<id>.schema.json`
   - `manifest.contract.yaml` 에 항목 추가 (codegen 이 읽음)
3. 변경 시 하위 호환성 유지 (data-model 은 특히 신중 — 영속 데이터의 호환성 문제로 직결).
4. `_shared/` 는 횡단 공유 전용 — 단일 persona 소유면 해당 persona 의 `stages/` 에 둘 것.
