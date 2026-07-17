"""Path constants for manual-indexer."""

from __future__ import annotations

from pathlib import Path

INDEXER_ROOT = Path(__file__).resolve().parent.parent  # tools/manual-indexer/
REPO_ROOT = INDEXER_ROOT.parent.parent  # engine-prototype/

KNOWLEDGE_ROOT = REPO_ROOT / "@knowledge"
DRAFTING_ROOT = KNOWLEDGE_ROOT / "drafting"
RAW_ROOT = DRAFTING_ROOT / "raw"
SUMMARY_PATH = DRAFTING_ROOT / "summary.md"
VERSION_PATH = DRAFTING_ROOT / "version.json"
README_PATH = DRAFTING_ROOT / "README.md"

CACHE_DIR = INDEXER_ROOT / ".cache"

PARTS = ["01", "02", "03", "04", "05", "06", "07"]
PART_TITLES = {
    "01": "총칙",
    "02": "특허출원",
    "03": "특허요건",
    "04": "명세서 등의 보정 + 청구범위 작성",
    "05": "심사절차",
    "06": "특수한 출원",
    "07": "기타",
}
