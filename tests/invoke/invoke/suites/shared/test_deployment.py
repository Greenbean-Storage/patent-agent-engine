"""venezia_deployment — knob 스키마(model) / 로드·검증(loader) / 런타임 read(runtime) / CLI(__main__) / export.

venezia_topology 테스트 패턴 미러 (sys.path insert + env-driven + lru_cache clear).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "shared"))

from venezia_deployment import __main__ as vmain  # noqa: E402
from venezia_deployment import export as vexport  # noqa: E402
from venezia_deployment import loader as vloader  # noqa: E402
from venezia_deployment import model as vmodel  # noqa: E402
from venezia_deployment import runtime as vruntime  # noqa: E402

KNOBS = str(ROOT / "@deployment" / "knobs.yaml")


def _profile_text() -> str:
    return (
        "version: 1\nactor: real\ndro: real\ncm: real\nnexus: real\n"
        "llm: real\nkipris: real\nauth: secure\nengine: full\n"
    )


@pytest.fixture
def knobs():
    return vloader.load_knobs(KNOBS)


# ── model ──


def test_model_default_not_in_values():
    with pytest.raises(ValueError):
        vmodel.KnobSpec(
            kind="fidelity",
            values=["real", "fake"],
            default="x",
            realize=vmodel.Realize(via="config"),
        )


def test_model_real_knobs(knobs):
    assert knobs.knobs["actor"].kind == "fidelity"
    assert knobs.knobs["cm"].available is False
    assert knobs.knobs["llm"].realize.via == "config"
    assert knobs.knobs["actor"].realize.services == ["actor"]  # unified 단일 actor


# ── loader ──


def test_default_profile(knobs):
    prof = vloader.default_profile(knobs)
    assert prof["version"] == 1
    assert prof["actor"] == "real" and prof["auth"] == "secure"


def test_load_knobs_missing(tmp_path):
    with pytest.raises(RuntimeError):
        vloader.load_knobs(tmp_path / "nope.yaml")


def test_load_profile_missing(tmp_path):
    with pytest.raises(RuntimeError):
        vloader.load_profile(tmp_path / "nope.yaml")


def test_load_profile_non_dict(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(RuntimeError):
        vloader.load_profile(p)


def test_validate_ok(knobs):
    vloader.validate_profile(vloader.default_profile(knobs), knobs)


def test_validate_bad_version(knobs):
    prof = vloader.default_profile(knobs)
    prof["version"] = 99
    with pytest.raises(ValueError):
        vloader.validate_profile(prof, knobs)


def test_validate_unknown_knob(knobs):
    prof = vloader.default_profile(knobs)
    prof["bogus"] = "x"
    with pytest.raises(ValueError):
        vloader.validate_profile(prof, knobs)


def test_validate_bad_value(knobs):
    prof = vloader.default_profile(knobs)
    prof["actor"] = "nope"
    with pytest.raises(ValueError):
        vloader.validate_profile(prof, knobs)


def test_validate_unavailable(knobs):
    prof = vloader.default_profile(knobs)
    prof["cm"] = "fake"
    with pytest.raises(ValueError):
        vloader.validate_profile(prof, knobs)


def test_validate_missing_knob(knobs):
    prof = vloader.default_profile(knobs)
    del prof["actor"]
    with pytest.raises(ValueError):
        vloader.validate_profile(prof, knobs)


# ── runtime ──


@pytest.fixture
def prof_env(tmp_path, monkeypatch):
    p = tmp_path / "deployment.yaml"
    p.write_text(_profile_text())
    monkeypatch.setenv("DEPLOYMENT_FILE", str(p))
    vruntime._load.cache_clear()
    yield p
    vruntime._load.cache_clear()


def test_runtime_getters(prof_env):
    assert vruntime.value("actor") == "real"
    assert vruntime.auth() == "SECURE"
    assert vruntime.engine() == "FULL"
    assert vruntime.llm() == "PRODUCTION"
    assert vruntime.kipris() == "real"


def test_runtime_llm_fake(tmp_path, monkeypatch):
    p = tmp_path / "d.yaml"
    p.write_text(_profile_text().replace("llm: real", "llm: fake"))
    monkeypatch.setenv("DEPLOYMENT_FILE", str(p))
    vruntime._load.cache_clear()
    assert vruntime.llm() == "FIXTURE"
    vruntime._load.cache_clear()


def test_runtime_kipris_fake(tmp_path, monkeypatch):
    """3k: kipris() 는 raw lowercase 반환 — fake 그대로."""
    p = tmp_path / "d.yaml"
    p.write_text(_profile_text().replace("kipris: real", "kipris: fake"))
    monkeypatch.setenv("DEPLOYMENT_FILE", str(p))
    vruntime._load.cache_clear()
    assert vruntime.kipris() == "fake"
    vruntime._load.cache_clear()


def test_runtime_value_missing(prof_env):
    with pytest.raises(KeyError):
        vruntime.value("nonexistent")


def test_runtime_missing_file(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_FILE", "/nonexistent/deployment.yaml")
    vruntime._load.cache_clear()
    with pytest.raises(RuntimeError):
        vruntime.value("actor")
    vruntime._load.cache_clear()


def test_runtime_invalid_schema(tmp_path, monkeypatch):
    p = tmp_path / "bad.yaml"
    p.write_text("foo: bar\n")  # version 없음
    monkeypatch.setenv("DEPLOYMENT_FILE", str(p))
    vruntime._load.cache_clear()
    with pytest.raises(RuntimeError):
        vruntime.value("actor")
    vruntime._load.cache_clear()


def test_runtime_app_getters_fallback_when_missing(monkeypatch):
    """1b: 파일 부재 시 auth/engine/llm 은 raise 대신 fallback default (config singleton import 가능하게)."""
    monkeypatch.setenv("DEPLOYMENT_FILE", "/nonexistent/deployment.yaml")
    vruntime._load.cache_clear()
    assert vruntime.auth() == "SECURE"
    assert vruntime.engine() == "FULL"
    assert vruntime.llm() == "PRODUCTION"
    assert vruntime.kipris() == "real"
    vruntime._load.cache_clear()


# ── __main__ CLI ──


def _argv(prof: Path, *rest: str) -> list[str]:
    return ["--knobs", KNOBS, "--profile", str(prof), *rest]


def test_cli_init_show_vet(tmp_path, capsys):
    prof = tmp_path / "profile.stack.yaml"
    assert vmain.main(_argv(prof, "init")) == 0
    assert prof.exists()
    capsys.readouterr()
    assert vmain.main(_argv(prof, "show")) == 0
    assert "actor: real" in capsys.readouterr().out
    assert vmain.main(_argv(prof, "vet")) == 0


def test_cli_reset(tmp_path):
    prof = tmp_path / "profile.stack.yaml"
    assert vmain.main(_argv(prof, "reset")) == 0
    assert prof.exists()


def test_cli_init_with_overrides(tmp_path):
    # 1b: init 이 default + override 쌍 적용 (fixture+open 한 줄).
    prof = tmp_path / "profile.stack.yaml"
    assert vmain.main(_argv(prof, "init", "llm", "fake", "auth", "open")) == 0
    data = prof.read_text()
    assert "llm: fake" in data and "auth: open" in data and "dro: real" in data


def test_cli_init_bad_override(tmp_path):
    prof = tmp_path / "profile.stack.yaml"
    with pytest.raises(SystemExit):
        vmain.main(_argv(prof, "init", "llm", "nope"))


def test_cli_set_patch(tmp_path):
    prof = tmp_path / "profile.stack.yaml"
    vmain.main(_argv(prof, "init"))
    assert vmain.main(_argv(prof, "set", "actor", "fake", "auth", "open")) == 0
    data = prof.read_text()
    assert "actor: fake" in data and "auth: open" in data and "dro: real" in data


@pytest.mark.parametrize(
    "rest",
    [
        ("set",),  # 인자 없음
        ("set", "actor"),  # 홀수 인자
        ("set", "bogus", "x"),  # 미지 knob
        ("set", "actor", "nope"),  # 미지 값
        ("set", "cm", "fake"),  # available:false
    ],
)
def test_cli_set_errors(tmp_path, rest):
    prof = tmp_path / "profile.stack.yaml"
    vmain.main(_argv(prof, "init"))
    with pytest.raises(SystemExit):
        vmain.main(_argv(prof, *rest))


# ── export ──


def test_export_targets(knobs):
    prof = vloader.default_profile(knobs)
    lines = vexport.export_targets(knobs, prof)
    assert "ACTOR_TARGET=production" in lines
    assert "DRO_TARGET=production" in lines
    assert not any("LLM_TARGET" in line for line in lines)  # via:config 미포함
    prof["dro"] = "fake"
    assert "DRO_TARGET=mock" in vexport.export_targets(knobs, prof)


def test_export_main(tmp_path, monkeypatch, capsys):
    prof = tmp_path / "profile.stack.yaml"
    prof.write_text(_profile_text())
    monkeypatch.setenv("DEPLOYMENT_KNOBS", KNOBS)
    monkeypatch.setenv("DEPLOYMENT_FILE", str(prof))
    vexport.main()
    assert "ACTOR_TARGET=production" in capsys.readouterr().out
