"""300.Actor llm/knowledge — @knowledge static text loader 전수 (invoke 단위).

대상: 300.Actor/src/llm/knowledge.py
  - _find_knowledge_root: KNOWLEDGE_DIR env (dir 면 사용 / dir 아니면 fallback),
    parent walk 로 @knowledge 디렉토리 탐색, 못 찾으면 FileNotFoundError.
  - _load_text: 파일 없으면 FileNotFoundError, 있으면 utf-8 read.
  - load_drafting_summary / load_drafting_raw(part) / load_rejections_summary:
    @knowledge 하위 정확한 path 를 읽어 반환. (모두 lru_cache → cache_clear 로 격리.)

임시 @knowledge 트리는 tmp_path + KNOWLEDGE_DIR env 로 구성.
순수 동기 (async 없음).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

import src.llm.knowledge as kn  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_caches():
    """lru_cache 격리 — 각 테스트가 env 를 갈아끼우므로 캐시를 비운다."""
    kn.load_drafting_summary.cache_clear()
    kn.load_drafting_raw.cache_clear()
    kn.load_rejections_summary.cache_clear()
    yield
    kn.load_drafting_summary.cache_clear()
    kn.load_drafting_raw.cache_clear()
    kn.load_rejections_summary.cache_clear()


def _build_knowledge_tree(root: Path) -> Path:
    """@knowledge/ 하위에 본 모듈이 읽는 3 asset 의 최소 트리를 만든다."""
    kdir = root / "@knowledge"
    (kdir / "drafting" / "raw").mkdir(parents=True)
    (kdir / "rejections").mkdir(parents=True)
    (kdir / "drafting" / "summary.md").write_text("DRAFTING-SUMMARY-한글", encoding="utf-8")
    (kdir / "drafting" / "raw" / "exammanual_03.md").write_text("RAW-PART-03", encoding="utf-8")
    (kdir / "rejections" / "summary.md").write_text("REJECTIONS-SUMMARY", encoding="utf-8")
    return kdir


# ── _find_knowledge_root ──────────────────────────────────────────────────────


def test_find_root_via_knowledge_dir_env(tmp_path, monkeypatch):
    kdir = _build_knowledge_tree(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    assert kn._find_knowledge_root() == kdir


def test_find_root_env_not_a_dir_falls_through_to_parent_walk(tmp_path, monkeypatch):
    """KNOWLEDGE_DIR 이 디렉토리가 아니면(파일) 무시하고 parent walk fallback."""
    not_a_dir = tmp_path / "bogus.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGE_DIR", str(not_a_dir))
    # cwd 를 repo 루트로 두면 parent walk 가 실제 repo @knowledge 를 찾는다.
    monkeypatch.chdir(ROOT)
    found = kn._find_knowledge_root()
    assert found == (ROOT / "@knowledge")
    assert found.is_dir()


def test_find_root_parent_walk_no_env(tmp_path, monkeypatch):
    """env 미설정 → __file__ / cwd 의 parent walk 로 repo @knowledge 발견."""
    monkeypatch.delenv("KNOWLEDGE_DIR", raising=False)
    found = kn._find_knowledge_root()
    assert found == (ROOT / "@knowledge")


def test_find_root_not_found_raises(tmp_path, monkeypatch):
    """env 없고, __file__·cwd 둘 다 @knowledge 가 없는 격리 트리 → FileNotFoundError.

    monkeypatch 로 모듈의 __file__ 과 cwd 를 @knowledge 없는 tmp 트리로 옮긴다.
    """
    monkeypatch.delenv("KNOWLEDGE_DIR", raising=False)
    isolated = tmp_path / "iso" / "deep"
    isolated.mkdir(parents=True)
    monkeypatch.chdir(isolated)
    # 모듈 파일 위치도 @knowledge 가 없는 곳으로 위장 (parent walk 가 못 찾도록).
    fake_file = isolated / "fake_knowledge.py"
    fake_file.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(kn, "__file__", str(fake_file))
    with pytest.raises(FileNotFoundError, match="@knowledge directory not found"):
        kn._find_knowledge_root()


# ── _load_text ────────────────────────────────────────────────────────────────


def test_load_text_reads_utf8(tmp_path):
    p = tmp_path / "asset.md"
    p.write_text("내용-content", encoding="utf-8")
    assert kn._load_text(p) == "내용-content"


def test_load_text_missing_raises(tmp_path):
    p = tmp_path / "nope.md"
    with pytest.raises(FileNotFoundError, match="@knowledge asset missing"):
        kn._load_text(p)


# ── load_drafting_summary ──────────────────────────────────────────────────────


def test_load_drafting_summary(tmp_path, monkeypatch):
    kdir = _build_knowledge_tree(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    assert kn.load_drafting_summary() == "DRAFTING-SUMMARY-한글"


def test_load_drafting_summary_cached(tmp_path, monkeypatch):
    """lru_cache(maxsize=1) — 두 번째 호출은 파일을 다시 읽지 않음(파일 삭제해도 동일 값)."""
    kdir = _build_knowledge_tree(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    first = kn.load_drafting_summary()
    (kdir / "drafting" / "summary.md").unlink()
    assert kn.load_drafting_summary() == first


# ── load_drafting_raw ──────────────────────────────────────────────────────────


def test_load_drafting_raw_part(tmp_path, monkeypatch):
    kdir = _build_knowledge_tree(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    assert kn.load_drafting_raw("03") == "RAW-PART-03"


def test_load_drafting_raw_missing_part_raises(tmp_path, monkeypatch):
    kdir = _build_knowledge_tree(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    with pytest.raises(FileNotFoundError, match="@knowledge asset missing"):
        kn.load_drafting_raw("99")


# ── load_rejections_summary ────────────────────────────────────────────────────


def test_load_rejections_summary(tmp_path, monkeypatch):
    kdir = _build_knowledge_tree(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    assert kn.load_rejections_summary() == "REJECTIONS-SUMMARY"
