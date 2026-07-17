"""Path constants. Resolves project root from the indexer location."""

from __future__ import annotations

from pathlib import Path

INDEXER_ROOT = Path(__file__).resolve().parent.parent  # tools/classification-indexer/
REPO_ROOT = INDEXER_ROOT.parent.parent  # engine-prototype/

KNOWLEDGE_ROOT = REPO_ROOT / "@knowledge"
CLASSIFICATION_ROOT = KNOWLEDGE_ROOT / "classification"
IPC_ROOT = CLASSIFICATION_ROOT / "ipc"
CPC_ROOT = CLASSIFICATION_ROOT / "cpc"

CACHE_DIR = INDEXER_ROOT / ".cache"
