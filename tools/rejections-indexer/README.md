# rejections-indexer

`@knowledge/rejections/` 정적 자산 빌드 — 거절사유 히스토리 3-layer 중 **PR-A: Layer 1 (고정 summary)**.

## 출처

KIPO 「특허·실용신안 심사기준」 7개 PDF — 이미 [`@knowledge/drafting/raw/`](../../@knowledge/drafting/raw/)에 추출돼 있음. 추가 다운로드 0.

분량 (참고):
- exammanual_01 (총칙) ~29K 토큰
- exammanual_03 (특허요건) ~24K — 신규성·진보성 거절사유 핵심
- exammanual_04 (명세서·청구범위) ~14K — 기재요건·청구항 명확성 거절
- 합계 ~167K 토큰

## 단계

PR-A는 단일 단계:

- **summarize** — 위 7 part raw를 입력으로 Claude Opus 4.7 1회성 호출. "거절사유 위주" 지침으로 5-10K 토큰 요약 → `@knowledge/rejections/summary.md`.

PR-B (Layer 2 by-section), PR-C (Layer 3 RAG)는 후속.

## 빌드

```bash
cd tools/rejections-indexer
uv sync --no-dev
uv run python -m rejections_indexer summarize
```

또는 프로젝트 루트:
```bash
make build-rejections-summary    # PR-A summary
make build-rejections            # 전체 (현재 = summary만)
```

## 정책

- ANTHROPIC_KEY는 AWS Secrets Manager `llm-providers/prod/personal`에서 IAM Role로 자동 로드.
- 입력은 `@knowledge/drafting/raw/` (KIPO 심사기준 추출본, KOGL 2.0).
- 결과 summary.md는 보조 가이드 — 법적 효력은 원본 KIPO 자료에.
