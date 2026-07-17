# `@knowledge/drafting/` — KIPO 심사기준 작성요령

director가 명세서를 채울 때 system_prompt로 주입할 정적 가이드. 원본 7 PDF 추출본 + 1회성 LLM 요약본.

## 출처

KIPO 「특허·실용신안 심사기준」 7개 PDF (2026.03 기준).

| Part | 주제 | 토큰(추정) |
|---|---|---|
| 01 | 총칙 | ~29K |
| 02 | 특허출원 | ~17K |
| 03 | 특허요건 | ~24K |
| 04 | 명세서 등의 보정 + 청구범위 작성 | ~14K |
| 05 | 심사절차 | ~23K |
| 06 | 특수한 출원 | ~22K |
| 07 | 기타 | ~38K |
| **합계** | | ~167K |

URL 패턴: `https://www.kipo.go.kr/upload/mobile/exammanual/pdf/exammanual_{01..07}.pdf`. 라이센스: KOGL 2.0 (상업적 이용 가능, 출처 명시).

## 파일

```
drafting/
├── version.json                  # 빌드 메타 (출처·라이센스·각 Part 토큰)
├── raw/                          # 원본 텍스트 추출 (재요약·근거 추적용)
│   ├── exammanual_01.md ~ 07.md
└── summary.md                    # 1회성 Claude Opus 4.7 요약 (~10K 토큰)
                                  # ← system_prompt 주입 대상
```

## 빌드

```bash
make build-drafting-raw           # PDF 다운로드 + 텍스트 추출
make build-drafting-summary       # raw/* → summary.md (Claude 호출)
make build-drafting               # 한 번에
```

빌더 코드: [`tools/manual-indexer/`](../../tools/manual-indexer/).

ANTHROPIC_KEY는 AWS Secrets Manager `llm-providers/prod/personal`에서 IAM Role로 자동 로드.

## 정책

- **법적 효력**: 원본 KIPO 심사기준에. 이 요약본은 보조 가이드.
- **summary.md**는 1회성 LLM 산출물 — 재현 가능하나 결정론적 동일 결과는 아님 (모델·온도 의존).
- KIPO 심사기준 개정 시 → `make build-drafting` 재실행. version.json의 `built_at` 갱신.
