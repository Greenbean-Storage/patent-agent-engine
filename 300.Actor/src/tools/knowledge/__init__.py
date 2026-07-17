"""Knowledge tool domain — @knowledge/ 의 static 자료를 동적 로드 (DRO tool step).

llm/knowledge.py (LLM prompt inject 용 static loader) 와 별개:
이 쪽은 DRO tool step 으로 호출되어 user message 에 동적 결합되는 자료.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import register

log = logging.getLogger(__name__)


def _find_knowledge_root() -> Path:
    env = os.environ.get("KNOWLEDGE_DIR")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for parent in (start, *start.parents):
            candidate = parent / "@knowledge"
            if candidate.is_dir():
                return candidate
    raise FileNotFoundError(
        "@knowledge directory not found. Set KNOWLEDGE_DIR env or place "
        "@knowledge/ in a parent of cwd."
    )


_IPC_SECTION_RE = re.compile(r"^([A-H])")


def _section_from_ipc(ipc_codes: Any) -> str | None:
    """IPC code list/string 에서 첫 Section letter (A-H) 추출.

    예: ['A61K 9/00', 'A23L 33/00'] → 'A', 'B05D 1/00' → 'B', None → None.
    여러 IPC 가 다른 Section 이면 첫 번째 우선 (P02.R10 의 director 가 IPC 우선순위로 정렬).
    """
    if not ipc_codes:
        return None
    if isinstance(ipc_codes, str):
        candidates = [ipc_codes]
    elif isinstance(ipc_codes, list):
        candidates = [c for c in ipc_codes if isinstance(c, str)]
    else:
        return None
    for c in candidates:
        m = _IPC_SECTION_RE.match(c.strip())
        if m:
            return m.group(1)
    return None


@lru_cache(maxsize=16)
def _load_section_md(section: str) -> str:
    """`@knowledge/rejections/by-section/{section}.md` 의 본문 (frontmatter 제외) 로드."""
    root = _find_knowledge_root()
    f = root / "rejections" / "by-section" / f"{section}.md"
    if not f.exists():
        raise FileNotFoundError(f"section guide missing: {f}")
    raw = f.read_text(encoding="utf-8")
    # frontmatter (--- ... ---) 제거
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end != -1:
            raw = raw[end + 3 :].lstrip("\n")
    return raw


@register("knowledge.load_rejections_section")
async def load_rejections_section(ipc_codes: Any = None) -> dict[str, Any]:
    """IPC Section (A-H) 기준 거절 패턴 가이드 로드.

    output (load_rejections_section-output schema):
      section: { letter, title, text } | null  (분류 미정이면 null)
    """
    section_letter = _section_from_ipc(ipc_codes)
    if section_letter is None:
        return {"section": {"letter": None, "title": None, "text": None}}
    try:
        text = _load_section_md(section_letter)
    except FileNotFoundError as e:
        log.warning("knowledge.load_rejections_section file missing: %s", e)
        return {"section": {"letter": section_letter, "title": None, "text": None}}
    # 첫 번째 `### Section X — TITLE` 또는 `## Section X — TITLE` 에서 title 추출
    title = None
    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s*Section\s+[A-H]\s*[—\-]\s*(.+)$", line.strip())
        if m:
            title = m.group(1).strip()
            break
    return {
        "section": {
            "letter": section_letter,
            "title": title,
            "text": text,
        }
    }
