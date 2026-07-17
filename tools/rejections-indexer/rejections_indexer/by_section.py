"""Layer 2 — IPC Section별 거절사유 특이 가이드 생성 (PR-B).

전략: drafting summary + rejections summary + IPC 분류 트리(@knowledge/classification/ipc/tree.json)
를 한 번에 입력으로 Claude Opus 4.7 호출 → 8 Section 통합 markdown 생성. 결과를
H1 `## Section X` 헤더로 split하여 by-section/{A..H}.md 8 파일에 저장.

이렇게 1회성 단일 호출 — 비용/일관성 좋음 (8회 따로 호출하면 Section 간 균형 ↓).
"""

from __future__ import annotations

import datetime as dt
import json
import re

import structlog
from anthropic import Anthropic

import shared.venezia_secrets  # noqa: F401  side-effect: AWS Secret → env

from .paths import (
    BY_SECTION_ROOT,
    DRAFTING_RAW_ROOT,
    IPC_TREE_PATH,
    SECTION_TITLES,
    SECTIONS,
    SUMMARY_PATH,
)

log = structlog.get_logger()

MODEL = "claude-opus-4-7"
MAX_OUTPUT_TOKENS = 24000

SYSTEM_PROMPT = (
    "당신은 한국 특허청(KIPO) 「특허·실용신안 심사기준」 전문가로, IPC 분류 8개 "
    "Section별로 빈번한 거절사유 패턴과 그 분야의 특이 회피 가이드를 작성합니다. "
    "각 Section은 기술 분야가 다르므로 공통 거절사유(신규성·진보성 등)도 그 Section의 "
    "기술적 맥락에서 어떻게 발현되고 회피해야 하는지 분야 맞춤형으로 작성합니다. "
    "결과는 director(자동 명세서 작성·검토 LLM)가 분류 코드가 정해진 후 그 Section "
    "가이드를 동적으로 주입하는 자료로 사용됩니다."
)

USER_INSTRUCTION_TEMPLATE = """\
아래 자료를 종합해 IPC **8개 Section(A-H)별 거절사유 특이 가이드**를 한 번에 작성하세요.

## 출력 형식 (정확히 준수)

각 Section마다 다음 구조의 markdown:

```
## Section A — 생활필수품 (HUMAN NECESSITIES)

### Section 개요
- 이 Section의 주요 기술 분야와 거절 패턴 1-2 문단

### 1. [거절사유 카테고리 1] (특법 §...)
- **이 Section 특이 패턴**: 일반 가이드 외에 이 Section에서 자주 거절되는 특이 사례
- **회피 가이드**: 이 분야 명세서 작성 시 체크포인트

### 2. [거절사유 카테고리 2] (특법 §...)
...

### 분야별 체크리스트
- 이 Section 명세서 제출 직전 self-check 5-7개 bullet
```

## 작성 원칙

- 8 Section 모두 동일 구조로 작성 (분량 균형: 각 ~1500-2500 토큰)
- **반드시 `## Section X — ...` 형태의 H2 헤더로 시작** (split 자동화 위해)
- Section 순서: A → B → C → D → E → F → G → H
- 일반 거절사유(전체 공통)는 짧게 다루고, 그 Section **특이 패턴** 위주
- 법조문은 정확히 (특법 §29①, §42④제2호 등)
- 화학/생명(C,A23) vs 전기(H) vs 기계(F,B) vs SW알고리즘(G06) 등 분야 차이 반영

## 주요 거절사유 카테고리 (참조용 — 각 Section별로 그 분야 특이 패턴만 다룸)

1. 신규성 부재 (특법 §29①)
2. 진보성 부재 (특법 §29②)
3. 기재불비 — 실시가능 (특법 §42③제1호)
4. 청구범위 명확성 (특법 §42④제2호)
5. 청구범위 뒷받침 (특법 §42④제1호)
6. 산업상 이용가능성 (특법 §29 본문)
7. 보정 시 신규사항 추가 (특법 §47②)

## 자료 1 — 거절사유 핵심 가이드 (이미 만든 summary.md)

{rejections_summary}

## 자료 2 — IPC 분류 트리 (Section→Subclass 메타 + 한국어 라벨)

{ipc_tree_compact}

## 자료 3 — KIPO 심사기준 원본 일부 (보조)

{drafting_raw_excerpt}

각 Section에 어떤 기술 분야가 들어가는지(자료 2)와 그 분야 거절 패턴을 매칭해
H2 헤더 시작으로 8 Section 가이드를 작성하세요.
"""


