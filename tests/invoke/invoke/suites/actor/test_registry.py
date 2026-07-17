"""300.Actor tools registry — list_available (auto-register on import).

구 llm.factory(create_actor_session/PERSONA_TO_*) 박제는 engine.config 도입으로 폐기 —
persona→모델 매핑 검증은 test_engine_config.py, 세션 생성은 test_llm_init.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src import tools  # noqa: E402


def test_tool_registry_list_available():
    avail = tools.list_available()
    assert isinstance(avail, list)
    assert avail == sorted(tools.TOOLS.keys())
    assert len(avail) > 0  # auto-register on import
