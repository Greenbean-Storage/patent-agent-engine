"""300.Actor llm/retry — _classify_llm_error + with_backoff 전수 (invoke 단위).

대상: 300.Actor/src/llm/retry.py
  - _classify_llm_error: 이미 분류된 에러 passthrough / httpx (429·5xx·4xx·기타·network) /
    anthropic (transient·permanent) / openai (transient·permanent) /
    google 메시지 기반 (permanent·transient) / unknown=retryable.
  - with_backoff: 1회 성공 / retryable 재시도 후 성공 / max 초과 후 마지막 raise /
    permanent 즉시 raise / on_attempt 콜백 (+콜백 자체 예외 삼킴).

anthropic SDK 는 venv 에 미설치 — 실제 isinstance 분기를 타도록 fake anthropic 모듈을
sys.modules 에 주입. openai 는 venv 에 설치되어 있어 실 예외 클래스로 검증.
asyncio.sleep 는 monkeypatch 로 no-op 화 (backoff 지연 제거).
async 는 asyncio.run(...) (pytest-asyncio mark 없이; 기존 suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import httpx
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "300.Actor"))

import src.llm.retry as retry_mod  # noqa: E402
from src.llm.retry import (  # noqa: E402
    _classify_llm_error,
    _PermanentLLMError,
    _RetryableLLMError,
    with_backoff,
)


# ── fake anthropic 모듈 (venv 미설치 → 실 isinstance 분기 강제) ──────────────────


@pytest.fixture
def fake_anthropic(monkeypatch):
    """sys.modules 에 anthropic stub 주입 — retry 의 `import anthropic` 가 성공하고
    isinstance 분기를 실제로 타게 한다. 각 예외 클래스는 고유 타입."""
    mod = types.ModuleType("anthropic")

    class RateLimitError(Exception): ...

    class APIConnectionError(Exception): ...

    class InternalServerError(Exception): ...

    class AuthenticationError(Exception): ...

    class BadRequestError(Exception): ...

    class PermissionDeniedError(Exception): ...

    class NotFoundError(Exception): ...

    for cls in (
        RateLimitError,
        APIConnectionError,
        InternalServerError,
        AuthenticationError,
        BadRequestError,
        PermissionDeniedError,
        NotFoundError,
    ):
        setattr(mod, cls.__name__, cls)

    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return mod


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://x")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(f"{status}", request=req, response=resp)


# ── _classify_llm_error: 이미 분류된 에러 passthrough ────────────────────────────


def test_already_retryable_passthrough():
    e = _RetryableLLMError("x")
    assert _classify_llm_error(e) is e


def test_already_permanent_passthrough():
    e = _PermanentLLMError("x")
    assert _classify_llm_error(e) is e


# ── _classify_llm_error: httpx ──────────────────────────────────────────────────


def test_httpx_429_is_retryable():
    assert isinstance(_classify_llm_error(_http_status_error(429)), _RetryableLLMError)


def test_httpx_503_is_retryable():
    assert isinstance(_classify_llm_error(_http_status_error(503)), _RetryableLLMError)


def test_httpx_500_is_retryable():
    assert isinstance(_classify_llm_error(_http_status_error(500)), _RetryableLLMError)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_httpx_4xx_is_permanent(status):
    assert isinstance(_classify_llm_error(_http_status_error(status)), _PermanentLLMError)


def test_httpx_other_status_defaults_retryable():
    """5xx/429/4xx-allowlist 외 (예: 418) → 보수적 retryable."""
    assert isinstance(_classify_llm_error(_http_status_error(418)), _RetryableLLMError)


def test_httpx_timeout_is_retryable():
    exc = httpx.TimeoutException("slow")
    assert isinstance(_classify_llm_error(exc), _RetryableLLMError)


def test_httpx_request_error_is_retryable():
    exc = httpx.ConnectError("refused")
    assert isinstance(_classify_llm_error(exc), _RetryableLLMError)


# ── _classify_llm_error: anthropic (fake 모듈) ──────────────────────────────────


def test_anthropic_rate_limit_retryable(fake_anthropic):
    exc = fake_anthropic.RateLimitError("429")
    assert isinstance(_classify_llm_error(exc), _RetryableLLMError)


def test_anthropic_connection_retryable(fake_anthropic):
    exc = fake_anthropic.APIConnectionError("net")
    assert isinstance(_classify_llm_error(exc), _RetryableLLMError)


def test_anthropic_internal_server_retryable(fake_anthropic):
    exc = fake_anthropic.InternalServerError("500")
    assert isinstance(_classify_llm_error(exc), _RetryableLLMError)


def test_anthropic_auth_permanent(fake_anthropic):
    exc = fake_anthropic.AuthenticationError("bad key")
    assert isinstance(_classify_llm_error(exc), _PermanentLLMError)


def test_anthropic_bad_request_permanent(fake_anthropic):
    exc = fake_anthropic.BadRequestError("400")
    assert isinstance(_classify_llm_error(exc), _PermanentLLMError)


def test_anthropic_permission_denied_permanent(fake_anthropic):
    exc = fake_anthropic.PermissionDeniedError("403")
    assert isinstance(_classify_llm_error(exc), _PermanentLLMError)


def test_anthropic_not_found_permanent(fake_anthropic):
    exc = fake_anthropic.NotFoundError("404")
    assert isinstance(_classify_llm_error(exc), _PermanentLLMError)


def test_anthropic_import_error_branch_swallowed(monkeypatch):
    """anthropic import 실패(미설치) → except ImportError 분기 → 이후 단계로 진행.
    google 키워드 없는 메시지 → 최종 unknown retryable."""
    monkeypatch.setitem(sys.modules, "anthropic", None)  # import anthropic → ImportError
    out = _classify_llm_error(RuntimeError("totally novel failure xyzzy"))
    assert isinstance(out, _RetryableLLMError)


# ── _classify_llm_error: openai (실 SDK 설치됨) ─────────────────────────────────


def test_openai_rate_limit_retryable():
    import openai

    exc = openai.RateLimitError.__new__(openai.RateLimitError)
    Exception.__init__(exc, "rate")
    assert isinstance(_classify_llm_error(exc), _RetryableLLMError)


def test_openai_authentication_permanent():
    import openai

    exc = openai.AuthenticationError.__new__(openai.AuthenticationError)
    Exception.__init__(exc, "auth")
    assert isinstance(_classify_llm_error(exc), _PermanentLLMError)


def test_openai_import_error_branch_swallowed(monkeypatch):
    """openai import 실패 → except ImportError 분기 → 이후 google/unknown 단계로 진행."""
    monkeypatch.setitem(sys.modules, "openai", None)  # import openai → ImportError
    out = _classify_llm_error(RuntimeError("totally novel failure qwerty"))
    assert isinstance(out, _RetryableLLMError)


# ── _classify_llm_error: google 메시지 기반 ─────────────────────────────────────


@pytest.mark.parametrize(
    "msg",
    [
        "UNAUTHENTICATED: caller identity",
        "invalid API key",
        "permission denied for resource",
        "invalid argument provided",
        "model not found",
        "got 404 from upstream",
        "401 unauthorized",
        "403 forbidden",
    ],
)
def test_google_permanent_keywords(msg):
    out = _classify_llm_error(RuntimeError(msg))
    assert isinstance(out, _PermanentLLMError)


@pytest.mark.parametrize(
    "msg",
    [
        "service UNAVAILABLE",
        "RESOURCE EXHAUSTED",
        "rate limit hit",
        "deadline exceeded",
        "request timeout",
        "got 429",
        "500 internal",
        "502 bad gateway",
        "503 service",
        "504 gateway timeout",
    ],
)
def test_google_transient_keywords(msg):
    out = _classify_llm_error(RuntimeError(msg))
    assert isinstance(out, _RetryableLLMError)


def test_unknown_defaults_retryable():
    out = _classify_llm_error(RuntimeError("some entirely opaque condition"))
    assert isinstance(out, _RetryableLLMError)
    assert "unknown" in str(out)


# ── with_backoff ────────────────────────────────────────────────────────────────


def _no_sleep(monkeypatch) -> None:
    async def _fake_sleep(_d):
        return None

    monkeypatch.setattr(retry_mod.asyncio, "sleep", _fake_sleep)


def test_with_backoff_first_try_success(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    async def _fn():
        calls["n"] += 1
        return "ok"

    out = asyncio.run(with_backoff(_fn))
    assert out == "ok"
    assert calls["n"] == 1


def test_with_backoff_retries_then_succeeds(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    async def _fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _RetryableLLMError(f"transient {calls['n']}")
        return "recovered"

    out = asyncio.run(with_backoff(_fn, max_attempts=3))
    assert out == "recovered"
    assert calls["n"] == 3


def test_with_backoff_exhausts_and_raises_last(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    async def _fn():
        calls["n"] += 1
        raise _RetryableLLMError(f"fail {calls['n']}")

    with pytest.raises(_RetryableLLMError, match="fail 3"):
        asyncio.run(with_backoff(_fn, max_attempts=3))
    assert calls["n"] == 3


def test_with_backoff_permanent_raises_immediately(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    async def _fn():
        calls["n"] += 1
        raise _PermanentLLMError("nope")

    with pytest.raises(_PermanentLLMError, match="nope"):
        asyncio.run(with_backoff(_fn, max_attempts=5))
    # permanent → 첫 시도에서 즉시 raise (재시도 없음).
    assert calls["n"] == 1


def test_with_backoff_on_attempt_callback_invoked(monkeypatch):
    _no_sleep(monkeypatch)
    seen: list[tuple[int, str]] = []

    async def _fn():
        raise _RetryableLLMError("boom")

    def _on_attempt(attempt: int, exc: Exception) -> None:
        seen.append((attempt, str(exc)))

    with pytest.raises(_RetryableLLMError):
        asyncio.run(with_backoff(_fn, max_attempts=2, on_attempt=_on_attempt))
    assert seen == [(1, "boom"), (2, "boom")]


def test_with_backoff_on_attempt_callback_exception_swallowed(monkeypatch):
    _no_sleep(monkeypatch)

    async def _fn():
        raise _RetryableLLMError("boom")

    def _bad_callback(attempt: int, exc: Exception) -> None:
        raise ValueError("callback exploded")

    # 콜백 자체 예외는 삼켜지고, 재시도 흐름은 정상 진행 → 최종 _RetryableLLMError.
    with pytest.raises(_RetryableLLMError, match="boom"):
        asyncio.run(with_backoff(_fn, max_attempts=2, on_attempt=_bad_callback))


def test_with_backoff_uses_last_backoff_when_attempts_exceed_list(monkeypatch):
    """max_attempts 가 backoff_seconds 길이보다 크면 마지막 지연을 재사용 (index clamp)."""
    delays: list[float] = []

    async def _fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(retry_mod.asyncio, "sleep", _fake_sleep)

    async def _fn():
        raise _RetryableLLMError("x")

    with pytest.raises(_RetryableLLMError):
        asyncio.run(with_backoff(_fn, max_attempts=4, backoff_seconds=(1.0, 2.0)))
    # 4 attempts → 3 sleeps; index clamp 으로 [1.0, 2.0, 2.0].
    assert delays == [1.0, 2.0, 2.0]
