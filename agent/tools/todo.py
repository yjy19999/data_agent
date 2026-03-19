from __future__ import annotations

import json
from pathlib import Path

from .base import Tool

_TODO_FILE = ".agent_todos.json"
_VALID_STATUSES = {"pending", "in_progress", "completed"}


class TodoReadTool(Tool):
    name = "TodoRead"
    description = (
        "Read the current task/todo list. "
        "Returns all todos with their id, content, and status."
    )

    def run(self) -> str:
        todos = _load()
        if not todos:
            return "[todo list is empty]"

        sections: dict[str, list[str]] = {"in_progress": [], "pending": [], "completed": []}
        for t in todos:
            status = t.get("status", "pending")
            icon   = {"in_progress": "◉", "pending": "○", "completed": "✓"}.get(status, "?")
            line   = f"  {icon} [{t['id']}] {t['content']}"
            sections.get(status, sections["pending"]).append(line)

        lines = []
        if sections["in_progress"]:
            lines.append("In progress:")
            lines.extend(sections["in_progress"])
        if sections["pending"]:
            lines.append("Pending:")
            lines.extend(sections["pending"])
        if sections["completed"]:
            lines.append("Completed:")
            lines.extend(sections["completed"])

        return "\n".join(lines)

    # Override schema: run() takes no arguments
    @property
    def parameters_schema(self):
        return {"type": "object", "properties": {}, "required": []}


class TodoWriteTool(Tool):
    name = "TodoWrite"
    description = (
        "Create or update the task/todo list. "
        "Pass the full list of todos — this replaces all existing todos. "
        "Each todo needs 'content' and optionally 'status' (pending/in_progress/completed)."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Complete list of todos to save.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "The task description.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Task status. Defaults to 'pending'.",
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
            "required": ["todos"],
        }

    def run(self, todos: list) -> str:
        """
        Args:
            todos: List of {content, status} dicts.
        """
        if not isinstance(todos, list):
            return "[error] todos must be a list"

        normalized = []
        for i, t in enumerate(todos):
            if not isinstance(t, dict):
                return f"[error] todo {i} must be an object with 'content'"
            content = t.get("content", "").strip()
            if not content:
                return f"[error] todo {i} has empty content"
            status = t.get("status", "pending")
            if status not in _VALID_STATUSES:
                return f"[error] todo {i} has invalid status {status!r} (use pending/in_progress/completed)"
            normalized.append({"id": i + 1, "content": content, "status": status})

        _save(normalized)
        counts = {s: sum(1 for t in normalized if t["status"] == s) for s in _VALID_STATUSES}
        return (
            f"[ok] saved {len(normalized)} todos "
            f"({counts['in_progress']} in progress, "
            f"{counts['pending']} pending, "
            f"{counts['completed']} completed)"
        )


def _load() -> list[dict]:
    path = Path(_TODO_FILE)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(todos: list[dict]) -> None:
    Path(_TODO_FILE).write_text(
        json.dumps(todos, indent=2, ensure_ascii=False), encoding="utf-8"
    )
