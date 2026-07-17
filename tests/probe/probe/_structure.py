"""세션 S3 메모리 구조 검증 로직 (probe 전용).

probe structure / verify 가 CM `/tree`(세션 prefix 실제 키 전수)를 받아 scaffolding 과 대조.
classify_key 는 venezia_memory(scaffolding SoT)의 *레이아웃 사실* 상수만 가져다 쓰고,
판단(검증) '로직' 은 여기 둔다 — 제품/shared 엔 검증 로직 0 원칙.

- classify_key(키) → scaffolding resource-type 이름 (없으면 None = orphan)
- verify_structure(키목록, manifests) → 리포트 (orphan / 필수누락 / manifest 불일치 / 관찰 비율)
"""

from __future__ import annotations

from typing import Any

import venezia_memory as vm

_PERSONA_DIR_SET = frozenset(vm.PERSONA_DIRS.values())

# 세션 scope resource-type 전체 (구조검증 metric 의 분모 — drawings 포함, users 제외).
SESSION_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        "context_manifest",
        "runtime_manifest",
        "conversation",
        "media",
        "persona_queue",
        "persona_dialog",
        "chain_manifest",
        "chain_trail",
        "chain_rt",
        "chain_agent_state",
        "models_manifest",
        "iom",
        "cmm",
        "user_roadmap",
        "concept_discovery_stack",
        "drawings_manifest",
        "drawing_numerals",
        "drawing_dl",
        "drawing_figure",
        "outputs_manifest",
        "output",
    }
)
# 세션이라면 반드시 있어야 하는 resource-type.
REQUIRED_RESOURCE_TYPES: frozenset[str] = frozenset({"context_manifest", "runtime_manifest"})


def _classify_runtime(rest: list[str]) -> str | None:
    if rest == [vm.MANIFEST_RUNTIME]:
        return "runtime_manifest"
    if not rest:
        return None
    head, sub = rest[0], rest[1:]
    if head == vm.DRO_DIR:
        if sub == [vm.CONVERSATION_FILE]:
            return "conversation"
        return None
    if head in _PERSONA_DIR_SET:
        if sub == [vm.QUEUE_FILE]:
            return "persona_queue"
        if len(sub) == 1 and sub[0].endswith(".json"):
            name = sub[0][: -len(".json")]
            return "persona_dialog" if name in vm.DIALOG_NAMES.get(head, frozenset()) else None
        if len(sub) == 2:
            leaf = sub[1]
            if leaf == vm.CHAIN_MANIFEST_FILE:
                return "chain_manifest"
            if leaf == vm.CHAIN_TRAIL_FILE:
                return "chain_trail"
            if leaf == vm.CHAIN_AGENT_STATE_FILE:
                return "chain_agent_state"
            return None
        if len(sub) == 3 and sub[1] == vm.CHAIN_RT_DIRNAME and sub[2].endswith(".json"):
            return "chain_rt"
    return None


def _classify_models(rest: list[str]) -> str | None:
    if rest == [vm.MANIFEST_MODELS]:
        return "models_manifest"
    if rest == [vm.IOM_FILE]:
        return "iom"
    if rest == [vm.CMM_FILE]:
        return "cmm"
    if rest == [vm.USER_ROADMAP_FILE]:
        return "user_roadmap"
    if rest == [vm.CONCEPT_DISCOVERY_STACK_FILE]:
        return "concept_discovery_stack"
    return None


def _classify_drawings(rest: list[str]) -> str | None:
    if rest == [vm.MANIFEST_DRAWINGS]:
        return "drawings_manifest"
    if len(rest) == 2:
        leaf = rest[1]
        if leaf == vm.DRAWING_NUMERALS_FILE:
            return "drawing_numerals"
        if leaf == vm.DRAWING_DL_FILE:
            return "drawing_dl"
        if leaf == vm.DRAWING_FIGURE_FILE:
            return "drawing_figure"
    return None


