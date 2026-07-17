"""venezia_memory — scaffolding SoT 기반 S3 key builder 전수 (순수 함수)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))

import venezia_memory as vm  # noqa: E402

U, INV, C, R = "u1", "i1", "c1", "rt1"


def test_persona_dir_all():
    assert vm.persona_dir(1) == "01.buddy"
    assert vm.persona_dir(6) == "06.inspector"
    for p in range(1, 7):
        assert vm.persona_dir(p) == vm.PERSONA_DIRS[p]


def test_persona_dir_invalid():
    with pytest.raises(ValueError):
        vm.persona_dir(0)
    with pytest.raises(ValueError):
        vm.persona_dir(7)


def test_session_and_root_keys():
    assert vm.session_root(U, INV) == f"sessions/{U}/{INV}"
    assert vm.context_manifest_key(U, INV) == f"sessions/{U}/{INV}/manifest.context.yaml"
    assert vm.runtime_root(U, INV) == f"sessions/{U}/{INV}/runtime"
    assert vm.runtime_manifest_key(U, INV).endswith("runtime/manifest.runtime.yaml")


def test_users_keys():
    assert vm.identity_key("google", "sub123") == "users/identities/google/sub123.json"
    assert vm.profile_key(U) == f"users/profiles/{U}/profile.json"


def test_dro_keys():
    assert vm.dro_root(U, INV).endswith("runtime/00.dro")
    assert vm.conversation_key(U, INV).endswith("00.dro/conversation.json")


def test_media_keys():
    """work 레벨 미디어 (presigned S3 직접) — 메시지/chain 무관, S3 prefix 가 진실."""
    assert vm.media_root(U, INV) == f"sessions/{U}/{INV}/media"
    assert vm.media_key(U, INV, "m1", "png") == f"sessions/{U}/{INV}/media/m1.png"
    assert vm.media_key(U, INV, "m1", "png").startswith(vm.media_root(U, INV))
    assert vm.MEDIA_DIRNAME == vm.NS_MEDIA == "media"


def test_persona_runtime_keys():
    assert vm.persona_root(U, INV, 2).endswith("runtime/02.director")
    assert vm.queue_key(U, INV, 2).endswith("02.director/queue.json")
    assert vm.chain_dir(U, INV, 2, C).endswith(f"02.director/{C}")
    assert vm.chain_manifest_key(U, INV, 2, C).endswith(f"{C}/manifest.json")
    assert vm.trail_key(U, INV, 2, C).endswith(f"{C}/trail.jsonl")
    assert vm.rt_key(U, INV, 2, C, R).endswith(f"{C}/rts/{R}.json")
    assert vm.agent_state_key(U, INV, 2, C).endswith(f"{C}/agent_state.json")


def test_persona_dialog_allowlist():
    assert vm.persona_dialog_key(U, INV, 2, "analysis").endswith("02.director/analysis.json")
    assert vm.persona_dialog_key(U, INV, 3, "research").endswith("03.finder/research.json")
    with pytest.raises(ValueError):
        vm.persona_dialog_key(U, INV, 2, "nonexistent")
    with pytest.raises(ValueError):
        vm.persona_dialog_key(U, INV, 1, "anything")  # 01.buddy = no dialogs


def test_models_keys():
    assert vm.models_root(U, INV).endswith(f"{INV}/models")
    assert vm.models_manifest_key(U, INV).endswith("models/manifest.models.yaml")
    assert vm.iom_key(U, INV).endswith("models/invention-object-model.json")
    assert vm.cmm_key(U, INV).endswith("models/concept-maturity-model.json")
    assert vm.user_roadmap_key(U, INV).endswith("models/user-roadmap.json")
    assert vm.concept_discovery_stack_key(U, INV).endswith("models/concept-discovery-stack.json")


def test_outputs_keys():
    assert vm.outputs_root(U, INV).endswith(f"{INV}/outputs")
    assert vm.outputs_manifest_key(U, INV).endswith("outputs/manifest.outputs.yaml")
    assert vm.output_key(U, INV, "draft.docx").endswith("outputs/draft.docx")


def test_drawings_keys():
    assert vm.drawings_root(U, INV).endswith(f"{INV}/drawings")
    assert vm.drawings_manifest_key(U, INV).endswith("drawings/manifest.drawing.yaml")
    assert vm.drawing_dir(U, INV, "d1").endswith("drawings/d1")
    assert vm.drawing_numerals_key(U, INV, "d1").endswith("d1/numerals.json")
    assert vm.drawing_dl_key(U, INV, "d1").endswith("d1/dl.json")
    assert vm.drawing_figure_key(U, INV, "d1").endswith("d1/figure.json")


def test_constants_and_dialog_names():
    assert vm.SCHEMA_VERSION == "1.0.0"
    assert vm.ROOT_PREFIX == "sessions"
    assert vm.DRO_DIR == "00.dro"
    assert "analysis" in vm.DIALOG_NAMES["02.director"]
    assert vm.DIALOG_NAMES["01.buddy"] == frozenset()
