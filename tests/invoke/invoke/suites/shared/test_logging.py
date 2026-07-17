"""venezia_logging — setup_logging(console/json/file) + get_logger."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))

from venezia_logging import get_logger, setup_logging  # noqa: E402


def test_setup_logging_console():
    setup_logging()
    get_logger("test").info("hello console")
    assert logging.getLogger().handlers  # console handler 등록


def test_setup_logging_json():
    setup_logging(json_output=True)
    get_logger().info("hello json")


def test_setup_logging_file(tmp_path):
    setup_logging(log_dir=str(tmp_path / "logs"))
    get_logger("file").info("hello file")
    assert (tmp_path / "logs" / "app.log").exists()
