# Actor 재편 시 고려사항 (DRO 재편 중 표면화된 Actor-side 결정)

> **Actor 의 composer / prompt 조립 동작** 결정 항목. §A.1~9 = 미결(composer 후속 작업에서 결정), §B = 확정 경계.
> 경계 철학 (DRO = 흐름·LLM/프롬프트 무지 / Actor = 순수함수형 실행자 — `@pipelines`·context 직접 읽고 prompt 조립, 파이프라인 흐름은 모름).

## A. 컨텍스트 주입 / 프롬프트 조립 (Actor composer)

Actor 가 RT 를 prompt 로 만드는 방식 — DRO 는 관여 안 함. (DRO 재편 중 "컨텍스트 주입" 토픽에서 표면화됐으나 Actor 동작.)

1. **프롬프트 섹션 순서·구조** — 현행 `[PERSONA][CONTEXT][FRAGMENTS][TASK][DISPATCH_GUIDE][RECOMMENDED]`. 유지/변경.
2. **섹션 라벨 표시** — 프롬프트에 `[CONTEXT]` 등 라벨 노출 여부.
3. **강제주입 자료 펼침 형식** — `## 이름\n값` inline 표현.
4. **inject_context 허용 자원(allowlist)** — `cm://`·`@knowledge` 의 허용 자원을 고정 목록(검증 가능)으로 제한 vs 자유 개방. (composer fetch + validate stage)
5. **fragments(고정텍스트)** — 4번째 주입 수단. 유지 여부·위상(강제주입과 동급?). prompt 조립 측면.
6. **cascade 4계층 머지**(GLOBAL→persona.COMMON→pipeline.common→step) — prompt context 합성 측면은 composer. **단 현재 RT-build 단계 머지는 DRO 쪽으로 보임**(composer 엔 cascade 없음, grep 0) → Actor 재편 시 *누가 머지하나* DRO 와 경계 재확인 필요.
7. **dispatch_choice_guide 프롬프트 배치/범위** — 분기 있는 step 프롬프트에 선택지 안내를 어떻게·어디에.
8. **멀티미디어(media_parts) 조립** — 이미지/문서 첨부를 prompt parts 로 넣는 방식(Gemini multimodal).
9. **IOM(발명 내용) 강제주입 범위** — 발명 모델을 모든 LLM 단계에 무조건 끼울지(inject) vs 추천으로 둘지. 파이프라인 선언 + composer 영역.

## B. 확정된 경계 (DRO 결정 — Actor 재편 시 재론 X)

- composer(`@pipelines` instructions 읽기 + `cm://` fetch + prompt 조립)는 **Actor 가 직접** 수행 (DRO 가 읽어 전달하지 않음).
- Actor = 순수함수형 실행자: 자기 instructions·RT·체인데이터(다른 RT 출력·agent_state·cm://)는 직접 읽되, **파이프라인 흐름/구조는 모름**.
- DRO 는 흐름(순차/병렬·dispatch)만 알고 LLM/프롬프트는 모름.
