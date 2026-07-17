"""300.Actor llm/client — get_gemini_client singleton (invoke 단위).

대상: 300.Actor/src/llm/client.py
  - get_gemini_client() 가 genai.Client() 를 만들어 반환하고 lru_cache 로 singleton 보장.

Vertex 실 client 생성은 비용/credential 의존이므로 genai.Client 를 monkeypatch 로 stub.
async 없음 (순수 동기).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

import src.llm.client as client_mod  # noqa: E402


class _FakeClient:
    """genai.Client() 대체 — 생성 횟수만 셈."""

    instances = 0

    def __init__(self, *args, **kwargs) -> None:
        type(self).instances += 1
        self.args = args
        self.kwargs = kwargs


def _patch_genai(monkeypatch) -> None:
    _FakeClient.instances = 0
    monkeypatch.setattr(client_mod.genai, "Client", _FakeClient)
    client_mod.get_gemini_client.cache_clear()


def test_returns_genai_client_instance(monkeypatch):
    _patch_genai(monkeypatch)
    c = client_mod.get_gemini_client()
    assert isinstance(c, _FakeClient)
    # 인자 없이 생성 — ENV 기반 ADC 사용.
    assert c.args == ()
    assert c.kwargs == {}
    assert _FakeClient.instances == 1
    client_mod.get_gemini_client.cache_clear()


def test_singleton_via_lru_cache(monkeypatch):
    _patch_genai(monkeypatch)
    a = client_mod.get_gemini_client()
    b = client_mod.get_gemini_client()
    assert a is b
    # lru_cache → 두 번째 호출에서 genai.Client 재생성 없음.
    assert _FakeClient.instances == 1
    client_mod.get_gemini_client.cache_clear()


def test_cache_clear_forces_new_instance(monkeypatch):
    _patch_genai(monkeypatch)
    a = client_mod.get_gemini_client()
    client_mod.get_gemini_client.cache_clear()
    b = client_mod.get_gemini_client()
    assert a is not b
    assert _FakeClient.instances == 2
    client_mod.get_gemini_client.cache_clear()
