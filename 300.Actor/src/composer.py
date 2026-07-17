"""
composer — RT spec 을 받아 inject_context 자원 fetch + prompt 합성.

Actor 전용 모듈 (구 shared/venezia_pipeline_runtime 에서 흡수 — 제품 소비자가
300.Actor/src/dispatcher.py 단독, Actor 재설계 A5·C-3).

prompt 합성 결과는 단일 텍스트 (사용자: "AI 가 layer 구조 왜 알아야 — 다 합쳐서").
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

KNOWLEDGE_PREFIX = "@knowledge/"
CM_PREFIX = "cm://"
PIPELINES_PREFIX = "@pipelines/"

INSTRUCTIONS_ALLOWED_KEYS = frozenset({"inline", "reference"})

# CM fetch 콜백 시그니처: (resource_path) -> dict | str | None
CmFetcher = Callable[[str], Awaitable[Any]]


class ComposerError(Exception):
    """prompt 합성 실패."""


def _resolve_knowledge(source: str, knowledge_root: Path) -> str:
    """@knowledge/personas/finder_kipris.md → 파일 내용 읽기."""
    rel = source[len(KNOWLEDGE_PREFIX) :]
    path = knowledge_root / rel
    if not path.exists():
        raise ComposerError(f"@knowledge 파일 없음: {path}")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=256)
def _read_instructions_file(path_str: str) -> str:
    """@pipelines/.../*.md 파일 read + cache (Actor 재시작 시까지)."""
    return Path(path_str).read_text(encoding="utf-8")


def _resolve_instructions_reference(source: str, pipelines_root: Path) -> str:
    """instructions.reference 값 → 텍스트. 현재 @pipelines/ prefix 만 지원."""
    if source.startswith(PIPELINES_PREFIX):
        rel = source[len(PIPELINES_PREFIX) :]
        path = pipelines_root / rel
        if not path.exists():
            raise ComposerError(f"@pipelines instruction 파일 없음: {path}")
        return _read_instructions_file(str(path))
    raise ComposerError(
        f"instructions.reference 의 알 수 없는 prefix: {source} (현재 '@pipelines/' 만 지원)"
    )


def _resolve_instructions(instructions: Any, pipelines_root: Path) -> str | None:
    """`instructions` 값 (객체) → 최종 텍스트.

    {inline: "..."} 또는 {reference: "@pipelines/.../*.md"} 객체. 정확히 1개 키.
    None / 빈 값이면 None 반환. legacy (list[str], string) 는 fail-loud.
    """
    if instructions is None:
        return None
    if not isinstance(instructions, dict):
        raise ComposerError(
            f"instructions 는 객체여야 함 ({{inline: ...}} 또는 {{reference: ...}}). "
            f"got: {type(instructions).__name__} ({instructions!r})"
        )
    keys = set(instructions.keys())
    if not keys:
        return None
    extra = keys - INSTRUCTIONS_ALLOWED_KEYS
    if extra:
        raise ComposerError(
            f"instructions 의 허용 키는 {sorted(INSTRUCTIONS_ALLOWED_KEYS)} 뿐. "
            f"알 수 없는 키: {sorted(extra)}"
        )
    if len(keys) != 1:
        raise ComposerError(
            f"instructions 객체 안에 키가 정확히 1개여야 함 (inline XOR reference). "
            f"got: {sorted(keys)}"
        )
    if "inline" in instructions:
        value = instructions["inline"]
        if not isinstance(value, str):
            raise ComposerError(
                f"instructions.inline 은 string 이어야 함. got: {type(value).__name__}"
            )
        return value
    # reference
    value = instructions["reference"]
    if not isinstance(value, str):
        raise ComposerError(
            f"instructions.reference 는 string 이어야 함. got: {type(value).__name__}"
        )
    return _resolve_instructions_reference(value, pipelines_root)


async def _resolve_cm(source: str, cm_fetch: CmFetcher | None) -> Any:
    """cm://invention_object_model[.dot.path] → CM 호출."""
    if cm_fetch is None:
        raise ComposerError("cm:// 자원 fetch 불가 (cm_fetch 콜백 미제공)")
    rel = source[len(CM_PREFIX) :]
    return await cm_fetch(rel)


async def _fetch_source(source: str, knowledge_root: Path, cm_fetch: CmFetcher | None) -> Any:
    if source.startswith(KNOWLEDGE_PREFIX):
        return _resolve_knowledge(source, knowledge_root)
    if source.startswith(CM_PREFIX):
        return await _resolve_cm(source, cm_fetch)
    raise ComposerError(f"알 수 없는 source prefix: {source} (@knowledge/ 또는 cm://)")


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


async def compose_prompt(
    *,
    persona_prompt: str,
    inject_context: dict[str, str],
    recommended_context: dict[str, str],
    fragments: dict[str, str],
    instructions: dict[str, str] | None,
    dispatch_choice_guide: dict[int, str] | None,
    knowledge_root: Path,
    pipelines_root: Path,
    cm_fetch: CmFetcher | None,
) -> str:
    """RT spec 을 단일 prompt 텍스트로 합성.

    구조: [PERSONA] + [CONTEXT] + [FRAGMENTS] + [TASK] + [DISPATCH_CHOICE_GUIDE]
    + [RECOMMENDED_FETCH]
    layer 구분 X (사용자 결정).
    """
    parts: list[str] = []

    if persona_prompt:
        parts.append("[PERSONA]\n" + persona_prompt.strip())

    # 강제 inject — 자원 fetch 후 prompt 에 inline
    if inject_context:
        inject_lines = ["[CONTEXT]"]
        for name, source in inject_context.items():
            try:
                value = await _fetch_source(source, knowledge_root, cm_fetch)
                inject_lines.append(f"## {name}\n{_stringify(value).strip()}")
            except ComposerError as e:
                inject_lines.append(f"## {name}\n(fetch 실패: {e})")
        parts.append("\n\n".join(inject_lines))

    # 재사용 prose 조각 — 이름 → 내용 그대로 inline
    if fragments:
        frag_lines = ["[FRAGMENTS]"]
        for name, text in fragments.items():
            frag_lines.append(f"## {name}\n{text.strip()}")
        parts.append("\n\n".join(frag_lines))

    instructions_text = _resolve_instructions(instructions, pipelines_root)
    if instructions_text:
        parts.append("[TASK]\n" + instructions_text.strip())

    if dispatch_choice_guide:
        guide_lines = [
            "[DISPATCH_CHOICE_GUIDE]",
            "마지막 step 출력에 dispatch_choice (정수) 를 반드시 포함. 의미:",
        ]
        for idx, meaning in sorted(dispatch_choice_guide.items()):
            guide_lines.append(f"- {idx}: {meaning}")
        parts.append("\n".join(guide_lines))

    # 추천 fetch — LLM 한테 hint 만 (자원 fetch 안 함)
    if recommended_context:
        rec_lines = ["[RECOMMENDED_FETCH]", "필요 시 fetch 도구로 가져와 참고할 자원:"]
        for name, source in recommended_context.items():
            rec_lines.append(f"- {name}: {source}")
        parts.append("\n".join(rec_lines))

    return "\n\n".join(parts)
