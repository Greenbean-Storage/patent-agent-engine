# Static Block Architecture

정적, 구조적, Block View (Diagram)
특히 **Worker** 를 정의한다.

> **현행 implementation 매핑**: 본 문서의 6 페르소나 워커 (01~06) 는 설계 의도. 실 컨테이너는 **unified 단일 Actor** — `300.Actor` (:59300) 가 P1~P6 전 persona 수락 (수락 집합 = engine.config `personas`, persona 별 동시성 cap = `src/slots.py` 세마포어). Gateway (00) → `DRO` (200.DRO, :59200 단일 — 순수 internal chain executor). Memory (10) → `CM` (400.CM, :59400). mypage 영역 + 외부 게이트웨이 = `Nexus` (100.Nexus, :59100 — SOLE external gateway). 페르소나 ↔ LLM 매핑은 본 문서 그대로, 단일 진실 원천은 `@deployment/engine.config.yaml` 의 `personas` (코드 persona-제로).

## Workers

각 Worker 는 페르소나 단위 1:1 — 실 Docker 컨테이너 packing 은 위 매핑 참조.

### 00. Gateway

> 사용자의 모든 입력과 출력을 통하는 창구 (웹소켓), 1번으로 보내는 Queue, 2번 요청 Flag 관리.
> (프로그램: Agentic AI 없이 고정 로직)
> PORT: 59200

- 사용자의 대화 입력은 응답과 별개로 Queuing.
- 2번으로는 Flag 가 올라가면 요청을 보냄, Flag 조건: 새로운 컨텍스트 (대화) 가 있으면 Flag-up.
- 즉 1번 요청, 1번의 응답 모두 Flag-up 트리거, 대신, 컨텍스트 전체를 2번이 볼 수 있으므로 하나씩 큐잉하지 않고
- Flag 로 요청 전까지 모든 쌓인 컨텍스트를 한꺼번에 요청하는 형태 (실제로는 2번이 직접 컨텍스트 봄)
- 완성된 특허 데이터 모델을 워드 문서로 생성

### 01. Buddy

> 대화창으로 사용자와 대화로 모델 구체화하는 멀티모달 인터페이스 Agent
> Agent: Gemini 3.1 Pro 기반
> PORT: 59201

- 응답원으로서 현재의 (컨텍스트 + 2번이 완성하는 특허데이터 모델) 을 토대로 대략적으로 사용자와 대화함.
- (사실 중요한 건 데이터 모델의 완성이라서, 사용자에게는 적당한 요약과 칭찬 정도면 됨)

### 02. Director

> 특허 데이터 모델을 평가하고 완성하는 주체
> 전체 전략 (사용자로 다음 체크리스트) 결정, 판단, 평가를 결정하고 제어하는 중앙 Agent
> Agent: Claude Opus 4.7 기반
> PORT: 59202

- 본래 대화로 사용자에게 요청하려고 했으나, 따로 체크리스트를 만드는 형태로 함.
- 현재의 대화 컨텍스트, 현재까지 만들어진 데이터 모델을 기반으로 사용자에게 요청할 다음 체크리스트를 판단함.
- 체크리스트는 단순 문장도 있지만 선택, 다중 선택도 가능함
- 모델이 완성되는 것을 평가하고, 어느 정도 완성되었을 때부터는 등록 가능성도 조금씩 평가하기 시작함.
- 기타 역할: "도면 종류, 도면 종류당 개수 판단", "기재불비(용어 및 부호 불일치) 검수", "도면 DL 반복 검수"

### 03. Finder

> Kipris 특허 등록 검색, 선행기술 검색, 배타성, 등록가능성 평가 분석 데이터 생성 웹 Kipris 서칭 RAG
> Agent: Gemini 3.1 Pro 기반
> PORT: 59203

### 04. Thinker

> 발명품의 수리, 논리, 복잡한 수식 계산 복잡한 사고 주체
> 일부 이해 및 일부 복잡한 모델 (특히, 도면의 부호와 청구항의 관계) Agent
> 도면의 부호 (Ref. Nums) 와 청구항 생성
> Agent: GPT o3 기반
> PORT: 59204

- 도면 핵심 부호 (주석, Reference Numerals) 판단, 리스트 생성 (각 도면당 부호 리스트 만들기)
- 부호를 포함한 청구항 작성, 부호 및 청구항 자가 검수

### 05. Crafter

> 도면 생성 AI: "Code-to-Diagram" (DL to 도면) 전략
> Agent: Claude Opus 4.7 기반
> PORT: 59205

- 도면과 부호(주석) 의 관계를 잘 판단해서 도면 생성
- 도면 Description Language 생성 (각 도면 별)
- 도면 생성 (툴 콜링): 기계 / 회로 / SW(BM) / 화학
  - Mermaid.js (PlantUML), Programmable CAD (OpenSCAD CLI, FreeCAD, CadQuery 등), Python (SchemDraw), SMILES / Python Code

### 06. Inspector

> 발명품의 완성 도면 검수 주체
> Agent: Gemini 3.1 Pro 기반
> PORT: 59206

- 완성 도면 검수, 사용자 도면 초안 검수

### 10. Memory

> 메모리 관리: 특허데이터 모델, 대화 컨텍스트, 진행 컨텍스트 등 저장
> (프로그램: Agentic AI 없이 고정 로직)
> PORT: 59210

- AWS S3 (or RDS) 연동
