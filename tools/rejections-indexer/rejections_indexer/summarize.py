"""1-shot Claude summarization: drafting/raw/* → @knowledge/rejections/summary.md.

ANTHROPIC_API_KEY 는 shared/venezia_secrets 가 AWS Secret 에서 env 로 자동 주입.
host 실행 시 AWS_SECRET_NAME env 가 `llm-providers/prod/personal` 포함하도록 set.
"""

from __future__ import annotations

import datetime as dt
import json

import structlog
from anthropic import Anthropic

import shared.venezia_secrets  # noqa: F401  side-effect: AWS Secret → env

from .paths import DRAFTING_RAW_ROOT, INPUT_PARTS, SUMMARY_PATH

log = structlog.get_logger()

MODEL = "claude-opus-4-7"
MAX_OUTPUT_TOKENS = 16000

SYSTEM_PROMPT = (
    "당신은 한국 특허청(KIPO) 「특허·실용신안 심사기준」을 분석해 "
    "특허 출원 거절사유 패턴을 추출·체계화하는 전문가입니다. "
    "결과는 director(자동 명세서 작성·검토 LLM)가 system_prompt에 항상 주입할 "
    "거절 회피 가이드로 사용됩니다."
)

USER_INSTRUCTION = """\
아래는 KIPO 심사기준의 일부입니다 (Part 01 총칙 / Part 03 특허요건 / Part 04 명세서·청구범위).
이 자료를 director가 명세서를 작성·검토할 때 항상 참조할 수 있는 **약 5-10K 토큰의
거절사유 회피 가이드**로 압축하세요.

## 요청 형식

- 한국어 markdown
- frontmatter는 추가하지 말 것 (별도로 빌더가 붙임)
- 7-10개 핵심 거절사유 카테고리 위주로 구성
- 각 카테고리:
  - **법적 근거** (특법 §29①, §29②, §42③, §42④ 등 정확히 인용)
  - **거절 패턴**: 어떤 명세서·청구항 작성이 이 거절을 유발하는가 (구체)
  - **회피 가이드**: 명세서·청구항 작성 시 이 거절을 피하려면 무엇을 해야 하는가 (체크리스트 또는 짧은 규칙)
  - **사례** (선택): 1줄 짧은 예시 또는 반례

## 후보 카테고리 (조사 결과 기준)

1. **신규성 부재** (특법 §29①) — 국내외 공지·공연실시·간행물 게재
2. **진보성 부재** (특법 §29②) — 선행기술 조합으로 당업자 용이 도출
3. **기재불비** (특법 §42③ 제1호) — 발명의 상세한 설명 실시가능 요건 위반
4. **청구범위 명확성 위반** (특법 §42④ 제2호) — 용어 모호, 범위 불명확
5. **청구범위 뒷받침 위반** (특법 §42④ 제1호) — 상세한 설명에 의해 뒷받침 안 됨
6. **산업상 이용가능성 부재** (특법 §29 본문) — 자연법칙·발견·비산업
7. **확대된 선원** (특법 §29③) — 선출원 명세서에 동일 발명 기재
8. **선원** (특법 §36) — 동일자 출원·복수출원 충돌
9. **명세서·청구범위 불일치** — 청구된 범위가 상세한 설명과 다름
10. **보정 시 신규사항 추가** (특법 §47②) — 출원 후 새 사항 추가

위 후보를 핵심 7-10개로 정리. 너무 자잘한 절차적 거절(서식·수수료 등)은 제외.

## 압축 원칙

- 법조문은 정확히 ("특법 §42④ 제2호" 같이)
- "예:" 사례는 1-2줄만
- 당업자 관점·통상의 기술자 같은 핵심 용어는 보존
- 마지막에 **체크리스트** 섹션 추가 (명세서 제출 직전 self-check 용도, 10개 내외 bullet)

## 원본 자료

"""


def _build_input() -> str:
    chunks: list[str] = []
    for part in INPUT_PARTS:
        path = DRAFTING_RAW_ROOT / f"exammanual_{part}.md"
        if not path.exists():
            raise FileNotFoundError(
                f"missing drafting raw extract: {path}. Run `make build-drafting-raw` first."
            )
        chunks.append(f"\n\n## ===== Part {part} =====\n\n")
        chunks.append(path.read_text(encoding="utf-8"))
    return "".join(chunks)


def run() -> int:
    raw_concat = _build_input()
    raw_chars = len(raw_concat)
    log.info(
        "rejections.summarize.start",
        model=MODEL,
        raw_chars=raw_chars,
        est_input_tokens=raw_chars // 4,
        parts=INPUT_PARTS,
    )

    client = Anthropic()  # ENV (ANTHROPIC_API_KEY) 자동
    user_message = USER_INSTRUCTION + raw_concat
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    summary_body = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )
    if not summary_body.strip():
        log.error("rejections.summarize.empty_response")
        return 1

    usage = resp.usage
    log.info(
        "rejections.summarize.done",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        summary_chars=len(summary_body),
    )

    frontmatter = (
        "---\n"
        f'source: "KIPO 심사기준 Part {",".join(INPUT_PARTS)} → 거절사유 요약"\n'
        f'license: "KOGL 2.0"\n'
        f'model: "{MODEL}"\n'
        f"input_tokens: {usage.input_tokens}\n"
        f"output_tokens: {usage.output_tokens}\n"
        f'built_at: "{dt.datetime.now(dt.UTC).isoformat()}"\n'
        "---\n\n"
        "# KIPO 심사기준 — 출원 거절사유 핵심 가이드 (요약)\n\n"
        "> 이 문서는 KIPO 「특허·실용신안 심사기준」(Part 01 총칙 / Part 03 특허요건 / "
        "Part 04 명세서·청구범위)을 거절사유 회피 관점에서 1회성 압축한 산출물입니다. "
        "법적 효력은 원본 KIPO 심사기준에 있으며, 이 요약본은 보조 가이드입니다.\n\n"
    )

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(frontmatter + summary_body + "\n", encoding="utf-8")
    log.info("rejections.summarize.write", path=str(SUMMARY_PATH))

    from .paths import VERSION_PATH

    version_payload = {
        "schema_version": "1.0.0",
        "source": "KIPO 심사기준 (drafting/raw → 거절사유 요약)",
        "license": "KOGL 2.0",
        "input_parts": INPUT_PARTS,
        "model": MODEL,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "summary_chars": len(summary_body),
        "built_at": dt.datetime.now(dt.UTC).isoformat(),
        "layer": "1",
        "next_layers": ["2:by-section (PR-B)", "3:RAG cases (PR-C)"],
    }
    VERSION_PATH.write_text(
        json.dumps(version_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log.info("rejections.summarize.version", path=str(VERSION_PATH))
    return 0
