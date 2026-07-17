"""LLM 호출 재시도 / 에러 분류 helper.

ActorSession 의 SDK 호출 위에서 사용:
  - `_classify_llm_error(exc)` — vendor SDK 가 raise 한 raw Exception 을
    `_RetryableLLMError` (5xx/429/network 일시 장애) 또는
    `_PermanentLLMError` (401/400/403 영구 장애) 로 분류.
  - `with_backoff(fn, ...)` — exponential backoff 으로 재시도.
    _RetryableLLMError 만 catch, _PermanentLLMError 는 즉시 raise.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

log = logging.getLogger(__name__)

T = TypeVar("T")


class _RetryableLLMError(Exception):
    """일시적 LLM 호출 에러 — 같은 모델로 재시도하거나 fallback 모델 시도 가능.

    원인 예: 5xx, 429 rate limit, 일시 네트워크 끊김.
    """


class _PermanentLLMError(Exception):
    """영구 LLM 호출 에러 — 재시도 / fallback 모델 모두 무의미.

    원인 예: 401 invalid API key, 400 bad request, 403 permission denied,
    schema validation 반복 실패.
    """


def _classify_llm_error(exc: BaseException) -> Exception:
    """vendor SDK 가 raise 한 raw Exception 을 retry / permanent 로 분류.

    이미 분류된 (_RetryableLLMError / _PermanentLLMError) 는 그대로 반환.
    그 외 unknown 은 보수적으로 retryable 분류.
    """
    if isinstance(exc, _RetryableLLMError | _PermanentLLMError):
        return exc

    # httpx (모든 vendor 의 transport layer)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (429,) or 500 <= status < 600:
            return _RetryableLLMError(f"http {status}: {exc}")
        if status in (400, 401, 403, 404):
            return _PermanentLLMError(f"http {status}: {exc}")
        return _RetryableLLMError(f"http {status}: {exc}")
    if isinstance(exc, httpx.TimeoutException | httpx.RequestError):
        return _RetryableLLMError(f"network: {exc}")

    # Anthropic SDK
    try:
        import anthropic

        if isinstance(
            exc,
            anthropic.RateLimitError | anthropic.APIConnectionError | anthropic.InternalServerError,
        ):
            return _RetryableLLMError(f"anthropic transient: {exc}")
        if isinstance(
            exc,
            anthropic.AuthenticationError
            | anthropic.BadRequestError
            | anthropic.PermissionDeniedError
            | anthropic.NotFoundError,
        ):
            return _PermanentLLMError(f"anthropic permanent: {exc}")
    except ImportError:
        pass

    # OpenAI SDK
    try:
        import openai

        if isinstance(
            exc,
            openai.RateLimitError
            | openai.APIConnectionError
            | openai.InternalServerError
            | openai.APITimeoutError,
        ):
            return _RetryableLLMError(f"openai transient: {exc}")
        if isinstance(
            exc,
            openai.AuthenticationError
            | openai.BadRequestError
            | openai.PermissionDeniedError
            | openai.NotFoundError,
        ):
            return _PermanentLLMError(f"openai permanent: {exc}")
    except ImportError:
        pass

    # Google GenAI / ADK — exception type 이 환경에 따라 다양. 메시지 기반 fallback.
    msg = str(exc).lower()
    if any(
        kw in msg
        for kw in (
            "unauthenticated",
            "invalid api key",
            "permission denied",
            "invalid argument",
            "not found",
            "404",
            "401",
            "403",
        )
    ):
        return _PermanentLLMError(f"google permanent: {exc}")
    if any(
        kw in msg
        for kw in (
            "unavailable",
            "resource exhausted",
            "rate limit",
            "deadline exceeded",
            "timeout",
            "429",
            "500",
            "502",
            "503",
            "504",
        )
    ):
        return _RetryableLLMError(f"google transient: {exc}")

    # 보수적 — unknown 은 retryable 로 분류 (fallback 모델 시도 가능하게)
    return _RetryableLLMError(f"unknown ({type(exc).__name__}): {exc}")


async def with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    backoff_seconds: list[float] | tuple[float, ...] = (2.0, 5.0, 10.0),
    on_attempt: Callable[[int, Exception], None] | None = None,
) -> T:
    """`fn` 을 retryable error 발생 시 exponential backoff 으로 재시도.

    max_attempts 회 시도 후도 실패 시 마지막 _RetryableLLMError 를 raise.
    _PermanentLLMError 는 catch 안 함 (즉시 raise).
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except _RetryableLLMError as e:
            last_exc = e
            if on_attempt is not None:
                try:
                    on_attempt(attempt + 1, e)
                except Exception:  # noqa: BLE001
                    log.exception("on_attempt callback failed")
            if attempt + 1 >= max_attempts:
                break
            delay = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            log.warning(
                "LLM retryable error (attempt %d/%d): %s — sleeping %.1fs",
                attempt + 1,
                max_attempts,
                e,
                delay,
            )
            await asyncio.sleep(delay)
        except _PermanentLLMError:
            raise
    # 루프가 break 한 시점엔 last_exc 가 반드시 채워짐
    assert last_exc is not None  # nosec B101
    raise last_exc
