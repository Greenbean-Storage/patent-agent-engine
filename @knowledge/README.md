# `@knowledge/` — Domain Knowledge Assets

특허 작성·심사 도메인 지식을 모아두는 정적 자산 디렉토리. 코드와 함께 git으로 관리한다.

`.docs/` 와의 차이:
- `.docs/` — 시스템 **설계·외적 자료** (아키텍처 문서, 의사결정 기록 등). 사람이 읽는 문서.
- `@knowledge/` — 런타임 **동작에 사용**되는 도메인 지식 (LLM 컨텍스트로 주입, 매핑·검색 등). 빌드 산출물 + 큐레이션 자산.

`@`-prefix는 [`@contracts/`](`@contracts/`), [`@pipelines/`](`@pipelines/`)와 동일한 컨벤션 — 동작 데이터.

## 현재 포함

| 디렉토리 | 내용 | 빌더 |
|---|---|---|
| [classification/](classification/) | IPC + CPC 분류 트리·정의·매핑 | [tools/classification-indexer/](../tools/classification-indexer/) |

## 향후 (예정)

- `drafting/` — 한국 특허 명세서 작성요령
- `rejections/` — 출원 거절사유 히스토리·분류별 패턴
- `expertise/` — 특허법·시행령·시행규칙 요약 (멀티 서브 에이전트 컨텍스트)

## 빌드 산출물 vs 큐레이션 자산

산출물(예: `classification/`)은 외부 출처에서 다운로드·파싱·결합한 결과를 재현 가능하게 빌드한다. 빌드 스크립트는 `tools/` 아래에 둔다. 출처·라이센스는 각 하위 디렉토리의 `README.md` + `version.json` 참조.