def classify_key(rel_key: str) -> str | None:
    """session-relative key (sessions/{uid}/{iid}/ 이후) → scaffolding resource-type.

    매칭되는 resource-type 이 없으면 None (= scaffolding 밖 orphan 후보).
    """
    rel = rel_key.strip("/")
    if not rel:
        return None
    if rel == vm.ROOT_MANIFEST:
        return "context_manifest"
    head, *rest = rel.split("/")
    if head == vm.NS_RUNTIME:
        return _classify_runtime(rest)
    if head == vm.NS_MODELS:
        return _classify_models(rest)
    if head == vm.NS_OUTPUTS:
        if rest == [vm.MANIFEST_OUTPUTS]:
            return "outputs_manifest"
        return "output" if len(rest) == 1 and rest[0] else None
    if head == vm.NS_DRAWINGS:
        return _classify_drawings(rest)
    if head == vm.NS_MEDIA:
        # media/{media_id}.{ext} — work 레벨, 단일 leaf
        return "media" if len(rest) == 1 and rest[0] else None
    return None


def verify_structure(
    session_keys: list[str],
    runtime_manifest: dict[str, Any] | None = None,
    outputs_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """세션 실제 키(tree) ↔ scaffolding + manifest 대조 리포트.

    runtime(chains)·outputs(files) manifest 는 list 의미가 있어 실제와 교차검증.
    models·context manifest 는 존재/가독(읽힘) + classify 로 tree 안 존재 확인 (호출자가 fetch).

    - orphans          : scaffolding resource-type 에 안 맞는 키 (설계 밖 파일)
    - missing_required : 필수 resource-type(context/runtime manifest) 부재
    - mismatches       : manifest↔실제 불일치 (runtime chains / outputs 산출물)
    - present / total  : 관찰된 resource-type 수 / 전체(drawings 포함, users 제외)
    - ok               : orphan 0 · 필수 충족 · 불일치 0 · 관찰 ≥99%
    """
    present: set[str] = set()
    orphans: list[str] = []
    chain_ids_in_keys: set[str] = set()
    output_files_in_keys: set[str] = set()
    for key in session_keys:
        rtype = classify_key(key)
        if rtype is None:
            orphans.append(key)
            continue
        present.add(rtype)
        parts = key.strip("/").split("/")
        if rtype in ("chain_manifest", "chain_trail", "chain_rt", "chain_agent_state"):
            if len(parts) >= 3:
                chain_ids_in_keys.add(parts[2])
        elif rtype == "output":
            output_files_in_keys.add(parts[-1])

    mismatches: list[str] = []
    if runtime_manifest is not None:
        manifest_chains: set[str] = set()
        for c in runtime_manifest.get("chains") or []:
            if isinstance(c, dict):
                cid = c.get("chain_id")
                if isinstance(cid, str):
                    manifest_chains.add(cid)
        for cid in sorted(manifest_chains - chain_ids_in_keys):
            mismatches.append(f"runtime manifest 의 chain '{cid}' 가 실제 저장소에 없음")
        for cid in sorted(chain_ids_in_keys - manifest_chains):
            mismatches.append(f"저장된 chain '{cid}' 가 runtime manifest 에 없음")

    if outputs_manifest is not None:
        listed = outputs_manifest.get("files") or outputs_manifest.get("outputs") or []
        listed_names: set[str] = set()
        for f in listed:
            if isinstance(f, str):
                listed_names.add(f)
            elif isinstance(f, dict):
                fn = f.get("filename")
                if isinstance(fn, str):
                    listed_names.add(fn)
        for name in sorted(listed_names - output_files_in_keys):
            mismatches.append(f"outputs manifest 의 산출물 '{name}' 가 실제 저장소에 없음")

    total = len(SESSION_RESOURCE_TYPES)
    missing_required = sorted(REQUIRED_RESOURCE_TYPES - present)
    ratio = len(present) / total if total else 0.0
    return {
        "ok": (not orphans and not missing_required and not mismatches and ratio >= 0.99),
        "present": sorted(present),
        "total": total,
        "ratio": ratio,
        "orphans": orphans,
        "missing_required": missing_required,
        "mismatches": mismatches,
    }
