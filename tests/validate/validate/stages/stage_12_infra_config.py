"""Stage 12 — 인프라 설정 YAML 정합 (scaffolding / topology / compose / knobs / engine.config).

코드에서 생성되지 않는 인프라 SoT 들을 구조 검증:
- scaffolding.yaml — storage-key SoT (필수 섹션 존재)
- topology.yaml — services{host,port,host_publish_port} 순수 주소록 (persona_mapping 잔재 = fail)
- compose.yaml — 유효 YAML + services ⊇ topology.services (topology 파생 일치)
- knobs.yaml — 검증 knob 스키마 (kind / values / default∈values / realize.via)
- engine.config.yaml — engine-config.schema.json(Draft 7) 검증 + persona-id 4원 정합 게이트
  (engine.config personas ↔ channels.py ↔ venezia_memory PERSONA_DIRS ↔ @pipelines 디렉토리)
- media.config.yaml — media-config.schema.json(Draft 7) 검증 (업로드 제한·presign TTL SoT)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .._common import ROOT, ValidationReport

STAGE_NAME = "infra config"

_SCAFFOLD = ROOT / "shared" / "venezia_memory" / "scaffolding.yaml"
_TOPOLOGY = ROOT / "@deployment" / "topology.yaml"
_KNOBS = ROOT / "@deployment" / "knobs.yaml"
_ENGINE_CONFIG = ROOT / "@deployment" / "engine.config.yaml"
_ENGINE_CONFIG_SCHEMA = ROOT / "@deployment" / "engine-config.schema.json"
_MEDIA_CONFIG = ROOT / "@deployment" / "media.config.yaml"
_MEDIA_CONFIG_SCHEMA = ROOT / "@deployment" / "media-config.schema.json"
_COMPOSE = ROOT / "compose.yaml"
_COMPOSE_OVERRIDE = ROOT / "compose.override.yaml"


def _load_yaml(p: Path, rep: ValidationReport, label: str) -> Any:
    if not p.exists():
        rep.err(f"[infra] {label} 없음: {p}")
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:
        rep.err(f"[infra] {label} YAML 파싱 실패: {e}")
        return None


def validate_infra_config(rep: ValidationReport) -> bool:
    ok = True

    # 1) scaffolding.yaml — 필수 섹션
    sc = _load_yaml(_SCAFFOLD, rep, "scaffolding.yaml")
    if sc is not None:
        if not isinstance(sc, dict):
            rep.err("[infra] scaffolding.yaml 최상위가 mapping 아님")
            ok = False
        else:
            for key in (
                "schema_version",
                "root_prefix",
                "entity_path",
                "root_manifest",
                "users",
                "namespaces",
            ):
                if key not in sc:
                    rep.err(f"[infra] scaffolding.yaml 필수 키 없음: {key}")
                    ok = False

    # 2) topology.yaml — services (순수 네트워크 주소록 — 구 persona_mapping 은 unified 컷오버로
    #    폐기, persona 정합은 engine.config 게이트(아래 5)가 담당)
    topo = _load_yaml(_TOPOLOGY, rep, "topology.yaml")
    topo_services: set[str] = set()
    if topo is not None:
        if not isinstance(topo, dict) or not isinstance(topo.get("services"), dict):
            rep.err("[infra] topology.yaml 에 services mapping 없음")
            ok = False
        else:
            services = topo["services"]
            topo_services = set(services)
            for name, svc in services.items():
                if not isinstance(svc, dict):
                    rep.err(f"[infra] topology service {name} 가 mapping 아님")
                    ok = False
                    continue
                for fld, typ in (("host", str), ("port", int), ("host_publish_port", int)):
                    if not isinstance(svc.get(fld), typ):
                        rep.err(f"[infra] topology {name}.{fld} 타입 위반 ({typ.__name__} 기대)")
                        ok = False
            if "persona_mapping" in topo:
                rep.err(
                    "[infra] topology.yaml 에 persona_mapping 잔재 — unified 컷오버로 폐기됨 "
                    "(persona 의 SoT = engine.config)"
                )
                ok = False

    # 3) compose.yaml — 유효 YAML + services ⊇ topology.services
    comp = _load_yaml(_COMPOSE, rep, "compose.yaml")
    if comp is not None:
        comp_services = set((comp.get("services") or {})) if isinstance(comp, dict) else set()
        if not comp_services:
            rep.err("[infra] compose.yaml 에 services 없음")
            ok = False
        elif topo_services and not topo_services <= comp_services:
            rep.err(
                f"[infra] compose.services 가 topology.services 미포함: "
                f"{sorted(topo_services - comp_services)}"
            )
            ok = False

    # compose.override (있으면 유효 YAML 인지만)
    if _COMPOSE_OVERRIDE.exists():
        _load_yaml(_COMPOSE_OVERRIDE, rep, "compose.override.yaml")

    # 4) knobs.yaml — 검증 knob 스키마 (kind / values / default∈values / realize.via)
    kn = _load_yaml(_KNOBS, rep, "knobs.yaml")
    if kn is not None:
        knobs = kn.get("knobs") if isinstance(kn, dict) else None
        if not isinstance(knobs, dict) or not knobs:
            rep.err("[infra] knobs.yaml 에 knobs mapping 없음")
            ok = False
        else:
            for name, spec in knobs.items():
                if not isinstance(spec, dict):
                    rep.err(f"[infra] knob {name} 가 mapping 아님")
                    ok = False
                    continue
                if spec.get("kind") not in ("fidelity", "behavior"):
                    rep.err(f"[infra] knob {name}.kind 위반 (fidelity|behavior)")
                    ok = False
                vals = spec.get("values")
                if not isinstance(vals, list) or not vals:
                    rep.err(f"[infra] knob {name}.values 누락/비어있음")
                    ok = False
                elif spec.get("default") not in vals:
                    rep.err(f"[infra] knob {name}.default '{spec.get('default')}' ∉ values")
                    ok = False
                rz = spec.get("realize")
                if not isinstance(rz, dict) or rz.get("via") not in ("image", "config"):
                    rep.err(f"[infra] knob {name}.realize.via 위반 (image|config)")
                    ok = False

    # 5) engine.config.yaml — 스키마 + persona-id 정합 게이트
    if not _validate_engine_config(rep):
        ok = False

    # 6) media.config.yaml — 스키마 검증
    if not _validate_media_config(rep):
        ok = False

    if ok:
        rep.stage_pass[STAGE_NAME] += 1
    return ok


def _validate_media_config(rep: ValidationReport) -> bool:
    """media.config.yaml — media-config.schema.json(Draft 7) 검증."""
    import json

    import jsonschema

    cfg = _load_yaml(_MEDIA_CONFIG, rep, "media.config.yaml")
    if cfg is None:
        return False
    if not _MEDIA_CONFIG_SCHEMA.exists():
        rep.err(f"[infra] media-config.schema.json 없음: {_MEDIA_CONFIG_SCHEMA}")
        return False
    try:
        schema = json.loads(_MEDIA_CONFIG_SCHEMA.read_text(encoding="utf-8"))
    except Exception as e:
        rep.err(f"[infra] media-config.schema.json 파싱 실패: {e}")
        return False
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(cfg), key=lambda v: list(v.absolute_path))
    for verr in errors[:10]:
        path = "/".join(str(p) for p in verr.absolute_path) or "<root>"
        rep.err(f"[infra] media.config.yaml schema 위반 @{path}: {verr.message}")
    return not errors


def _validate_engine_config(rep: ValidationReport) -> bool:
    """engine.config.yaml — 스키마 검증 + persona-id 4원 정합 게이트.

    persona 정의의 개념적 SoT = engine.config personas. 기계 소비자의 코드 상수
    (Nexus channel = venezia_contracts channels.py, CM/DRO 경로 = venezia_memory
    PERSONA_DIRS) 는 미러 — 본 게이트가 byte-일치를 강제해 드리프트를 차단한다.
    """
    import json

    import jsonschema
    from venezia_contracts.models.dro_api.channels import PERSONA_TO_CHANNEL
    from venezia_memory import PERSONA_DIRS

    cfg = _load_yaml(_ENGINE_CONFIG, rep, "engine.config.yaml")
    if cfg is None:
        return False
    if not _ENGINE_CONFIG_SCHEMA.exists():
        rep.err(f"[infra] engine-config.schema.json 없음: {_ENGINE_CONFIG_SCHEMA}")
        return False
    try:
        schema = json.loads(_ENGINE_CONFIG_SCHEMA.read_text(encoding="utf-8"))
    except Exception as e:
        rep.err(f"[infra] engine-config.schema.json 파싱 실패: {e}")
        return False

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(cfg), key=lambda v: list(v.absolute_path))
    for verr in errors[:10]:
        path = "/".join(str(p) for p in verr.absolute_path) or "<root>"
        rep.err(f"[infra] engine.config.yaml schema 위반 @{path}: {verr.message}")
    if errors:
        return False

    ok = True
    personas = cfg["personas"]
    cfg_ids = {int(k) for k in personas}
    pipeline_ids: set[int] = set()
    for d in (ROOT / "@pipelines").iterdir():
        name = d.name
        if d.is_dir() and len(name) > 3 and name[:2].isdigit() and name[2] == ".":
            pipeline_ids.add(int(name[:2]))
    for label, other in (
        ("channels.py PERSONA_TO_CHANNEL", set(PERSONA_TO_CHANNEL)),
        ("venezia_memory PERSONA_DIRS", set(PERSONA_DIRS)),
        ("@pipelines 디렉토리", pipeline_ids),
    ):
        if cfg_ids != other:
            rep.err(
                f"[infra] persona id 집합 불일치: engine.config {sorted(cfg_ids)} "
                f"↔ {label} {sorted(other)}"
            )
            ok = False
    for k, entry in personas.items():
        pid = int(k)
        expected_channel = PERSONA_TO_CHANNEL.get(pid)
        if expected_channel is not None and entry.get("channel") != expected_channel:
            rep.err(
                f"[infra] persona {pid} channel 미러 불일치: "
                f"engine.config '{entry.get('channel')}' ↔ channels.py '{expected_channel}'"
            )
            ok = False
        expected_dir = PERSONA_DIRS.get(pid)
        if expected_dir is not None and entry.get("memory_dir") != expected_dir:
            rep.err(
                f"[infra] persona {pid} memory_dir 미러 불일치: "
                f"engine.config '{entry.get('memory_dir')}' ↔ PERSONA_DIRS '{expected_dir}'"
            )
            ok = False
    return ok
