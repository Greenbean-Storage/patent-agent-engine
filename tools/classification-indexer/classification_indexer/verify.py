"""Verify built @knowledge/classification/ — node counts, schema, dangling refs."""

from __future__ import annotations

import json

import structlog

from .paths import CLASSIFICATION_ROOT, IPC_ROOT

log = structlog.get_logger()

# WIPO IPC official counts (sanity check)
# Counts grow over time as new technology areas are added; thresholds are
# tolerant lower bounds to catch gross parsing errors, not exact equality.
EXPECTED_IPC_SECTIONS = 8
MIN_IPC_CLASSES = 125
MIN_IPC_SUBCLASSES = 645


def verify_ipc_tree(tree: dict) -> list[str]:
    """Return list of error messages (empty = OK)."""
    errors: list[str] = []
    sections = tree.get("sections", [])
    if len(sections) != EXPECTED_IPC_SECTIONS:
        errors.append(f"section count {len(sections)} != {EXPECTED_IPC_SECTIONS}")
    n_classes = sum(len(s.get("classes", [])) for s in sections)
    if n_classes < MIN_IPC_CLASSES:
        errors.append(
            f"class count {n_classes} < {MIN_IPC_CLASSES} (likely parsing error)"
        )
    n_subclasses = sum(
        len(c.get("subclasses", [])) for s in sections for c in s.get("classes", [])
    )
    if n_subclasses < MIN_IPC_SUBCLASSES:
        errors.append(
            f"subclass count {n_subclasses} < {MIN_IPC_SUBCLASSES} (likely parsing error)"
        )
    return errors


def verify_ko_coverage(tree: dict) -> dict:
    """Compute Korean enrichment coverage (% of nodes with non-empty title.ko)."""
    total, with_ko = 0, 0
    for s in tree.get("sections", []):
        for c in s.get("classes", []):
            for sc in c.get("subclasses", []):
                total += 1
                if (sc.get("title") or {}).get("ko"):
                    with_ko += 1
    return {
        "total_subclasses": total,
        "with_ko": with_ko,
        "coverage": with_ko / total if total else 0.0,
    }


def run_existing() -> int:
    """CLI verify — read existing @knowledge/classification/ files."""
    tree_path = IPC_ROOT / "tree.json"
    if not tree_path.exists():
        log.error("verify.no_tree", path=str(tree_path))
        return 1
    tree = json.loads(tree_path.read_text())
    errors = verify_ipc_tree(tree)
    if errors:
        for e in errors:
            log.error("verify.ipc_tree", error=e)
        return 1
    cov = verify_ko_coverage(tree)
    log.info("verify.ko_coverage", **cov)
    log.info("verify.ok", classification_root=str(CLASSIFICATION_ROOT))
    return 0
