"""Path constants for rejections-indexer."""

from __future__ import annotations

from pathlib import Path

INDEXER_ROOT = Path(__file__).resolve().parent.parent  # tools/rejections-indexer/
REPO_ROOT = INDEXER_ROOT.parent.parent  # engine-prototype/

KNOWLEDGE_ROOT = REPO_ROOT / "@knowledge"
REJECTIONS_ROOT = KNOWLEDGE_ROOT / "rejections"
SUMMARY_PATH = REJECTIONS_ROOT / "summary.md"
VERSION_PATH = REJECTIONS_ROOT / "version.json"
README_PATH = REJECTIONS_ROOT / "README.md"
BY_SECTION_ROOT = REJECTIONS_ROOT / "by-section"

# Input raw — produced by manual-indexer for the drafting domain.
DRAFTING_RAW_ROOT = KNOWLEDGE_ROOT / "drafting" / "raw"

# Classification tree — produced by classification-indexer.
CLASSIFICATION_ROOT = KNOWLEDGE_ROOT / "classification"
IPC_TREE_PATH = CLASSIFICATION_ROOT / "ipc" / "tree.json"

# We pull from these parts (general·patentability·specification — where rejection
# triggers are concentrated). Procedural/special-application parts are skipped to
# keep the input lean and the summary focused.
INPUT_PARTS = ["01", "03", "04"]

# IPC Sections — fixed list, ordered.
SECTIONS = ["A", "B", "C", "D", "E", "F", "G", "H"]
SECTION_TITLES = {
    "A": "생활필수품 (HUMAN NECESSITIES)",
    "B": "처리·운송 (PERFORMING OPERATIONS; TRANSPORTING)",
    "C": "화학·야금 (CHEMISTRY; METALLURGY)",
    "D": "섬유·종이 (TEXTILES; PAPER)",
    "E": "고정 구조물 (FIXED CONSTRUCTIONS)",
    "F": "기계공학·조명·난방·무기·폭파 (MECHANICAL ENGINEERING; LIGHTING; HEATING; WEAPONS; BLASTING)",
    "G": "물리학 (PHYSICS)",
    "H": "전기 (ELECTRICITY)",
}
