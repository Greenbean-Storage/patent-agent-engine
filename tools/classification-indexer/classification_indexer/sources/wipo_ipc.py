"""① WIPO IPC — official scheme title list (English).

Master English tree on which KIPI Korean labels and Definitions are joined.

Source format: TSV title list per section, one file per Section A-H.
URL pattern:
  https://www.wipo.int/ipc/itos4ipc/ITSupport_and_download_area/{version}/
  IPC_scheme_title_list/EN_ipc_section_{X}_title_list_{version}.txt

Each line: `<code>\\t<english title>`

Code lengths and meaning:
  1 char  → Section (A, B, C, ...)
  3 chars → Class (A01, A02, ...)
  4 chars → Subclass (A01B, A01C, ...)
  14 chars → Group / Subgroup (A01B0001000000) — packed numeric form,
              e.g. A01B0001020000 = standard "A01B 1/02"

Definitions are NOT in the title list — they would require the full XML
master file. We attach English definitions in a later step (TODO).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import structlog

from ._common import download, polite_sleep

log = structlog.get_logger()

SOURCE_ID = "wipo_ipc"
SOURCE_URL = "https://www.wipo.int/classifications/ipc/en/ITsupport/Version20260101/"
DEFAULT_VERSION = "20260101"

SECTIONS = list("ABCDEFGH")

_TITLE_LIST_URL = (
    "https://www.wipo.int/ipc/itos4ipc/ITSupport_and_download_area/"
    "{version}/IPC_scheme_title_list/EN_ipc_section_{section}_title_list_{version}.txt"
)


def fetch(
    cache_dir: Path,
    http: httpx.Client,
    version: str = DEFAULT_VERSION,
) -> Path:
    """Download all 8 section title lists. Returns the merged JSON cache path."""
    section_dir = cache_dir / f"{SOURCE_ID}-{version}"
    section_dir.mkdir(parents=True, exist_ok=True)
    for section in SECTIONS:
        url = _TITLE_LIST_URL.format(version=version, section=section)
        dest = section_dir / f"{section}.txt"
        if dest.exists() and dest.stat().st_size > 0:
            continue
        download(http, url, dest, expect_min_bytes=1024)
        polite_sleep(0.5)

    merged_path = cache_dir / f"{SOURCE_ID}-{version}.json"
    if not merged_path.exists():
        merged = parse(section_dir, version=version)
        merged_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log.info(
            "wipo_ipc.parse.cached",
            path=str(merged_path),
            sections=len(merged["sections"]),
        )
    return merged_path


def parse(raw_path: Path, *, version: str = DEFAULT_VERSION) -> dict:
    """Parse all 8 section TXT files (raw_path is the section_dir) → tree dict.

    If raw_path is a file (the cached merged JSON), return its content.
    """
    if raw_path.is_file():
        return json.loads(raw_path.read_text(encoding="utf-8"))

    section_dir = raw_path
    sections: list[dict] = []
    for s in SECTIONS:
        f = section_dir / f"{s}.txt"
        if not f.exists():
            raise FileNotFoundError(f"missing section file: {f}")
        sections.append(_parse_section(f))
    return {"version": _format_version(version), "sections": sections}


def _format_version(v: str) -> str:
    # 20260101 → 2026.01
    return f"{v[:4]}.{v[4:6]}"


def _parse_section(path: Path) -> dict:
    """Parse one section TXT into a nested dict.

    Returns:
        { "code": "A", "title_en": "...",
          "classes": [{ "code": "A01", "title_en": "...",
                        "subclasses": [{ "code": "A01B", "title_en": "...",
                                         "groups": [{ "code": "A01B 1/00",
                                                      "title_en": "...",
                                                      "subgroups": [...] }] }] }] }
    """
    section: dict = {"code": "", "title_en": "", "classes": []}
    cur_class: dict | None = None
    cur_subclass: dict | None = None
    cur_main_group: dict | None = None  # last seen main group (for subgroup nesting)

    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line or "\t" not in line:
                continue
            code, title = line.split("\t", 1)
            code = code.strip()
            title = title.strip()
            if not code:
                continue
            n = len(code)
            if n == 1:  # Section
                section["code"] = code
                section["title_en"] = title
            elif n == 3:  # Class
                cur_class = {"code": code, "title_en": title, "subclasses": []}
                section["classes"].append(cur_class)
                cur_subclass = None
                cur_main_group = None
            elif n == 4:  # Subclass
                if cur_class is None:
                    raise ValueError(f"subclass {code} before any class")
                cur_subclass = {"code": code, "title_en": title, "groups": []}
                cur_class["subclasses"].append(cur_subclass)
                cur_main_group = None
            elif n == 14:  # Group or subgroup
                if cur_subclass is None:
                    raise ValueError(f"group {code} before any subclass")
                std_code = _packed_to_standard(code)
                is_main = code.endswith("000000")
                node = {"code": std_code, "title_en": title}
                if is_main:
                    node["subgroups"] = []
                    cur_subclass["groups"].append(node)
                    cur_main_group = node
                else:
                    if cur_main_group is None:
                        # Subgroup without preceding main group — attach as group
                        node["subgroups"] = []
                        cur_subclass["groups"].append(node)
                        cur_main_group = node
                    else:
                        cur_main_group["subgroups"].append(node)
            else:
                # ignore unknown widths
                continue
    return section


_PACKED_RE = re.compile(r"^([A-H]\d{2}[A-Z])(\d{4})(\d{6})$")


def _packed_to_standard(packed: str) -> str:
    """A01B0001020000 → 'A01B 1/02', A01B0003421000 → 'A01B 3/421'."""
    m = _PACKED_RE.match(packed)
    if not m:
        return packed  # fallback
    sub, main, frac = m.group(1), m.group(2), m.group(3)
    main_int = int(main)
    # Strip trailing zeros from the 6-digit fractional part. Always show at
    # least 2 digits ("00" for main groups, "02" for /02).
    frac_stripped = frac.rstrip("0") or "00"
    if len(frac_stripped) < 2:
        frac_stripped = frac_stripped.ljust(2, "0")
    return f"{sub} {main_int}/{frac_stripped}"
