from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import httpx
import openai

T = TypeVar("T")

# ── Retryable network error keywords (match against exception messages) ────────
_RETRYABLE_NETWORK_MSGS = (
    "connection reset",
    "connection refused",
    "timed out",
    "timeout",
    "econnreset",
    "etimedout",
    "enotfound",
    "epipe",
    "eai_again",
    "ssl",
    "handshake",
    "fetch failed",
    "remote end closed",
)


@dataclass
class RetryConfig:
    max_attempts: int = 5
    initial_delay_ms: int = 1000   # 1s starting delay
    max_delay_ms: int = 30_000     # 30s cap (matches gemini-cli)
    jitter_factor: float = 0.3    # ±30% random jitter


def is_retryable(error: Exception) -> tuple[bool, int | None]:
    """
    Classify whether an error should be retried.

    Returns:
        (should_retry, retry_after_ms)
        retry_after_ms is the server-specified delay in ms, or None.
    """
    # ── OpenAI-typed errors ────────────────────────────────────────────
    if isinstance(error, openai.RateLimitError):           # 429
        return True, _parse_retry_after(error)

    if isinstance(error, openai.InternalServerError):      # 500-599
        return True, None

    if isinstance(error, openai.APIStatusError):
        # Other 5xx we don't have a specific subclass for
        if error.status_code >= 500:
            return True, None
        # 400, 401, 403, 404 → not retryable
        return False, None

    if isinstance(error, openai.APITimeoutError):
        return True, None

    if isinstance(error, openai.APIConnectionError):
        return True, None

    # ── httpx transport errors ─────────────────────────────────────────
    if isinstance(error, (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        httpx.RemoteProtocolError,
    )):
        return True, None

    # ── Generic network errors by message ─────────────────────────────
    msg = str(error).lower()
    if any(kw in msg for kw in _RETRYABLE_NETWORK_MSGS):
        return True, None

    return False, None


def retry_with_backoff(
    fn: Callable[[], T],
    config: RetryConfig | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> T:
    """
    Call fn() with exponential backoff + jitter on retryable errors.

    Args:
        fn:       Zero-argument callable to attempt.
        config:   Retry tuning (defaults to RetryConfig()).
        on_retry: Optional callback(attempt, error, wait_ms) called before each retry.

    Returns:
        The return value of fn() on success.

    Raises:
        The last exception if all attempts are exhausted or error is not retryable.
    """
    cfg = config or RetryConfig()
    delay_ms = cfg.initial_delay_ms
    last_error: Exception | None = None

    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return fn()

        except Exception as error:
            last_error = error
            should_retry, retry_after_ms = is_retryable(error)

            if not should_retry:
                raise

            if attempt >= cfg.max_attempts:
                raise

            # Determine wait time ──────────────────────────────────────
            if retry_after_ms is not None:
                # Respect Retry-After header; add small positive jitter on top
                wait_ms = float(max(delay_ms, retry_after_ms))
                wait_ms += wait_ms * 0.2 * random.random()
            else:
                # Exponential backoff with ±30% jitter (matches gemini-cli)
                jitter = delay_ms * cfg.jitter_factor * (random.random() * 2 - 1)
                wait_ms = max(0.0, delay_ms + jitter)

            if on_retry:
                on_retry(attempt, error, wait_ms)

            time.sleep(wait_ms / 1000)

            # Double delay for next round, capped at max
            delay_ms = min(cfg.max_delay_ms, delay_ms * 2)

    # Should not reach here, but satisfy type checker
    raise last_error or RuntimeError("retry_with_backoff: no attempts made")


def _parse_retry_after(error: openai.RateLimitError) -> int | None:
    """
    Extract Retry-After from a 429 response header.
    Returns milliseconds, or None if header is absent / unparseable.
    """
    try:
        header = error.response.headers.get("retry-after")
        if header:
            return int(float(header) * 1000)
    except (AttributeError, ValueError, TypeError):
        pass
    return None
