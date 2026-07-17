"""mock 설정 — env 단일점. shared(venezia_*) 미포함 (mock 이미지 = minimal)."""

from __future__ import annotations

import os

TAPE_DIR = os.getenv("TAPE_DIR", "/app/data/dro-tapes")  # compose 가 tests/data/dro-tapes ro mount
