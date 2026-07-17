"""Top-level build flow: fetch → merge → verify → write."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import structlog

from . import merge as merge_mod
from . import verify as verify_mod
from .paths import (
    CLASSIFICATION_ROOT,
    CPC_ROOT,
    IPC_ROOT,
    KNOWLEDGE_ROOT,
)
from .sources import (
    catchwords,
    concordance,
    data_go_kr,
    kipi_cpc,
    kipi_ipc,
    kipris_plus,
    wipo_cpc,
    wipo_ipc,
)
from .sources._common import make_client

log = structlog.get_logger()


def run(
    *,
    only: str = "all",
    cache_dir: str | Path,
    skip_fetch: bool = False,
    dry_run: bool = False,
) -> int:
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    do_ipc = only in ("ipc", "all")
    do_cpc = only in ("cpc", "all")

    sources_meta: list[dict] = []

    with make_client() as http:
        if do_ipc:
            log.info("build.ipc.start")
            wipo_ipc_data = _try_source(wipo_ipc, cache, http, skip_fetch, sources_meta)
            kipi_ipc_data = _try_source(kipi_ipc, cache, http, skip_fetch, sources_meta)
            kipris_data = _try_source(
                kipris_plus, cache, http, skip_fetch, sources_meta
            )
            ksic_data = _try_source(data_go_kr, cache, http, skip_fetch, sources_meta)
            catchwords_data = _try_source(
                catchwords, cache, http, skip_fetch, sources_meta
            )

            if wipo_ipc_data is None:
                log.error("build.ipc.no_master_tree")
                return 1

            merged_ipc = merge_mod.merge_tree(
                wipo=wipo_ipc_data,
                kipi=kipi_ipc_data,
                kipris_plus=kipris_data,
            )
            errors = verify_mod.verify_ipc_tree(merged_ipc)
            if errors:
                for e in errors:
                    log.warning("verify.warn", error=e)

            tree_meta, per_subclass, shards = merge_mod.split_tree_for_storage(
                merged_ipc
            )
            cov = verify_mod.verify_ko_coverage(merged_ipc)
            log.info("ipc.ko_coverage", **cov)

            if not dry_run:
                _write_ipc(tree_meta, per_subclass, shards)
                if ksic_data is not None:
                    _write_side_file("ksic-ipc.json", ksic_data)
                if catchwords_data is not None:
                    _write_side_file("catchwords.json", catchwords_data)

        if do_cpc:
            log.info("build.cpc.start")
            wipo_cpc_data = _try_source(wipo_cpc, cache, http, skip_fetch, sources_meta)
            kipi_cpc_data = _try_source(kipi_cpc, cache, http, skip_fetch, sources_meta)
            concordance_data = _try_source(
                concordance, cache, http, skip_fetch, sources_meta
            )

            if wipo_cpc_data is None:
                log.warning("build.cpc.skip_no_master_tree")
            else:
                merged_cpc = merge_mod.merge_tree(
                    wipo=wipo_cpc_data, kipi=kipi_cpc_data
                )
                tree_meta_cpc, per_subclass_cpc, shards_cpc = (
                    merge_mod.split_tree_for_storage(merged_cpc)
                )
                if not dry_run:
                    _write_cpc(tree_meta_cpc, per_subclass_cpc, shards_cpc)
                    if concordance_data is not None:
                        _write_side_file("ipc-cpc-concordance.json", concordance_data)

        if not dry_run:
            _write_version(sources_meta)

    log.info("build.done", dry_run=dry_run, sources=len(sources_meta))
    return 0


def _try_source(module, cache: Path, http, skip_fetch: bool, meta: list[dict]):
    """Run module.fetch + module.parse. Return parsed data or None if not yet implemented."""
    try:
        if skip_fetch:
            candidates = list(cache.glob(f"{module.SOURCE_ID}*"))
            if not candidates:
                raise RuntimeError(f"--skip-fetch but no cache for {module.SOURCE_ID}")
            path = candidates[0]
        else:
            path = module.fetch(cache, http)
        data = module.parse(path)
    except NotImplementedError:
        log.warning("source.not_implemented", source=module.SOURCE_ID)
        return None
    except Exception as exc:
        log.error("source.fail", source=module.SOURCE_ID, error=str(exc))
        return None
    meta.append(
        {
            "id": module.SOURCE_ID,
            "url": module.SOURCE_URL,
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            "cache_path": str(path),
        }
    )
    return data


def _write_classification_root(
    root: Path,
    tree_meta: dict,
    per_subclass: dict[str, dict],
    shards: dict[str, dict],
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tree.json").write_text(
        json.dumps(tree_meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sub_dir = root / "subclasses"
    sub_dir.mkdir(parents=True, exist_ok=True)
    for code, payload in per_subclass.items():
        (sub_dir / f"{code}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    shard_dir = root / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    for shard_name, payload in shards.items():
        (shard_dir / f"{shard_name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _write_ipc(
    tree_meta: dict, per_subclass: dict[str, dict], shards: dict[str, dict]
) -> None:
    _write_classification_root(IPC_ROOT, tree_meta, per_subclass, shards)


def _write_cpc(
    tree_meta: dict, per_subclass: dict[str, dict], shards: dict[str, dict]
) -> None:
    _write_classification_root(CPC_ROOT, tree_meta, per_subclass, shards)


def _write_side_file(filename: str, payload: dict) -> None:
    CLASSIFICATION_ROOT.mkdir(parents=True, exist_ok=True)
    (CLASSIFICATION_ROOT / filename).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_version(sources_meta: list[dict]) -> None:
    KNOWLEDGE_ROOT.mkdir(parents=True, exist_ok=True)
    CLASSIFICATION_ROOT.mkdir(parents=True, exist_ok=True)
    payload = merge_mod.build_version_meta(sources_meta)
    payload["built_at"] = dt.datetime.now(dt.UTC).isoformat()
    (CLASSIFICATION_ROOT / "version.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
