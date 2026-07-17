"""knowledge tool 전수 (invoke 단위) — 300.Actor/src/tools/knowledge/__init__.py.

대상: knowledge.load_rejections_section (IPC Section guide 로드, DRO tool step).
함수 단위:
  - _find_knowledge_root : KNOWLEDGE_DIR env (dir/non-dir) · parent walk discovery · 미발견 raise.
  - _section_from_ipc    : falsy/str/list(비-str 필터)/타입오류 → None · 첫 Section letter 추출.
  - _load_section_md     : frontmatter 제거 · 미닫힘 frontmatter · 파일없음 raise. (lru_cache → 각 test 클리어)
  - load_rejections_section : 분류미정 null · 파일없음 swallow(warn) · title 추출 유무.

전략: @knowledge tree 를 tmp_path 에 합성해 KNOWLEDGE_DIR 로 가리킴 (외부 의존 0).
async 는 asyncio.run(...) (pytest-asyncio mark 없이; suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

from src.tools import get as tool_get  # noqa: E402
from src.tools import knowledge as kn  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru():
    """_load_section_md 는 lru_cache — 각 test 가 독립된 tmp tree 를 보도록 매번 클리어."""
    kn._load_section_md.cache_clear()
    yield
    kn._load_section_md.cache_clear()


def _write_section(root: Path, letter: str, body: str) -> Path:
    """root/rejections/by-section/{letter}.md 작성. body 그대로 (frontmatter 포함 가능)."""
    d = root / "rejections" / "by-section"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{letter}.md"
    f.write_text(body, encoding="utf-8")
    return f


_FM = "---\nsection: A\nsection_title: x\n---\n\n"  # 닫힌 frontmatter


# ── registry ──────────────────────────────────────────────────────────────────


def test_handler_registered():
    assert tool_get("knowledge.load_rejections_section") is kn.load_rejections_section


# ── _find_knowledge_root ─────────────────────────────────────────────────────


def test_find_root_env_dir(monkeypatch, tmp_path):
    kdir = tmp_path / "@knowledge"
    kdir.mkdir()
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    assert kn._find_knowledge_root() == kdir


def test_find_root_env_set_but_not_dir_falls_through(monkeypatch, tmp_path):
    """KNOWLEDGE_DIR 가 dir 아니면 무시하고 parent walk 로 폴백 → repo @knowledge 발견."""
    not_a_dir = tmp_path / "nope.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    monkeypatch.setenv("KNOWLEDGE_DIR", str(not_a_dir))
    found = kn._find_knowledge_root()
    assert found.name == "@knowledge"
    assert found.is_dir()
    # 실제 repo tree 폴백을 탔는지 — by-section 존재로 확인
    assert (found / "rejections" / "by-section").is_dir()


def test_find_root_no_env_walks_parents(monkeypatch):
    """env 없음 → __file__/cwd parents walk. repo 안이라 @knowledge 발견."""
    monkeypatch.delenv("KNOWLEDGE_DIR", raising=False)
    found = kn._find_knowledge_root()
    assert found == (ROOT / "@knowledge")


def test_find_root_raises_when_absent(monkeypatch, tmp_path):
    """env 없고 어떤 parent 에도 @knowledge 없으면 FileNotFoundError.

    __file__ 기반 walk 가 repo @knowledge 를 잡지 못하도록 _find_knowledge_root 내부의
    탐색 시작점 두 곳(__file__, cwd) 을 모두 격리된 tmp 하위로 강제.
    """
    monkeypatch.delenv("KNOWLEDGE_DIR", raising=False)
    isolated = tmp_path / "deep" / "leaf"
    isolated.mkdir(parents=True)
    fake_file = isolated / "fakemod.py"
    fake_file.write_text("# x", encoding="utf-8")

    # 탐색 시작점 두 곳(__file__, Path.cwd()) 을 모두 격리된 tmp 하위로 강제 —
    # 어떤 parent 에도 @knowledge 가 없어 raise 분기로 진입.
    monkeypatch.setattr(kn, "__file__", str(fake_file))
    monkeypatch.setattr(kn.Path, "cwd", staticmethod(lambda: isolated))
    with pytest.raises(FileNotFoundError, match="@knowledge directory not found"):
        kn._find_knowledge_root()


# ── _section_from_ipc ────────────────────────────────────────────────────────


def test_section_from_ipc_none():
    assert kn._section_from_ipc(None) is None


def test_section_from_ipc_empty_list():
    assert kn._section_from_ipc([]) is None


def test_section_from_ipc_empty_string():
    assert kn._section_from_ipc("") is None


def test_section_from_ipc_string():
    assert kn._section_from_ipc("B05D 1/00") == "B"


def test_section_from_ipc_string_with_leading_space():
    assert kn._section_from_ipc("  C07D 5/00") == "C"


def test_section_from_ipc_list_first_wins():
    assert kn._section_from_ipc(["A61K 9/00", "B23L 33/00"]) == "A"


def test_section_from_ipc_list_filters_non_str():
    """list 안 non-str 는 걸러지고 첫 유효 str 의 Section 을 본다."""
    assert kn._section_from_ipc([123, None, "D21H 1/00"]) == "D"


def test_section_from_ipc_list_all_non_str_none():
    assert kn._section_from_ipc([1, 2, 3]) is None


def test_section_from_ipc_list_no_match_none():
    """Section letter (A-H) 로 시작하지 않는 코드만 → None."""
    assert kn._section_from_ipc(["Z99Z 1/00", "199 0/00"]) is None


def test_section_from_ipc_wrong_type_none():
    """list/str 아닌 타입 → None 분기."""
    assert kn._section_from_ipc({"ipc": "A"}) is None
    assert kn._section_from_ipc(42) is None


# ── _load_section_md ─────────────────────────────────────────────────────────


def test_load_section_md_strips_frontmatter(monkeypatch, tmp_path):
    kdir = tmp_path / "@knowledge"
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    body = _FM + "## Section A — Human Necessities\nbody text"
    _write_section(kdir, "A", body)
    out = kn._load_section_md("A")
    assert out == "## Section A — Human Necessities\nbody text"
    assert "section_title" not in out  # frontmatter 제거됨


def test_load_section_md_no_frontmatter_passthrough(monkeypatch, tmp_path):
    kdir = tmp_path / "@knowledge"
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    body = "## Section B — Operations\njust body"
    _write_section(kdir, "B", body)
    assert kn._load_section_md("B") == body


def test_load_section_md_unterminated_frontmatter_kept(monkeypatch, tmp_path):
    """'---' 로 시작하지만 닫는 '---' 가 없으면 (end == -1) 본문 그대로 유지."""
    kdir = tmp_path / "@knowledge"
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    body = "---\nsection: C\nno closing fence here"
    _write_section(kdir, "C", body)
    assert kn._load_section_md("C") == body


def test_load_section_md_missing_raises(monkeypatch, tmp_path):
    kdir = tmp_path / "@knowledge"
    (kdir / "rejections" / "by-section").mkdir(parents=True)
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    with pytest.raises(FileNotFoundError, match="section guide missing"):
        kn._load_section_md("G")


# ── load_rejections_section (handler) ────────────────────────────────────────


def test_load_rejections_section_unclassified_null(monkeypatch, tmp_path):
    """IPC 분류 미정 → section letter None → 전 null 응답 (파일 read 자체를 안 함)."""
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path / "@knowledge"))
    out = asyncio.run(kn.load_rejections_section(ipc_codes=None))
    assert out == {"section": {"letter": None, "title": None, "text": None}}


def test_load_rejections_section_with_title(monkeypatch, tmp_path):
    kdir = tmp_path / "@knowledge"
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    body = _FM + "## Section A — 생활필수품 (HUMAN NECESSITIES)\n\nSection 개요 ..."
    _write_section(kdir, "A", body)
    out = asyncio.run(kn.load_rejections_section(ipc_codes=["A61K 9/00"]))
    sec = out["section"]
    assert sec["letter"] == "A"
    assert sec["title"] == "생활필수품 (HUMAN NECESSITIES)"
    assert "Section 개요" in sec["text"]
    assert sec["text"].startswith("## Section A")  # frontmatter 제거 확인


def test_load_rejections_section_title_hyphen_and_h3(monkeypatch, tmp_path):
    """### 헤더 + hyphen(-) 구분자도 title 매칭."""
    kdir = tmp_path / "@knowledge"
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    body = "### Section E - Fixed Constructions\nbody"
    _write_section(kdir, "E", body)
    out = asyncio.run(kn.load_rejections_section(ipc_codes="E04B 1/00"))
    assert out["section"]["letter"] == "E"
    assert out["section"]["title"] == "Fixed Constructions"


def test_load_rejections_section_no_title_line(monkeypatch, tmp_path):
    """본문에 'Section X — TITLE' 헤더가 없으면 title 은 None, text 는 그대로."""
    kdir = tmp_path / "@knowledge"
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    body = "# Some other heading\njust prose, no section header"
    _write_section(kdir, "B", body)
    out = asyncio.run(kn.load_rejections_section(ipc_codes=["B23K 1/00"]))
    assert out["section"]["letter"] == "B"
    assert out["section"]["title"] is None
    assert out["section"]["text"] == body


def test_load_rejections_section_file_missing_swallows(monkeypatch, tmp_path):
    """letter 는 잡혔지만 해당 .md 가 없으면 FileNotFoundError 를 삼키고 title/text=None."""
    kdir = tmp_path / "@knowledge"
    (kdir / "rejections" / "by-section").mkdir(parents=True)  # dir 만, F.md 없음
    monkeypatch.setenv("KNOWLEDGE_DIR", str(kdir))
    out = asyncio.run(kn.load_rejections_section(ipc_codes=["F16H 1/00"]))
    assert out == {"section": {"letter": "F", "title": None, "text": None}}
