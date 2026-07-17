"""@knowledge/ 의 static text loader — P2 Director / P5 Crafter 의 system_prompt
에 KIPO 심사기준 가이드를 정적 inject 하기 위한 thin module.

`inject_knowledge` key (pipeline JSON) → 본 모듈의 함수 → text 반환.
claude.py 의 `_resolve_knowledge_prefix` 가 호출.

(구 shared/venezia_pipeline/knowledge_loader.py 의 일부 — IPC/CPC tree /
knowledge_service_handler 등 dead 기능은 폐기.)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


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


def _load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"@knowledge asset missing: {path}")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_drafting_summary() -> str:
    """KIPO 명세서 작성 가이드 LLM 요약본 (~10K 토큰). director system_prompt 에 정적 주입."""
    return _load_text(_find_knowledge_root() / "drafting" / "summary.md")


@lru_cache(maxsize=8)
def load_drafting_raw(part: str) -> str:
    """KIPO 명세서 작성 가이드 원본 추출본 — 한 Part (`01`~`07`)."""
    return _load_text(_find_knowledge_root() / "drafting" / "raw" / f"exammanual_{part}.md")


@lru_cache(maxsize=1)
def load_rejections_summary() -> str:
    """KIPO 거절사유 가이드 LLM 요약본 (~10K 토큰). director system_prompt 에 정적 주입."""
    return _load_text(_find_knowledge_root() / "rejections" / "summary.md")