def _build_ipc_tree_compact() -> str:
    """Section + Class 레벨 한·영 라벨만 추출 (Subclass 생략)."""
    if not IPC_TREE_PATH.exists():
        raise FileNotFoundError(
            f"IPC tree not found: {IPC_TREE_PATH}. Run `make build-classification` first."
        )
    tree = json.loads(IPC_TREE_PATH.read_text(encoding="utf-8"))
    lines: list[str] = []
    for section in tree.get("sections", []):
        s_code = section["code"]
        s_title = section.get("title", {})
        lines.append(
            f"\n### Section {s_code} — {s_title.get('ko', '')} / {s_title.get('en', '')}"
        )
        for cls in section.get("classes", []):
            c_code = cls["code"]
            c_title = cls.get("title", {})
            ko = (c_title.get("ko") or "").strip()
            en = (c_title.get("en") or "").strip()[:80]
            lines.append(f"- **{c_code}** {ko}  /  {en}")
    return "\n".join(lines)


def _build_drafting_excerpt(max_chars: int = 30000) -> str:
    """Part 03·04 합본 일부 (rejection-relevant)."""
    chunks: list[str] = []
    for part in ["03", "04"]:
        path = DRAFTING_RAW_ROOT / f"exammanual_{part}.md"
        if path.exists():
            chunks.append(f"\n\n## ===== Part {part} =====\n\n")
            chunks.append(path.read_text(encoding="utf-8"))
    text = "".join(chunks)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n... [truncated for token budget]"
    return text


def _split_by_section(markdown: str) -> dict[str, str]:
    """`## Section X — ...` H2 기준으로 8 Section 분할."""
    pattern = re.compile(r"^## Section ([A-H])\b", re.MULTILINE)
    matches = list(pattern.finditer(markdown))
    if not matches:
        log.warning("by_section.split.no_h2_match")
        return {}

    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        section = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        out[section] = markdown[start:end].rstrip() + "\n"
    return out


def run() -> int:
    if not SUMMARY_PATH.exists():
        log.error(
            "by_section.no_summary",
            path=str(SUMMARY_PATH),
            hint="Run `make build-rejections-summary` first",
        )
        return 1

    rejections_summary = SUMMARY_PATH.read_text(encoding="utf-8")
    ipc_tree_compact = _build_ipc_tree_compact()
    drafting_raw_excerpt = _build_drafting_excerpt()

    user_message = USER_INSTRUCTION_TEMPLATE.format(
        rejections_summary=rejections_summary,
        ipc_tree_compact=ipc_tree_compact,
        drafting_raw_excerpt=drafting_raw_excerpt,
    )
    log.info("by_section.start", model=MODEL, user_chars=len(user_message))

    client = Anthropic()  # ENV (ANTHROPIC_API_KEY) 자동
    text_parts: list[str] = []
    final_msg = None
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for chunk in stream.text_stream:
            text_parts.append(chunk)
        final_msg = stream.get_final_message()

    body = "".join(text_parts)
    if not body.strip():
        log.error("by_section.empty_response")
        return 1

    usage = final_msg.usage
    log.info(
        "by_section.done",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        body_chars=len(body),
    )

    splits = _split_by_section(body)
    missing = [s for s in SECTIONS if s not in splits]
    if missing:
        log.warning("by_section.split.missing", sections=missing)

    BY_SECTION_ROOT.mkdir(parents=True, exist_ok=True)
    built_at = dt.datetime.now(dt.UTC).isoformat()
    for section in SECTIONS:
        if section not in splits:
            continue
        title = SECTION_TITLES[section]
        frontmatter = (
            "---\n"
            f'source: "KIPO 심사기준 + 분류 트리 → Section {section} 거절사유 가이드"\n'
            f'license: "KOGL 2.0"\n'
            f'model: "{MODEL}"\n'
            f'section: "{section}"\n'
            f'section_title: "{title}"\n'
            f'built_at: "{built_at}"\n'
            "---\n\n"
        )
        path = BY_SECTION_ROOT / f"{section}.md"
        path.write_text(frontmatter + splits[section], encoding="utf-8")
        log.info(
            "by_section.write",
            section=section,
            path=str(path),
            chars=len(splits[section]),
        )

    return 0
