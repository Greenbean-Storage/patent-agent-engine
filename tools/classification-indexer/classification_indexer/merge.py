"""Merge WIPO master tree with KIPI Korean labels (and KIPRIS Plus supplement).

Produces the final tree dict that's split into `tree.json` (Section→Subclass)
and `subclasses/{code}.json` (Group/Subgroup detail).
"""

from __future__ import annotations

from typing import Any


def merge_tree(
    *,
    wipo: dict,
    kipi: dict[str, dict] | None = None,
    kipris_plus: dict[str, dict] | None = None,
) -> dict:
    """Master tree (WIPO English) + Korean enrichment (KIPI then KIPRIS).

    Walks the WIPO tree depth-first. For each node, looks up `code` in
    `kipi` first, then `kipris_plus`, attaching Korean title and definition.

    Returns the same shape as WIPO output, but with `title` upgraded from
    `title_en` to `{ ko, en }` and `definition` from `definition_en` to
    `{ ko, en }`.
    """
    kipi = kipi or {}
    kipris_plus = kipris_plus or {}

    def _ko_lookup(code: str) -> dict:
        """Return { 'title_ko'?, 'definition_ko'? } for the given code."""
        return kipi.get(code) or kipris_plus.get(code) or {}

    def _node(code: str, title_en: str, definition_en: str | None = None) -> dict:
        ko = _ko_lookup(code)
        n: dict = {
            "code": code,
            "title": {"ko": ko.get("title_ko"), "en": title_en},
        }
        if definition_en is not None or ko.get("definition_ko"):
            n["definition"] = {
                "ko": ko.get("definition_ko"),
                "en": definition_en,
            }
        return n

    sections_out = []
    for s in wipo["sections"]:
        s_node = _node(s["code"], s["title_en"])
        s_node["classes"] = []
        for c in s.get("classes", []):
            c_node = _node(c["code"], c["title_en"])
            c_node["subclasses"] = []
            for sc in c.get("subclasses", []):
                sc_node = _node(sc["code"], sc["title_en"])
                sc_node["groups"] = []
                for g in sc.get("groups", []):
                    g_node = _node(g["code"], g["title_en"], g.get("definition_en"))
                    g_node["subgroups"] = []
                    for sg in g.get("subgroups", []):
                        g_node["subgroups"].append(
                            _node(sg["code"], sg["title_en"], sg.get("definition_en"))
                        )
                    sc_node["groups"].append(g_node)
                c_node["subclasses"].append(sc_node)
            s_node["classes"].append(c_node)
        sections_out.append(s_node)
    return {"version": wipo.get("version"), "sections": sections_out}


# 4-shard layout for fan-out parallel classification stage.
# Each shard groups two adjacent IPC sections. Y is CPC-only (USPTO tagging
# section) — it gets absorbed into the last shard. IPC has no Y so the
# membership is ignored harmlessly.
SHARDS: dict[str, list[str]] = {
    "AB": ["A", "B"],
    "CD": ["C", "D"],
    "EF": ["E", "F"],
    "GH": ["G", "H", "Y"],
}


def split_tree_for_storage(
    merged: dict,
) -> tuple[dict, dict[str, dict], dict[str, dict]]:
    """Split merged tree into:
      1. `tree.json`            — Section→Subclass meta (full)
      2. `subclasses/{code}.json` — per-Subclass detail with Group/Subgroup
      3. `shards/{name}.json`   — same as tree.json but only sections in that shard

    Returns (tree_meta, per_subclass, shards).
    """
    tree_meta: dict = {"version": merged.get("version"), "sections": []}
    per_subclass: dict[str, dict] = {}

    for s in merged["sections"]:
        s_meta: dict[str, Any] = {
            "code": s["code"],
            "title": s["title"],
            "classes": [],
        }
        for c in s.get("classes", []):
            c_meta: dict[str, Any] = {
                "code": c["code"],
                "title": c["title"],
                "subclasses": [],
            }
            for sc in c.get("subclasses", []):
                # Tree meta gets just code+title for each subclass.
                c_meta["subclasses"].append(
                    {
                        "code": sc["code"],
                        "title": sc["title"],
                    }
                )
                # Per-subclass file gets full group/subgroup detail.
                payload: dict[str, Any] = {
                    "subclass": sc["code"],
                    "title": sc["title"],
                }
                if sc.get("definition"):
                    payload["definition"] = sc["definition"]
                payload["groups"] = sc.get("groups", [])
                per_subclass[sc["code"]] = payload
            s_meta["classes"].append(c_meta)
        tree_meta["sections"].append(s_meta)

    # Shards reuse the section meta from tree_meta.
    section_by_code = {s["code"]: s for s in tree_meta["sections"]}
    shards: dict[str, dict] = {}
    for shard_name, codes in SHARDS.items():
        shards[shard_name] = {
            "version": tree_meta.get("version"),
            "shard": shard_name,
            "sections": [section_by_code[c] for c in codes if c in section_by_code],
        }

    return tree_meta, per_subclass, shards


def build_version_meta(sources: list[dict[str, Any]]) -> dict:
    return {
        "schema_version": "1.0.0",
        "sources": sources,
    }
