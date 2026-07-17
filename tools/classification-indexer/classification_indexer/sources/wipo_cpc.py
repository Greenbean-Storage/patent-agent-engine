"""⑦ CPC — Cooperative Patent Classification (USPTO/EPO).

Source: cooperativepatentclassification.org bulk
File: CPCTitleList{YYYYMM}.zip

ZIP layout: 9 TSV files, one per section (A-H + Y).
Line format: `<code>\\t<depth>\\t<english title>`

Code lengths and meaning (similar to IPC but with explicit depth):
  1 char  → Section (A, B, ..., Y; CPC has Y for tagging)
  3 chars → Class (A01)
  4 chars → Subclass (A01B)
  longer  → Group ('A01B1/00' depth=0) or Subgroup (depth >= 1)

CPC ships English-only. Korean labels (kipi_cpc) join later.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import httpx
import structlog

from ._common import download

log = structlog.get_logger()

SOURCE_ID = "wipo_cpc"
SOURCE_URL = (
    "https://www.cooperativepatentclassification.org/cpcSchemeAndDefinitions/bulk"
)
DEFAULT_VERSION = "202605"  # CPC 2026.05

_TITLE_LIST_URL = (
    "https://www.cooperativepatentclassification.org/sites/default/files/cpc/bulk/"
    "CPCTitleList{version}.zip"
)


def fetch(
    cache_dir: Path,
    http: httpx.Client,
    version: str = DEFAULT_VERSION,
) -> Path:
    """Download CPC Title List ZIP, extract sections, return merged JSON path."""
    extracted_dir = cache_dir / f"{SOURCE_ID}-{version}"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    zip_dest = cache_dir / f"{SOURCE_ID}-{version}.zip"
    download(
        http, _TITLE_LIST_URL.format(version=version), zip_dest, expect_min_bytes=1024
    )

    if not any(extracted_dir.glob("*.txt")):
        with zipfile.ZipFile(zip_dest) as z:
            z.extractall(extracted_dir)

    merged_path = cache_dir / f"{SOURCE_ID}-{version}.json"
    if not merged_path.exists():
        merged = parse(extracted_dir, version=version)
        merged_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log.info(
            "wipo_cpc.parse.cached",
            path=str(merged_path),
            sections=len(merged["sections"]),
        )
    return merged_path


def parse(raw_path: Path, *, version: str = DEFAULT_VERSION) -> dict:
    """Parse the extracted CPC section TXTs (or the cached JSON)."""
    if raw_path.is_file():
        return json.loads(raw_path.read_text(encoding="utf-8"))

    section_files = sorted(raw_path.glob("cpc-section-*.txt"))
    sections = [_parse_section_file(p) for p in section_files]
    return {"version": _format_version(version), "sections": sections}


def _format_version(v: str) -> str:
    # 202605 → 2026.05
    return f"{v[:4]}.{v[4:6]}"


_GROUP_RE = re.compile(r"^([A-HY]\d{2}[A-Z])(\d+)/(\d+)$")


def _parse_section_file(path: Path) -> dict:
    section: dict = {"code": "", "title_en": "", "classes": []}
    cur_class: dict | None = None
    cur_subclass: dict | None = None
    depth_stack: list[dict] = []  # parallel to subgroup nesting depth

    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            code = parts[0].strip()
            depth_str = parts[1].strip() if len(parts) > 1 else ""
            title = (
                parts[2].strip()
                if len(parts) > 2
                else (
                    parts[1].strip()
                    if len(parts) > 1 and not depth_str.isdigit()
                    else ""
                )
            )
            if not code:
                continue

            n = len(code)
            if n == 1:  # Section
                section["code"] = code
                section["title_en"] = title
                cur_class = None
                cur_subclass = None
                depth_stack = []
            elif n == 3:  # Class
                cur_class = {"code": code, "title_en": title, "subclasses": []}
                section["classes"].append(cur_class)
                cur_subclass = None
                depth_stack = []
            elif n == 4:  # Subclass
                if cur_class is None:
                    continue
                cur_subclass = {"code": code, "title_en": title, "groups": []}
                cur_class["subclasses"].append(cur_subclass)
                depth_stack = []
            elif _GROUP_RE.match(code):  # Group / Subgroup
                if cur_subclass is None:
                    continue
                depth = int(depth_str) if depth_str.isdigit() else 0
                node = {"code": _normalize_code(code), "title_en": title}
                if depth == 0:
                    node["subgroups"] = []
                    cur_subclass["groups"].append(node)
                    depth_stack = [node]
                else:
                    # Walk the stack to find a parent of depth-1
                    while depth_stack and len(depth_stack) > depth:
                        depth_stack.pop()
                    parent = depth_stack[-1] if depth_stack else None
                    if parent is None:
                        # Stray subgroup — treat as main group
                        node["subgroups"] = []
                        cur_subclass["groups"].append(node)
                        depth_stack = [node]
                    else:
                        node["subgroups"] = []
                        parent.setdefault("subgroups", []).append(node)
                        depth_stack = depth_stack[:depth] + [node]
            else:
                # Unknown line; skip
                continue
    return section


def _normalize_code(code: str) -> str:
    """A47G19/22 → 'A47G 19/22' (match IPC display style)."""
    m = _GROUP_RE.match(code)
    if not m:
        return code
    return f"{m.group(1)} {m.group(2)}/{m.group(3)}"
