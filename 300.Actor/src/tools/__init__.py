"""Actor 공유 tool registry. 페르소나 무관 — RT.available_tools 가 결정."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Tool handler signature: (args: dict) -> dict (sync or async)
TOOLS: dict[str, Callable[..., Any]] = {}


def register(name: str):
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        TOOLS[name] = fn
        return fn

    return decorator


def get(name: str) -> Callable[..., Any] | None:
    return TOOLS.get(name)


def list_available() -> list[str]:
    return sorted(TOOLS.keys())


# Auto-register on import
from . import (
    cm,  # noqa: E402, F401
    document,  # noqa: E402, F401
    drawing,  # noqa: E402, F401
    kipris,  # noqa: E402, F401
    knowledge,  # noqa: E402, F401
    maturity,  # noqa: E402, F401
    media,  # noqa: E402, F401
    roadmap,  # noqa: E402, F401
    staging,  # noqa: E402, F401
    vision,  # noqa: E402, F401
)
