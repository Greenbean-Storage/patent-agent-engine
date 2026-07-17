# DIRECTOR-R00 Residuals

P02 Director 의 R00 chain(구체화 단계)의 알려진 미결 잔재. 각 issue 는 *현상 / 위치 / 영향* 3 필드. 권장·판단·우선순위 없음 (사실만). 설계 reference = `.docs/Features/CONCEPT_MATURITY_FLOW.md`.

---

## 1. roadmap 답변의 `status=satisfied` 가 다음 P02 사이클에 뒤집힐 수 있음

**현상**: roadmap 답변은 REST `PATCH .../estimate/roadmap/{item_id}` 단독(WS action 아님) — Nexus 가 CM item 을 즉시 `status=satisfied` + answer 로 atomic update 한다. 그러나 다음 P02 사이클의 `update_roadmap` LLM (Claude opus) 이 매 사이클 UR 전체를 conversation 기준 재작성하므로, PRODUCTION 모드에서 *충분치 않은 답변* 으로 판단 시 같은 id 의 `status` 를 `pending` 으로 되돌리거나 `answer.value` 를 null 로 둘 수 있다. FIXTURE 모드는 정해진 fixture array 반환이라 검증 불가.

**위치**:
- `@pipelines/02.director/P02.R00/update_roadmap.md` — instructions reference (4-mode reasoning 규칙)

**영향**: 사용자가 REST 로 답해 즉시 `satisfied` 를 관찰한 뒤, 다음 사이클 LLM 재평가로 같은 item 이 `pending` 으로 보일 수 있다 (REST 즉시 확정 ↔ LLM 정성 판단의 시점차).

---

## 2. research/evaluation dialog schema placeholder 부재

**현상**: P03 Finder 의 `research` / `rejection-cases` dialog 와 P06 Inspector 의 `evaluation` dialog 가 누적 자료지만 contract schema 없음. allowlist (`venezia_memory.DIALOG_NAMES`) 에만 등록.

**위치**:
- `@contracts/_shared/runtime/03.finder/dialog/` (디렉토리 자체 없음)
- `@contracts/_shared/runtime/06.inspector/dialog/`

**영향**: 해당 dialog write 시 schema validation 없음. P03/P06 chain 진입 안 한 현시점에선 실 영향 0.

---

## 3. LLM SDK 의 native structured output 의 array root 미지원

**현상**: `update_roadmap` step 의 contract 가 RFC 6901 array root (`update-roadmap-output.schema.json` → `"type": "array"`). 그러나 Claude/Gemini/OpenAI SDK 의 native structured output (response_schema / output_schema) 는 *object root* 만 강제. 현재는 parsing fallback (`json.loads(text)`) 으로 array 수용.

**위치**:
- `300.Actor/src/llm/claude.py:run_stage_structured`
- `300.Actor/src/llm/gemini.py:run_stage_structured`
- `300.Actor/src/llm/openai.py:run_stage_structured`
- `300.Actor/src/llm/session.py` fallback

**영향**: parsing fallback 으로 정상 동작 (검증 완료). 단 SDK 의 *strict mode validation* 은 적용 안 됨. SDK 가 native array root 지원하면 그쪽으로 통일.

---

## 4. probe `view/check/trail/dump-rt` 의 `/chains/{chain_id}` legacy alias 의존

**현상**: probe 의 4 sub-command 가 CM router 의 by-chain alias path (`/sessions/{u}/{i}/chains/{chain_id}` 와 `/chains/{chain_id}/trail` 등) 호출. P-A v3 layout 의 정식 path 는 `/runtime/{persona}/{chain_id}/*` — router 의 alias 가 `_resolve_persona_by_chain` 으로 manifest read 후 정식 path 로 redirect.

**위치**:
- `tests/probe/probe/commands/{view,check,trail,dump_rt}.py`
- `400.CM/src/router.py` 의 `# Legacy by-chain endpoints` 섹션

**영향**: alias 가 살아있는 동안 정상. alias 가 사라지면 probe 깨짐. probe 가 페르소나 인지하도록 갱신 필요 시점은 미정.

---

## 메모

새 issue 발견·기존 issue 해소 시 갱신.
