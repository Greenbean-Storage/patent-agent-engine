# `@knowledge/rejections/` — 출원 거절사유 히스토리

director가 명세서·청구항을 작성·검토할 때 system_prompt로 주입할 거절사유 회피 가이드. 3-layer 구조 중 **Layer 1 (고정 summary)** 부터 단계적 도입.

## 3-Layer 구조

| Layer | 내용 | 트리거 | 상태 |
|---|---|---|---|
| **1 — 고정 summary** | 주요 거절사유 7-10개 카테고리 (법적 근거·패턴·회피 가이드·사례·체크리스트) | 매 director 라운드 (system_prompt 정적 prefix) | ✅ **PR-A 완료** |
| **2 — by-section** | IPC Section(8개) 단위 분야 특이 거절 패턴 | 분류 코드 채워진 후 라운드 (load_rejections_section stage가 동적 로드 → user message) | ✅ **PR-B 완료** |
| **3 — RAG cases** | KIPRIS 거절결정서·의견제출통지서 벡터 인덱스 (Chroma + Gemini gemini-embedding-001), 의미 유사 사례 top-K 검색 | 분류 정해진 후 director가 1회 fetch → contexts/rejection-cases.json 캐시 → 다중 워커 활용 | ✅ **PR-C 완료** (256 cases indexed) |

## 출처 (PR-A)

KIPO 「특허·실용신안 심사기준」 Part 01 (총칙) + Part 03 (특허요건) + Part 04 (명세서·청구범위) — 이미 [`@knowledge/drafting/raw/`](../drafting/raw/)에 추출된 자료를 입력으로 1회성 LLM 요약. 추가 다운로드 0.

라이센스: KOGL 2.0 (상업 OK, 출처 명시).

## 파일

```
rejections/
├── version.json                  # 빌드 메타 (출처·라이센스·input/output 토큰)
└── summary.md                    # Layer 1 (1회성 Claude Opus 4.7 요약, ~10K 토큰)
                                  # ← system_prompt inject_knowledge 대상
```

PR-B 완료 후 추가:
```
├── by-section/                   # PR-B (Layer 2)
│   └── A.md ~ H.md               # 8 Section 분야별 거절 패턴
```

PR-C 완료 — KIPRIS 거절결정서/의견제출통지서 본문 RAG:
```
└── cases/                        # PR-C (Layer 3 RAG, gitignore)
    ├── chroma.sqlite3            # 벡터 인덱스 (Chroma persistent, ~21MB / 256건 기준)
    └── meta.json                 # 빌드 통계 (키워드·서비스·indexed 수)
```
- 인덱스 빌더: [`tools/rejections-indexer/rejections_indexer/cases.py`](../../tools/rejections-indexer/rejections_indexer/cases.py)
  - KIPRIS Plus REST: `IntermediateDocumentREService`(거절결정서) + `IntermediateDocumentOPService`(의견제출통지서) advancedSearchInfo
  - 키워드 7개 (진보성·신규성·명확성·기재불비·식별력·산업상이용가능성·보정) × 2 서비스 메타 수집 → 중복 제거 → PDF 다운로드 → `pypdf` 텍스트 추출 → 법조항 정규식 추출 → Gemini `gemini-embedding-001` (3072차원) 임베딩 → Chroma persistent
- finder MCP `search_rejection_cases(query_text, ipc_filter, top_k)` — Chroma 벡터 검색 (ipc_filter는 향후 enrichment용 placeholder)
- finder MCP `analyze_rejection_risk(claim_text, ipc, ...)` — LLM 위험 합성 (W03.R20 sub-pipeline)
- contexts/rejection-cases.json — director 1회 fetch 후 캐시, thinker도 GET 가능

## 빌드

```bash
make build-rejections-summary     # PR-A: drafting/raw → summary.md
make build-rejections-by-section  # PR-B: drafting/raw → by-section/{A..H}.md (8 Section)
make build-rejections-cases      # PR-C: KIPRIS 메타 fetch + PDF + 임베딩 + Chroma 인덱싱 (무거움, 5-10분)
make build-rejections             # PR-A + PR-B (cases 제외, summary + by-section)
make verify-rejections            # 산출물 사이즈·존재 검증
```

빌더 코드: [`tools/rejections-indexer/`](../../tools/rejections-indexer/).

ANTHROPIC_KEY는 AWS Secrets Manager `llm-providers/prod/personal` IAM Role 자동 로드.

## 거절사유 카테고리 (Layer 1)

1. 산업상 이용가능성 / 발명 성립성 (특법 §29① 본문, §2)
2. 신규성 부재 (특법 §29①)
3. 진보성 부재 (특법 §29②)
4. 기재불비 — 실시가능 요건 (특법 §42③제1호)
5. 청구범위 명확성 위반 (특법 §42④제2호)
6. 청구범위 뒷받침 위반 (특법 §42④제1호)
7. 확대된 선원 (특법 §29③)
8. 선원 (특법 §36)
9. 명세서·청구범위 불일치
10. 보정 시 신규사항 추가 (특법 §47②)

## 정책

- **법적 효력**: 원본 KIPO 심사기준에. 이 요약본은 보조 가이드.
- **summary.md**는 1회성 LLM 산출물 — 재현 가능하나 결정론적 동일 결과는 아님.
- KIPO 심사기준 개정 시 → `make build-rejections` 재실행.
