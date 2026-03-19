"""Session recording and resumption for conversations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .telemetry import SessionMetrics


@dataclass
class MessageRecord:
    """A single message in a conversation.
    
    Roles:
        - "system": system prompt
        - "user": user input
        - "assistant": model response (may include tool_calls)
        - "tool": tool result (includes tool_call_id, name)
    """
    role: str
    content: str
    timestamp: str
    # For assistant messages: list of tool calls requested
    tool_calls: list[dict[str, Any]] | None = None
    # For tool messages: the tool_call_id this result is for
    tool_call_id: str | None = None
    # For tool messages: the tool name
    name: str | None = None


@dataclass
class ConversationRecord:
    """Complete conversation record stored in session files."""
    session_id: str
    start_time: str
    last_updated: str
    messages: list[MessageRecord]
    summary: str | None = None
    metrics: dict[str, Any] | None = None


def _extract_first_user_message(messages: list[MessageRecord]) -> str:
    """Extract the first user message for display purposes."""
    for msg in messages:
        if msg.role == "user" and msg.content.strip():
            text = msg.content.strip()
            return text[:60] + "..." if len(text) > 60 else text
    return "(empty conversation)"


class SessionRecordingService:
    """Records conversations to disk for resumption.
    
    Session files are stored as JSON at:
        .gemini/sessions/session-<timestamp>_<session_id_prefix>.json
    
    The file format mirrors the OpenAI chat message format so that
    messages can be replayed directly into AgentState on resume.
    """

    SESSION_FILE_PREFIX = "session-"

    def __init__(self, project_root: str = ".", sessions_dir: str | None = None):
        self.project_root = Path(project_root)
        
        if sessions_dir:
            self.sessions_dir = Path(sessions_dir)
        else:
            self.sessions_dir = self.project_root / ".gemini" / "sessions"
        
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.current_session_file: Path | None = None
        self.session_id: str | None = None

    def create_session(self, session_id: str) -> None:
        """Create a new session file."""
        self.session_id = session_id
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.SESSION_FILE_PREFIX}{timestamp}_{session_id[:8]}.json"
        self.current_session_file = self.sessions_dir / filename

    def _read_session_data(self) -> dict[str, Any]:
        """Read current session data from disk, or create initial structure."""
        if self.current_session_file and self.current_session_file.exists():
            with open(self.current_session_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "session_id": self.session_id,
            "start_time": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "messages": [],
        }

    def _write_session_data(self, data: dict[str, Any]) -> None:
        """Write session data to disk."""
        if not self.current_session_file:
            return
        data["last_updated"] = datetime.now().isoformat()
        with open(self.current_session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def save_message(
        self,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> None:
        """Record a message to the current session.
        
        Args:
            role: "user", "assistant", or "tool"
            content: message text
            tool_calls: for assistant messages, list of tool call dicts
            tool_call_id: for tool messages, the ID of the tool call this responds to
            name: for tool messages, the tool name
        """
        if not self.current_session_file:
            return  # No active session, silently skip

        data = self._read_session_data()

        message: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        if tool_call_id is not None:
            message["tool_call_id"] = tool_call_id
        if name is not None:
            message["name"] = name

        data["messages"].append(message)
        self._write_session_data(data)

    def resume_session(self, session_id: str) -> ConversationRecord | None:
        """Load a session by ID (matches by prefix).
        
        Also accepts a numeric index (1-based) matching the order
        returned by list_sessions().
        """
        # Try numeric index first
        try:
            idx = int(session_id)
            sessions = self.list_sessions()
            if 1 <= idx <= len(sessions):
                session_id = sessions[idx - 1]["id"]
        except ValueError:
            pass

        # Search by session_id prefix
        for session_file in sorted(self.sessions_dir.glob(f"{self.SESSION_FILE_PREFIX}*.json")):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    stored_id = data.get("session_id", "")
                    if not stored_id.startswith(session_id[:8]):
                        continue
                    messages = [
                        MessageRecord(
                            role=msg["role"],
                            content=msg.get("content", ""),
                            timestamp=msg.get("timestamp", ""),
                            tool_calls=msg.get("tool_calls"),
                            tool_call_id=msg.get("tool_call_id"),
                            name=msg.get("name"),
                        )
                        for msg in data.get("messages", [])
                    ]
                    # Point recorder at this file so new messages append here
                    self.current_session_file = session_file
                    self.session_id = stored_id
                    return ConversationRecord(
                        session_id=stored_id,
                        start_time=data["start_time"],
                        last_updated=data["last_updated"],
                        messages=messages,
                        summary=data.get("summary"),
                        metrics=data.get("metrics"),
                    )
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all available sessions, newest first."""
        sessions = []
        for session_file in sorted(
            self.sessions_dir.glob(f"{self.SESSION_FILE_PREFIX}*.json"),
            reverse=True,
        ):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    msgs = data.get("messages", [])
                    # Skip empty sessions (no user/assistant messages)
                    has_content = any(
                        m.get("role") in ("user", "assistant") for m in msgs
                    )
                    if not has_content:
                        continue

                    msg_records = [
                        MessageRecord(
                            role=m["role"],
                            content=m.get("content", ""),
                            timestamp=m.get("timestamp", ""),
                        )
                        for m in msgs
                    ]
                    sessions.append({
                        "id": data["session_id"],
                        "file": session_file.stem,
                        "start_time": data["start_time"],
                        "last_updated": data["last_updated"],
                        "message_count": len(msgs),
                        "summary": data.get("summary"),
                        "first_message": _extract_first_user_message(msg_records),
                    })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

    def save_metrics(self, metrics: SessionMetrics) -> None:
        """Save session metrics to the current session file."""
        if not self.current_session_file or not self.current_session_file.exists():
            return

        data = self._read_session_data()
        data["metrics"] = metrics.get_summary()
        self._write_session_data(data)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID prefix."""
        for session_file in self.sessions_dir.glob(f"{self.SESSION_FILE_PREFIX}*.json"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("session_id", "").startswith(session_id[:8]):
                        session_file.unlink()
                        return True
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        return False
