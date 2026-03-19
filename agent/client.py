from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionChunk

from .config import Config
from .logger import APILogger, create_logger
from .retry import RetryConfig, retry_with_backoff
from .telemetry import TokenUsageStats


def _parse_tool_arguments(raw: str) -> dict[str, Any]:
    """
    Parse tool-call arguments from a (possibly malformed) JSON string.

    The streaming path concatenates delta chunks; occasionally the result is
    not valid JSON (truncated, double-encoded, etc.).  Try a few recovery
    strategies before giving up and returning an empty dict.
    """
    if not raw:
        return {}
    # Fast path — valid JSON
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # Recovery: find the first complete {...} object in the string
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result = json.loads(raw[start : i + 1])
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        break
    import sys
    print(f"[warning] could not parse tool arguments: {raw[:120]!r}", file=sys.stderr)
    return {}


class LLMClient:
    """Thin wrapper around any OpenAI-compatible API."""

    def __init__(self, config: Config, logger: APILogger | None = None):
        self.config = config
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )
        self._logger = logger or create_logger()
        self._retry_config = RetryConfig(
            max_attempts=config.retry_max_attempts,
            initial_delay_ms=config.retry_initial_delay_ms,
            max_delay_ms=config.retry_max_delay_ms,
        )

    def chat(
        self,
        messages: list[ChatCompletionMessageParam],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Send a chat request. Returns a ChatResponse (streaming or not)."""
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": self.config.stream,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False  # avoid index collisions in streaming

        # For streaming, we need usage to be included in the final chunk
        if self.config.stream:
            kwargs["stream_options"] = {"include_usage": True}

        request_id = self._logger.log_request(
            model=self.config.model,
            messages=messages,
            tools=tools,
            stream=self.config.stream,
        )

        def _attempt():
            return self._client.chat.completions.create(**kwargs)

        def _on_retry(attempt: int, error: Exception, wait_ms: float) -> None:
            self._logger.log_error(
                request_id,
                str(error),
                details={"attempt": attempt, "retry_after_ms": round(wait_ms)},
            )

        try:
            start_time = time.time()
            raw = retry_with_backoff(
                _attempt,
                config=self._retry_config,
                on_retry=_on_retry,
            )
            if self.config.stream:
                resp = ChatResponse.from_stream(
                    raw, logger=self._logger, request_id=request_id, start_time=start_time,
                )  # type: ignore[arg-type]
            else:
                resp = ChatResponse.from_response(
                    raw, logger=self._logger, request_id=request_id, start_time=start_time,
                )  # type: ignore[arg-type]
        except Exception as e:
            self._logger.log_error(request_id, str(e))
            raise

        return resp


class ToolCall:
    """A single tool call requested by the model."""

    def __init__(self, id: str, name: str, arguments: dict[str, Any]):
        self.id = id
        self.name = name
        self.arguments = arguments

    def __repr__(self) -> str:
        return f"ToolCall(name={self.name!r}, arguments={self.arguments})"


class ChatResponse:
    """
    Unified response object that works for both streaming and non-streaming.

    Usage (streaming):
        for text in response.text_chunks():
            print(text, end="", flush=True)
        tool_calls = response.tool_calls   # available after iteration
        full_text  = response.content
        usage      = response.usage        # TokenUsageStats
        latency    = response.latency_ms   # float
    """

    def __init__(self):
        self.content: str = ""
        self.tool_calls: list[ToolCall] = []
        self.usage: TokenUsageStats = TokenUsageStats()
        self.latency_ms: float = 0.0
        self._chunks: list[ChatCompletionChunk] = []
        self._stream: Iterator[ChatCompletionChunk] | None = None
        self._logger: APILogger | None = None
        self._request_id: str = ""
        self._start_time: float = 0.0

    @classmethod
    def from_stream(
        cls,
        stream: Iterator[ChatCompletionChunk],
        logger: APILogger | None = None,
        request_id: str = "",
        start_time: float = 0.0,
    ) -> ChatResponse:
        resp = cls()
        resp._stream = stream
        resp._logger = logger
        resp._request_id = request_id
        resp._start_time = start_time
        return resp

    @classmethod
    def from_response(
        cls,
        response: Any,
        logger: APILogger | None = None,
        request_id: str = "",
        start_time: float = 0.0,
    ) -> ChatResponse:
        resp = cls()
        resp._start_time = start_time
        resp.latency_ms = (time.time() - start_time) * 1000 if start_time else 0.0

        choice = response.choices[0]
        resp.content = choice.message.content or ""
        resp.tool_calls = cls._parse_tool_calls(choice.message.tool_calls or [])
        resp._logger = logger
        resp._request_id = request_id

        # Extract token usage from non-streaming response
        resp.usage = cls._extract_usage(response.usage)

        # Log the non-streaming response immediately
        if logger and request_id:
            logger.log_response(
                request_id,
                content=resp.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in resp.tool_calls
                ] or None,
            )

        return resp

    def text_chunks(self) -> Iterator[str]:
        """
        Yields text tokens as they arrive. Must be fully consumed before
        accessing .tool_calls or .content.
        """
        if self._stream is None:
            yield self.content
            return

        # Accumulate tool call fragments across chunks.
        # Each tool call gets a unique index from the API. We use the index
        # as the key and accumulate id/name/arguments across delta chunks.
        tc_accumulator: dict[int, dict[str, Any]] = {}

        for chunk in self._stream:
            # Extract usage from the final chunk (when stream_options.include_usage is set)
            if chunk.usage is not None:
                self.usage = self._extract_usage(chunk.usage)

            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Text token
            if delta.content:
                self.content += delta.content
                yield delta.content

            # Tool call fragments
            for tc in delta.tool_calls or []:
                idx = tc.index
                if idx not in tc_accumulator:
                    tc_accumulator[idx] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    tc_accumulator[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        # FIX: Replace name instead of appending. Tool names
                        # are never split across chunks — only arguments are.
                        # Using += caused concatenation bugs like
                        # "list_dirlist_dir" when the API sent the name in
                        # multiple fragments or re-sent it.
                        tc_accumulator[idx]["name"] = tc.function.name
                    if tc.function.arguments:
                        # Arguments ARE streamed in fragments, so += is correct
                        tc_accumulator[idx]["arguments"] += tc.function.arguments

        # Record latency after full stream consumption
        if self._start_time:
            self.latency_ms = (time.time() - self._start_time) * 1000

        # Parse accumulated tool calls
        for entry in tc_accumulator.values():
            args = _parse_tool_arguments(entry["arguments"])
            self.tool_calls.append(ToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=args,
            ))

        # Log the streaming response after full consumption
        if self._logger and self._request_id:
            self._logger.log_response(
                self._request_id,
                content=self.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in self.tool_calls
                ] or None,
            )

    @staticmethod
    def _parse_tool_calls(raw: list[Any]) -> list[ToolCall]:
        calls = []
        for tc in raw:
            try:
                raw_args = tc.function.arguments or ""
            except AttributeError:
                raw_args = ""
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=_parse_tool_arguments(raw_args)))
        return calls

    @staticmethod
    def _extract_usage(usage: Any) -> TokenUsageStats:
        """Extract token usage from an OpenAI usage object."""
        if usage is None:
            return TokenUsageStats()

        # Standard OpenAI fields
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or 0

        # Cached tokens - some providers include this
        cached_tokens = 0
        prompt_tokens_details = getattr(usage, "prompt_tokens_details", None)
        if prompt_tokens_details:
            cached_tokens = getattr(prompt_tokens_details, "cached_tokens", 0) or 0

        return TokenUsageStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            total_tokens=total_tokens if total_tokens else input_tokens + output_tokens,
        )
