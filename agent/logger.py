"""
Agent trace logger with pluggable output formats.

Supports multiple trace formats, configured via ``LLM_LOG_FORMAT`` in ``.env``:

- ``openhands``      — OpenHands event-stream format (action/observation pairs)
- ``swe-agent``      — SWE-agent trajectory format (thought/action/observation steps)
- ``mini-swe-agent`` — Mini-SWE-agent format (flat OpenAI-style message list)
- ``both``           — write both openhands + swe-agent simultaneously
- ``all``            — write all three formats simultaneously
- ``none``           — disable logging

Each session produces one trace file per format in the ``api_logs/`` directory.
"""
from __future__ import annotations

import json
import os
import time as _time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════
# Abstract base — defines the logging interface used by Agent + LLMClient
# ═══════════════════════════════════════════════════════════════════════

class APILogger(ABC):
    """
    Abstract logger interface.

    All concrete loggers and the composite logger implement this interface,
    so the agent code only ever calls these methods.
    """

    @abstractmethod
    def start_session(self, session_id: str, model: str) -> None: ...

    @abstractmethod
    def log_request(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> str: ...

    @abstractmethod
    def log_response(
        self,
        request_id: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> None: ...

    @abstractmethod
    def log_tool_exec(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        duration_ms: float,
    ) -> None: ...

    @abstractmethod
    def log_error(
        self, request_id: str, error: str, details: dict[str, Any] | None = None
    ) -> None: ...

    # Optional hooks with default no-ops
    def log_usage(self, usage: dict[str, Any] | None, latency_ms: float = 0) -> None:
        pass

    def log_user_message(self, content: str) -> None:
        pass

    def log_condensation(self, original_tokens: int, new_tokens: int, status: str) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# NullLogger — disabled logging
# ═══════════════════════════════════════════════════════════════════════

class NullLogger(APILogger):
    """No-op logger when logging is disabled."""

    def start_session(self, session_id: str, model: str) -> None:
        pass

    def log_request(self, model, messages, tools=None, stream=False) -> str:
        return ""

    def log_response(self, request_id, content, tool_calls=None, error=None) -> None:
        pass

    def log_tool_exec(self, tool_name, arguments, result, success, duration_ms) -> None:
        pass

    def log_error(self, request_id, error, details=None) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# OpenHands format
# ═══════════════════════════════════════════════════════════════════════

# Map tool names to OpenHands-style action/observation types
_OH_ACTION_MAP = {
    "shell": "run", "Bash": "run",
    "read_file": "read", "Read": "read", "ReadFile": "read",
    "read_many_files": "read", "ReadManyFiles": "read", "NotebookRead": "read",
    "write_file": "write", "Write": "write", "WriteFile": "write", "NotebookEdit": "write",
    "Edit": "edit", "multi_edit": "edit", "MultiEdit": "edit", "Replace": "edit",
    "glob": "search", "Glob": "search", "grep": "search", "Grep": "search", "GrepSearch": "search",
    "list_dir": "read", "LS": "read", "ListDirectory": "read",
    "WebFetch": "browse", "WebSearch": "browse", "web_fetch": "browse", "web_search": "browse",
    "write_plan": "think", "exit_plan_mode": "think",
    "TodoRead": "recall", "TodoWrite": "think", "Task": "think", "SaveMemory": "think",
}


class OpenHandsLogger(APILogger):
    """
    OpenHands event-stream format.

    Produces a JSON array of action/observation events::

        [
          {"id": 0, "source": "agent", "action": "message", "args": {...}},
          {"id": 1, "source": "agent", "action": "write", "args": {...}},
          {"id": 2, "source": "environment", "observation": "write", "content": "...", "extras": {...}},
          ...
        ]
    """

    def __init__(self, logs_dir: Path):
        self._logs_dir = logs_dir
        self._trace_file: Path | None = None
        self._events: list[dict[str, Any]] = []
        self._next_id = 0
        self._pending_request: dict[str, Any] | None = None

    def start_session(self, session_id: str, model: str) -> None:
        self._events = []
        self._next_id = 0
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._trace_file = self._logs_dir / f"trace_openhands_{ts}_{session_id}.json"
        self._flush()

    def log_request(self, model, messages, tools=None, stream=False) -> str:
        if self._trace_file is None:
            self.start_session("auto", model)
        request_id = f"req_{self._next_id}"
        self._pending_request = {
            "model": model,
            "stream": stream,
            "messages": messages,
            "tools": [t.get("function", {}).get("name", "?") for t in tools] if tools else None,
        }
        return request_id

    def log_response(self, request_id, content, tool_calls=None, error=None) -> None:
        req = self._pending_request
        self._pending_request = None

        llm_metrics: dict[str, Any] = {}
        if req:
            llm_metrics["model"] = req["model"]
            llm_metrics["tools_available"] = req["tools"]

        args: dict[str, Any] = {"content": content}
        if error:
            args["error"] = error

        event: dict[str, Any] = {
            "id": self._next_id,
            "timestamp": datetime.now().isoformat(),
            "source": "agent",
            "action": "message",
            "args": args,
        }
        if tool_calls:
            event["tool_call_metadata"] = {"tool_calls": tool_calls}
        if llm_metrics:
            event["llm_metrics"] = llm_metrics

        self._next_id += 1
        self._events.append(event)
        self._flush()

    def log_usage(self, usage, latency_ms=0) -> None:
        if not self._events:
            return
        last = self._events[-1]
        if last.get("source") == "agent" and last.get("action") == "message":
            metrics = last.get("llm_metrics", {})
            if usage:
                metrics.update(usage)
            metrics["latency_ms"] = round(latency_ms, 1)
            last["llm_metrics"] = metrics
            self._flush()

    def log_tool_exec(self, tool_name, arguments, result, success, duration_ms) -> None:
        action_type = _OH_ACTION_MAP.get(tool_name, tool_name)

        action_event = {
            "id": self._next_id,
            "timestamp": datetime.now().isoformat(),
            "source": "agent",
            "action": action_type,
            "args": {**arguments, "_tool_name": tool_name},
            "message": f"Running tool: {tool_name}",
        }
        self._next_id += 1
        self._events.append(action_event)

        obs_event = {
            "id": self._next_id,
            "timestamp": datetime.now().isoformat(),
            "source": "environment",
            "cause": action_event["id"],
            "observation": action_type,
            "content": result,
            "extras": {
                "tool_name": tool_name,
                "success": success,
                "duration_ms": round(duration_ms, 1),
            },
            "message": (
                f"Tool `{tool_name}` executed successfully."
                if success
                else f"Tool `{tool_name}` failed."
            ),
        }
        self._next_id += 1
        self._events.append(obs_event)
        self._flush()

    def log_user_message(self, content) -> None:
        event = {
            "id": self._next_id,
            "timestamp": datetime.now().isoformat(),
            "source": "user",
            "action": "message",
            "args": {"content": content},
        }
        self._next_id += 1
        self._events.append(event)
        self._flush()

    def log_error(self, request_id, error, details=None) -> None:
        if self._pending_request is not None:
            self._pending_request = None
        event = {
            "id": self._next_id,
            "timestamp": datetime.now().isoformat(),
            "source": "environment",
            "observation": "error",
            "content": error,
            "extras": details or {},
            "message": f"Error: {error[:200]}",
        }
        self._next_id += 1
        self._events.append(event)
        self._flush()

    def log_condensation(self, original_tokens, new_tokens, status) -> None:
        event = {
            "id": self._next_id,
            "timestamp": datetime.now().isoformat(),
            "source": "agent",
            "action": "condensation",
            "args": {
                "original_tokens": original_tokens,
                "new_tokens": new_tokens,
                "status": status,
            },
            "message": f"Context compressed: {original_tokens} -> {new_tokens} tokens ({status})",
        }
        self._next_id += 1
        self._events.append(event)
        self._flush()

    def _flush(self) -> None:
        if self._trace_file is None:
            return
        try:
            with open(self._trace_file, "w", encoding="utf-8") as f:
                json.dump(self._events, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# SWE-agent format
# ═══════════════════════════════════════════════════════════════════════

class SWEAgentLogger(APILogger):
    """
    SWE-agent trajectory (.traj) format.

    Produces a JSON object with::

        {
          "environment": "agent_cli",
          "trajectory": [
            {
              "action": "write_file ...",
              "observation": "[ok] wrote 34 lines...",
              "response": "I'll create a file...",
              "thought": "Need to write the implementation",
              "state": {"open_file": "n/a", "working_dir": "/workspace"},
              "execution_time": 0.5,
              "query": [...messages...],
              "extra_info": {}
            },
            ...
          ],
          "history": [
            {"role": "system", "content": "...", "message_type": "thought"},
            {"role": "user", "content": "...", "message_type": "action"},
            ...
          ],
          "info": {
            "model_stats": {...},
            "exit_status": "completed",
            "swe_agent_version": "cc_rewrite_api_1.0"
          }
        }
    """

    def __init__(self, logs_dir: Path):
        self._logs_dir = logs_dir
        self._trace_file: Path | None = None
        self._model = ""
        self._session_id = ""
        # SWE-agent structures
        self._trajectory: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._model_stats: dict[str, Any] = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "api_calls": 0,
            "total_cost": 0.0,
        }
        # Pending state for building trajectory steps
        self._pending_request: dict[str, Any] | None = None
        self._pending_response: dict[str, Any] | None = None
        self._pending_query: list[dict[str, Any]] = []
        self._step_start: float = 0.0

    def start_session(self, session_id: str, model: str) -> None:
        self._model = model
        self._session_id = session_id
        self._trajectory = []
        self._history = []
        self._model_stats = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "api_calls": 0,
            "total_cost": 0.0,
        }
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._trace_file = self._logs_dir / f"trace_sweagent_{ts}_{session_id}.traj"
        self._flush()

    def log_request(self, model, messages, tools=None, stream=False) -> str:
        if self._trace_file is None:
            self.start_session("auto", model)
        self._pending_query = list(messages)
        self._step_start = _time.time()
        self._pending_request = {
            "model": model,
            "messages": messages,
        }
        return f"req_{len(self._trajectory)}"

    def log_response(self, request_id, content, tool_calls=None, error=None) -> None:
        self._pending_request = None
        self._model_stats["api_calls"] += 1

        # Store the response for pairing with tool exec
        self._pending_response = {
            "content": content,
            "tool_calls": tool_calls,
            "error": error,
        }

        # Add assistant message to history
        hist_entry: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "agent": "main",
            "message_type": "action",
        }
        if tool_calls:
            hist_entry["thought"] = content
            actions = []
            for tc in tool_calls:
                name = tc.get("name", "?")
                args = tc.get("arguments", {})
                actions.append(f"{name}({json.dumps(args, ensure_ascii=False)})")
            hist_entry["action"] = "; ".join(actions)
            hist_entry["tool_calls"] = [
                {
                    "function": {
                        "name": tc.get("name", "?"),
                        "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                    },
                    "id": tc.get("id", ""),
                    "type": "function",
                }
                for tc in tool_calls
            ]
        else:
            hist_entry["action"] = None
        self._history.append(hist_entry)

        # If no tool calls, this is a pure text response — emit a trajectory step
        if not tool_calls:
            step = {
                "action": "(text response)",
                "observation": "",
                "response": content,
                "thought": content,
                "state": {"open_file": "n/a", "working_dir": os.getcwd()},
                "execution_time": _time.time() - self._step_start,
                "query": self._pending_query,
                "extra_info": {"error": error} if error else {},
            }
            self._trajectory.append(step)
            self._pending_response = None
            self._flush()

    def log_usage(self, usage, latency_ms=0) -> None:
        if usage:
            self._model_stats["total_input_tokens"] += usage.get("input_tokens", 0)
            self._model_stats["total_output_tokens"] += usage.get("output_tokens", 0)
            self._model_stats["latency_ms"] = round(latency_ms, 1)
        self._flush()

    def log_tool_exec(self, tool_name, arguments, result, success, duration_ms) -> None:
        # Build the action string (SWE-agent style: "tool_name arg1 arg2" or structured)
        action_str = _build_swe_action_string(tool_name, arguments)

        # Extract thought from the pending response
        thought = ""
        response_text = ""
        if self._pending_response:
            response_text = self._pending_response.get("content", "")
            thought = response_text

        # Build trajectory step
        step: dict[str, Any] = {
            "action": action_str,
            "observation": result,
            "response": response_text,
            "thought": thought,
            "state": {
                "open_file": arguments.get("path", arguments.get("file_path", "n/a")),
                "working_dir": os.getcwd(),
            },
            "execution_time": round(duration_ms / 1000, 4),
            "query": self._pending_query,
            "extra_info": {
                "tool_name": tool_name,
                "arguments": arguments,
                "success": success,
                "duration_ms": round(duration_ms, 1),
            },
        }
        self._trajectory.append(step)

        # Clear pending response after first tool (thought applies to first tool only)
        self._pending_response = None

        # Add observation to history
        self._history.append({
            "role": "user",
            "content": result,
            "agent": "main",
            "message_type": "observation",
        })

        self._flush()

    def log_user_message(self, content) -> None:
        self._history.append({
            "role": "user",
            "content": content,
            "agent": "main",
            "message_type": "action",
        })
        self._flush()

    def log_error(self, request_id, error, details=None) -> None:
        if self._pending_request is not None:
            self._pending_request = None

        step = {
            "action": "(error)",
            "observation": error,
            "response": "",
            "thought": "",
            "state": {"open_file": "n/a", "working_dir": os.getcwd()},
            "execution_time": 0.0,
            "query": self._pending_query,
            "extra_info": {"error": error, "details": details or {}},
        }
        self._trajectory.append(step)

        self._history.append({
            "role": "user",
            "content": f"[error] {error}",
            "agent": "main",
            "message_type": "observation",
        })
        self._flush()

    def log_condensation(self, original_tokens, new_tokens, status) -> None:
        step = {
            "action": "(condensation)",
            "observation": f"Context compressed: {original_tokens} -> {new_tokens} tokens ({status})",
            "response": "",
            "thought": f"Context too large ({original_tokens} tokens), compressing to {new_tokens}",
            "state": {"open_file": "n/a", "working_dir": os.getcwd()},
            "execution_time": 0.0,
            "query": [],
            "extra_info": {
                "original_tokens": original_tokens,
                "new_tokens": new_tokens,
                "status": status,
            },
        }
        self._trajectory.append(step)
        self._flush()

    def _flush(self) -> None:
        if self._trace_file is None:
            return
        traj = {
            "environment": "agent_cli",
            "trajectory": self._trajectory,
            "history": self._history,
            "info": {
                "model_stats": self._model_stats,
                "exit_status": None,
                "model": self._model,
                "session_id": self._session_id,
                "swe_agent_version": "cc_rewrite_api_1.0",
            },
        }
        try:
            with open(self._trace_file, "w", encoding="utf-8") as f:
                json.dump(traj, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# Mini-SWE-agent format
# ═══════════════════════════════════════════════════════════════════════

class MiniSWEAgentLogger(APILogger):
    """
    Mini-SWE-agent trajectory format.

    Produces a JSON object with a flat OpenAI-style message list::

        {
          "trajectory_format": "mini-swe-agent-1",
          "messages": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "...", "tool_calls": [...]},
            {"role": "tool", "content": "...", "tool_call_id": "..."},
            ...
          ],
          "info": {
            "exit_status": null,
            "submission": null,
            "model_stats": {...},
            "config": {...}
          }
        }
    """

    def __init__(self, logs_dir: Path):
        self._logs_dir = logs_dir
        self._trace_file: Path | None = None
        self._model = ""
        self._session_id = ""
        self._messages: list[dict[str, Any]] = []
        self._model_stats: dict[str, Any] = {
            "instance_cost": 0.0,
            "api_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }
        # Track pending tool calls so we can pair tool results
        self._pending_tool_calls: list[dict[str, Any]] = []

    def start_session(self, session_id: str, model: str) -> None:
        self._model = model
        self._session_id = session_id
        self._messages = []
        self._model_stats = {
            "instance_cost": 0.0,
            "api_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._trace_file = self._logs_dir / f"trace_miniswe_{ts}_{session_id}.json"
        self._flush()

    def log_request(self, model, messages, tools=None, stream=False) -> str:
        if self._trace_file is None:
            self.start_session("auto", model)
        # On first request, capture the system message if present
        if not self._messages and messages:
            for msg in messages:
                role = msg.get("role", "")
                if role == "system" and not any(
                    m.get("role") == "system" for m in self._messages
                ):
                    self._messages.append({
                        "role": "system",
                        "content": msg.get("content", ""),
                    })
        return f"req_{self._model_stats['api_calls']}"

    def log_response(self, request_id, content, tool_calls=None, error=None) -> None:
        self._model_stats["api_calls"] += 1

        msg: dict[str, Any] = {
            "role": "assistant",
            "content": content or "",
        }

        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(
                            tc.get("arguments", {}), ensure_ascii=False
                        ),
                    },
                }
                for tc in tool_calls
            ]
            self._pending_tool_calls = list(tool_calls)

        if error:
            msg["_error"] = error

        self._messages.append(msg)
        self._flush()

    def log_usage(self, usage, latency_ms=0) -> None:
        if usage:
            self._model_stats["total_input_tokens"] += usage.get("input_tokens", 0)
            self._model_stats["total_output_tokens"] += usage.get("output_tokens", 0)
        self._flush()

    def log_tool_exec(self, tool_name, arguments, result, success, duration_ms) -> None:
        # Find the matching tool_call_id from pending calls
        tool_call_id = ""
        for i, tc in enumerate(self._pending_tool_calls):
            if tc.get("name") == tool_name:
                tool_call_id = tc.get("id", "")
                self._pending_tool_calls.pop(i)
                break

        self._messages.append({
            "role": "tool",
            "content": result,
            "tool_call_id": tool_call_id,
            "name": tool_name,
        })
        self._flush()

    def log_user_message(self, content) -> None:
        self._messages.append({
            "role": "user",
            "content": content,
        })
        self._flush()

    def log_error(self, request_id, error, details=None) -> None:
        # Log errors as a system-level message
        self._messages.append({
            "role": "system",
            "content": f"[error] {error}",
            "_details": details or {},
        })
        self._flush()

    def log_condensation(self, original_tokens, new_tokens, status) -> None:
        self._messages.append({
            "role": "system",
            "content": (
                f"[condensation] Context compressed: "
                f"{original_tokens} -> {new_tokens} tokens ({status})"
            ),
        })
        self._flush()

    def _flush(self) -> None:
        if self._trace_file is None:
            return
        traj = {
            "trajectory_format": "mini-swe-agent-1",
            "messages": self._messages,
            "info": {
                "exit_status": None,
                "submission": None,
                "model_stats": self._model_stats,
                "config": {
                    "model": self._model,
                    "session_id": self._session_id,
                    "agent_type": "cc_rewrite_api_1.0",
                },
            },
        }
        try:
            with open(self._trace_file, "w", encoding="utf-8") as f:
                json.dump(traj, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def _build_swe_action_string(tool_name: str, arguments: dict[str, Any]) -> str:
    """Build a SWE-agent style action string from tool name and arguments."""
    if tool_name in ("shell", "Bash"):
        return arguments.get("command", "")
    if tool_name in ("read_file", "Read", "ReadFile"):
        path = arguments.get("path", arguments.get("file_path", "?"))
        return f"open {path}"
    if tool_name in ("write_file", "Write", "WriteFile"):
        path = arguments.get("path", arguments.get("file_path", "?"))
        content = arguments.get("content", "")
        return f"create {path}\n{content}\nend_of_edit"
    if tool_name in ("Edit", "multi_edit", "MultiEdit", "Replace"):
        path = arguments.get("path", arguments.get("file_path", "?"))
        old = arguments.get("old_string", arguments.get("old_str", ""))
        new = arguments.get("new_string", arguments.get("new_str", ""))
        return f"edit {path}\n{old}\n---\n{new}\nend_of_edit"
    if tool_name in ("glob", "Glob"):
        pattern = arguments.get("pattern", "*")
        directory = arguments.get("directory", arguments.get("path", "."))
        return f"find_file {pattern} {directory}"
    if tool_name in ("grep", "Grep", "GrepSearch"):
        pattern = arguments.get("pattern", "")
        path = arguments.get("path", ".")
        return f"search_file \"{pattern}\" {path}"
    if tool_name in ("list_dir", "LS", "ListDirectory"):
        path = arguments.get("path", ".")
        return f"ls {path}"
    # Fallback: tool_name with JSON args
    return f"{tool_name} {json.dumps(arguments, ensure_ascii=False)}"


# ═══════════════════════════════════════════════════════════════════════
# Composite logger — writes multiple formats simultaneously
# ═══════════════════════════════════════════════════════════════════════

class CompositeLogger(APILogger):
    """Wraps multiple loggers and delegates all calls to each."""

    def __init__(self, loggers: list[APILogger]):
        self._loggers = loggers

    def start_session(self, session_id, model) -> None:
        for lg in self._loggers:
            lg.start_session(session_id, model)

    def log_request(self, model, messages, tools=None, stream=False) -> str:
        rid = ""
        for lg in self._loggers:
            rid = lg.log_request(model, messages, tools, stream)
        return rid

    def log_response(self, request_id, content, tool_calls=None, error=None) -> None:
        for lg in self._loggers:
            lg.log_response(request_id, content, tool_calls, error)

    def log_usage(self, usage, latency_ms=0) -> None:
        for lg in self._loggers:
            lg.log_usage(usage, latency_ms)

    def log_tool_exec(self, tool_name, arguments, result, success, duration_ms) -> None:
        for lg in self._loggers:
            lg.log_tool_exec(tool_name, arguments, result, success, duration_ms)

    def log_user_message(self, content) -> None:
        for lg in self._loggers:
            lg.log_user_message(content)

    def log_error(self, request_id, error, details=None) -> None:
        for lg in self._loggers:
            lg.log_error(request_id, error, details)

    def log_condensation(self, original_tokens, new_tokens, status) -> None:
        for lg in self._loggers:
            lg.log_condensation(original_tokens, new_tokens, status)


# ═══════════════════════════════════════════════════════════════════════
# Factory — creates the right logger from LLM_LOG_FORMAT env var
# ═══════════════════════════════════════════════════════════════════════

def create_logger(
    log_format: str | None = None,
    logs_dir: str = "api_logs",
) -> APILogger:
    """
    Create a logger based on format string.

    Args:
        log_format: One of ``"openhands"``, ``"swe-agent"``, ``"mini-swe-agent"``,
                    ``"both"``, ``"all"``, ``"none"``.
                    If None, reads from ``LLM_LOG_FORMAT`` env var (default: ``"openhands"``).
        logs_dir: Directory for trace files.

    Returns:
        An APILogger instance.
    """
    if log_format is None:
        log_format = os.getenv("LLM_LOG_FORMAT", "openhands")

    log_format = log_format.strip().lower().replace("_", "-")
    logs_path = Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    if log_format == "none":
        return NullLogger()
    elif log_format == "swe-agent":
        return SWEAgentLogger(logs_path)
    elif log_format == "mini-swe-agent":
        return MiniSWEAgentLogger(logs_path)
    elif log_format == "both":
        return CompositeLogger([
            OpenHandsLogger(logs_path),
            SWEAgentLogger(logs_path),
        ])
    elif log_format == "all":
        return CompositeLogger([
            OpenHandsLogger(logs_path),
            SWEAgentLogger(logs_path),
            MiniSWEAgentLogger(logs_path),
        ])
    else:
        # Default: openhands
        return OpenHandsLogger(logs_path)
