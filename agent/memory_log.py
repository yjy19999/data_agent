"""
Memory compression logger.

Each time the agent compresses its conversation history a JSON record is
written to ``memory_logs/`` so you can audit exactly what was summarised,
what the resulting <state_snapshot> looks like, and how many tokens were saved.

Log file naming:
    memory_logs/compression_<YYYYMMDD_HHMMSS_mmm>_<session_id>.json

Log record fields:
    timestamp           ISO-8601 UTC timestamp
    session_id          Agent session ID
    status              "compressed" | "content_truncated" | "hard_truncated"
                        | "failed_inflated" | "failed_empty_summary"
    original_tokens     Estimated tokens before compression
    new_tokens          Estimated tokens after compression
    tokens_saved        original_tokens - new_tokens
    reduction_pct       Percentage reduction (0.0–100.0)
    messages_before     Number of history messages before compression
    messages_after      Number of history messages after compression (0 if failed)
    snapshot            Extracted <state_snapshot> XML (empty for non-LLM paths)
    history_before      Full message list that was fed into compression (no system msgs)
    history_after       Full message list that resulted (no system msgs; empty if failed)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai.types.chat import ChatCompletionMessageParam

_DEFAULT_LOG_DIR = Path("memory_logs")


def _extract_snapshot(messages: list[ChatCompletionMessageParam]) -> str:
    """Return the first <state_snapshot> block found in any user message."""
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content") or ""
        if isinstance(content, str) and "<state_snapshot>" in content:
            return content
    return ""


def _strip_system(
    messages: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    return [m for m in messages if m.get("role") != "system"]


class MemoryLogger:
    """
    Writes one JSON file per compression event to ``log_dir``.

    Usage::

        logger = MemoryLogger()
        logger.log(
            session_id="abc123",
            status="compressed",
            original_tokens=50_000,
            new_tokens=12_000,
            messages_before=state.messages,
            messages_after=result.new_messages,
        )
    """

    def __init__(self, log_dir: str | Path = _DEFAULT_LOG_DIR) -> None:
        self.log_dir = Path(log_dir)

    def log(
        self,
        session_id: str,
        status: str,
        original_tokens: int,
        new_tokens: int,
        messages_before: list[ChatCompletionMessageParam],
        messages_after: list[ChatCompletionMessageParam] | None,
    ) -> Path:
        """
        Write a compression event record and return the path of the log file.

        Args:
            session_id:      Agent session identifier.
            status:          Compression outcome label.
            original_tokens: Estimated token count before compression.
            new_tokens:      Estimated token count after compression.
            messages_before: Full message list (incl. system) before compression.
            messages_after:  Full message list (incl. system) after compression,
                             or None for failed/non-replacing outcomes.
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%d_%H%M%S_") + f"{ts.microsecond // 1000:03d}"
        filename = f"compression_{ts_str}_{session_id}.json"

        history_before = _strip_system(messages_before)
        history_after = _strip_system(messages_after) if messages_after else []

        tokens_saved = original_tokens - new_tokens
        reduction_pct = (
            round(tokens_saved / original_tokens * 100, 1) if original_tokens else 0.0
        )

        record: dict[str, Any] = {
            "timestamp": ts.isoformat(),
            "session_id": session_id,
            "status": status,
            "original_tokens": original_tokens,
            "new_tokens": new_tokens,
            "tokens_saved": tokens_saved,
            "reduction_pct": reduction_pct,
            "messages_before": len(history_before),
            "messages_after": len(history_after),
            "snapshot": _extract_snapshot(history_after),
            "history_before": history_before,
            "history_after": history_after,
        }

        path = self.log_dir / filename
        path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        return path
