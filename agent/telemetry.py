"""Token usage tracking and session metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TokenUsageStats:
    """Token counts and latency from a single API response."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0

    def __add__(self, other: TokenUsageStats) -> TokenUsageStats:
        """Combine two token usage stats."""
        return TokenUsageStats(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            latency_ms=self.latency_ms + other.latency_ms,
        )


@dataclass
class ModelMetrics:
    """Metrics for a single model."""
    model_name: str
    total_requests: int = 0
    total_tokens: TokenUsageStats = field(default_factory=TokenUsageStats)
    total_latency_ms: float = 0.0

    def add_response(self, tokens: TokenUsageStats, latency_ms: float) -> None:
        """Record an API response."""
        self.total_requests += 1
        self.total_tokens = self.total_tokens + tokens
        self.total_latency_ms += latency_ms

    @property
    def avg_latency_ms(self) -> float:
        """Average latency per request."""
        return self.total_latency_ms / self.total_requests if self.total_requests > 0 else 0.0

    @property
    def cache_hit_rate(self) -> float:
        """Percentage of cached tokens vs input tokens."""
        if self.total_tokens.input_tokens == 0:
            return 0.0
        return (self.total_tokens.cached_tokens / self.total_tokens.input_tokens) * 100


@dataclass
class ToolMetrics:
    """Metrics for tool calls."""
    total_calls: int = 0
    total_success: int = 0
    total_fail: int = 0
    total_duration_ms: float = 0.0
    by_name: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_call(self, name: str, success: bool, duration_ms: float) -> None:
        """Record a tool call."""
        self.total_calls += 1
        if success:
            self.total_success += 1
        else:
            self.total_fail += 1
        self.total_duration_ms += duration_ms

        if name not in self.by_name:
            self.by_name[name] = {"count": 0, "success": 0, "fail": 0, "duration_ms": 0.0}

        self.by_name[name]["count"] += 1
        if success:
            self.by_name[name]["success"] += 1
        else:
            self.by_name[name]["fail"] += 1
        self.by_name[name]["duration_ms"] += duration_ms

    @property
    def success_rate(self) -> float:
        """Percentage of successful tool calls."""
        return (self.total_success / self.total_calls * 100) if self.total_calls > 0 else 0.0


@dataclass
class SessionMetrics:
    """Aggregated metrics for an entire session."""
    session_start_time: datetime = field(default_factory=datetime.now)
    models: dict[str, ModelMetrics] = field(default_factory=dict)
    tools: ToolMetrics = field(default_factory=ToolMetrics)

    def get_or_create_model(self, model_name: str) -> ModelMetrics:
        """Get or create metrics for a model."""
        if model_name not in self.models:
            self.models[model_name] = ModelMetrics(model_name=model_name)
        return self.models[model_name]

    def add_api_response(self, model_name: str, tokens: TokenUsageStats, latency_ms: float) -> None:
        """Record an API response."""
        model = self.get_or_create_model(model_name)
        model.add_response(tokens, latency_ms)

    def add_tool_call(self, name: str, success: bool, duration_ms: float) -> None:
        """Record a tool call."""
        self.tools.add_call(name, success, duration_ms)

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens across all models."""
        return sum(m.total_tokens.input_tokens for m in self.models.values())

    @property
    def total_output_tokens(self) -> int:
        """Total output tokens across all models."""
        return sum(m.total_tokens.output_tokens for m in self.models.values())

    @property
    def total_cached_tokens(self) -> int:
        """Total cached tokens across all models."""
        return sum(m.total_tokens.cached_tokens for m in self.models.values())

    @property
    def total_tokens(self) -> int:
        """Total tokens across all models."""
        return sum(m.total_tokens.total_tokens for m in self.models.values())

    @property
    def total_api_time_ms(self) -> float:
        """Total API latency across all models."""
        return sum(m.total_latency_ms for m in self.models.values())

    @property
    def total_tool_time_ms(self) -> float:
        """Total tool execution time."""
        return self.tools.total_duration_ms

    @property
    def session_duration_ms(self) -> float:
        """Wall-clock session duration."""
        return (datetime.now() - self.session_start_time).total_seconds() * 1000

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of session metrics."""
        return {
            "session_duration_ms": self.session_duration_ms,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_tokens,
            "total_api_time_ms": self.total_api_time_ms,
            "total_tool_time_ms": self.total_tool_time_ms,
            "total_api_requests": sum(m.total_requests for m in self.models.values()),
            "total_tool_calls": self.tools.total_calls,
            "tool_success_rate": self.tools.success_rate,
            "models": {
                name: {
                    "requests": m.total_requests,
                    "input_tokens": m.total_tokens.input_tokens,
                    "output_tokens": m.total_tokens.output_tokens,
                    "cached_tokens": m.total_tokens.cached_tokens,
                    "total_tokens": m.total_tokens.total_tokens,
                    "avg_latency_ms": m.avg_latency_ms,
                    "cache_hit_rate": m.cache_hit_rate,
                }
                for name, m in self.models.items()
            },
            "tools": {
                "total_calls": self.tools.total_calls,
                "total_success": self.tools.total_success,
                "total_fail": self.tools.total_fail,
                "success_rate": self.tools.success_rate,
                "by_name": self.tools.by_name,
            },
        }
    
    def _calculate_prompt_char():
        pass

    def _calculate_completion_chars():
        pass

    def _extract_token_usage():
        pass

