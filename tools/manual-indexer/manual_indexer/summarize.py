"""1-shot Claude summarization: raw/* → summary.md.

ANTHROPIC_API_KEY 는 shared/venezia_secrets 가 AWS Secret 에서 env 로 자동 주입.
host 실행 시 AWS_SECRET_NAME env 가 `llm-providers/prod/personal` 포함하도록 set.
"""

from __future__ import annotations

import datetime as dt

import structlog
from anthropic import Anthropic

import shared.venezia_secrets  # noqa: F401  side-effect: AWS Secret → env

from .paths import PART_TITLES, PARTS, RAW_ROOT, SUMMARY_PATH

log = structlog.get_logger()

MODEL = "claude-opus-4-7"
MAX_OUTPUT_TOKENS = 16000

SYSTEM_PROMPT = (
    "당신은 KIPO 「특허·실용신안 심사기준」을 한국어 특허 명세서 작성·검토용 "
    "핵심 가이드로 압축하는 전문가입니다. 결과는 director(자동 명세서 작성 LLM)가 "
    "system_prompt에 항상 주입할 정적 가이드로 사용됩니다. "
    "법적 정확성과 압축 효율을 동시에 추구합니다."
)

USER_INSTRUCTION = """\
아래는 KIPO 심사기준 7개 Part의 원본 텍스트입니다. 이 자료를 director가 명세서를
채울 때 항상 참고할 수 있는 **약 5-10K 토큰의 핵심 가이드**로 요약하세요.

## 요청 형식

- 한국어 markdown
- frontmatter는 추가하지 말 것 (별도로 빌더가 붙임)
- 섹션 구성:
  1. **명세서 일반 작성 규칙** — 발명의 명칭·기술분야·배경기술·발명의 내용(과제·해결수단·효과)·도면의 간단한 설명·발명을 실시하기 위한 구체적인 내용
  2. **청구항 작성·해석** — 독립항·종속항 구조, 카테고리(물건·방법·장치), 권리 범위 표현, 다중 종속 제한
  3. **명세서 기재요건 (특법 §42)** — 발명의 상세한 설명 기재 정도, 청구범위 명확성·간결성, 뒷받침 요건
  4. **신규성·진보성 (특법 §29)** — 판단 기준, 비교 대상, 거절되는 전형 패턴
  5. **자주 거절되는 패턴** — 사례 위주 (모호한 용어, 카테고리 불명확, 효과 미기재, 청구항·명세서 불일치 등)
  6. **보정 시 유의사항** — 신규사항 추가 금지, 보정 가능 시기·범위
  7. **도면·요약서 요건** — 도면 종류, 부호 기재, 요약서 분량 (400자 이내)

## 압축 원칙

- 법조문(특법 §29, §42, §47 등) 인용은 정확히 보존
- "예:", "예시:" 같은 구체 사례는 1-2개만 (장황하지 않게)
- 행정 절차(심사 단계·기간·서식·수수료), 특수한 출원(분할·변경·우선권), PCT, 거절결정 후 절차 등은 **생략**
- 표·복잡한 도식 대신 짧은 문장 또는 bullet
- 동어 반복 제거

## 원본 자료

"""


def _build_raw_concat() -> str:
    chunks: list[str] = []
    for part in PARTS:
        path = RAW_ROOT / f"exammanual_{part}.md"
        if not path.exists():
            raise FileNotFoundError(f"missing raw extract: {path}")
        chunks.append(f"\n\n## ===== Part {part} — {PART_TITLES[part]} =====\n\n")
        chunks.append(path.read_text(encoding="utf-8"))
    return "".join(chunks)


def run() -> int:
    raw_concat = _build_raw_concat()
    raw_chars = len(raw_concat)
    log.info(
        "summarize.start",
        model=MODEL,
        raw_chars=raw_chars,
        est_input_tokens=raw_chars // 4,
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
        log.error("summarize.empty_response")
        return 1

    usage = resp.usage
    log.info(
        "summarize.done",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        summary_chars=len(summary_body),
    )

    frontmatter = (
        "---\n"
        f'source: "KIPO 심사기준 7-Part summary"\n'
        f'license: "KOGL 2.0"\n'
        f'model: "{MODEL}"\n'
        f"input_tokens: {usage.input_tokens}\n"
        f"output_tokens: {usage.output_tokens}\n"
        f'built_at: "{dt.datetime.now(dt.UTC).isoformat()}"\n'
        "---\n\n"
        "# KIPO 심사기준 — 명세서 작성 핵심 가이드 (요약)\n\n"
        "> 이 문서는 KIPO 「특허·실용신안 심사기준」 7개 Part를 director "
        "(자동 명세서 작성 LLM)에 주입할 수 있는 형태로 1회성 요약한 산출물입니다. "
        "법적 효력은 원본 KIPO 심사기준에 있으며, 이 요약본은 보조 가이드입니다.\n\n"
    )

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(frontmatter + summary_body + "\n", encoding="utf-8")
    log.info("summarize.write", path=str(SUMMARY_PATH))
    return 0
