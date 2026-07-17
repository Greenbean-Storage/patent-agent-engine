# manual-indexer

`@knowledge/drafting/` 정적 자산을 KIPO 심사기준 PDF에서 빌드한다.

## 출처

KIPO 「특허·실용신안 심사기준」 7개 PDF (~7.6 MB total, KOGL 2.0 라이센스).

URL 패턴:
```
https://www.kipo.go.kr/upload/mobile/exammanual/pdf/exammanual_{01..07}.pdf
```

| Part | 주제 |
|---|---|
| 01 | 총칙 |
| 02 | 특허출원 |
| 03 | 특허요건 |
| 04 | 명세서 등의 보정 + 청구범위 작성 (핵심) |
| 05 | 심사절차 |
| 06 | 특수한 출원 |
| 07 | 기타 |

## 단계

1. **fetch** — 7 PDF 다운로드 → `.cache/`
2. **extract** — `pypdf`로 텍스트 추출 → `@knowledge/drafting/raw/exammanual_*.md` (페이지 헤더·푸터 정리)
3. **summarize** — Claude Opus 4.7로 1회성 요약 → `@knowledge/drafting/summary.md` (5-10K 토큰 목표)
4. **write** — `version.json` + `README.md` 갱신

## 빌드

```bash
cd tools/manual-indexer
uv sync --no-dev

# 단계별
uv run python -m manual_indexer extract
uv run python -m manual_indexer summarize

# 한 번에
uv run python -m manual_indexer build
```

또는 프로젝트 루트:
```bash
make build-drafting-raw       # fetch + extract
make build-drafting-summary   # raw → summary.md
make build-drafting           # 한 번에
```

## 정책

- KIPO 자료는 KOGL 2.0 (상업 OK), 출처 명시
- 요약은 1회성 — model: claude-opus-4-7. ANTHROPIC_KEY는 AWS Secrets Manager `llm-providers/prod/personal`에서 로드 (IAM Role 사용).
- 원본 raw + summary 둘 다 git 커밋 (재요약·근거 추적용)
