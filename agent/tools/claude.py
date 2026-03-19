"""
Claude Code tool implementations — all 16 tools in one place.

Tool names match Claude Code exactly:
  Bash, Glob, Grep, LS, Read, Edit, MultiEdit, Write,
  NotebookRead, NotebookEdit,
  WebFetch, WebSearch,
  exit_plan_mode,
  TodoRead, TodoWrite,
  Task
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

from .base import Tool
from .files import GlobTool as _GlobBase, GrepTool as _GrepBase, MultiEditTool as _MultiEditBase, _max_read_chars

# Re-export tools whose implementations live in specialised modules
from .notebook import NotebookEditTool, NotebookReadTool
from .plan import ExitPlanModeTool
from .task import TaskTool
from .todo import TodoReadTool, TodoWriteTool
from .web import WebFetchTool, WebSearchTool

__all__ = [
    # file I/O + shell (defined below)
    "BashTool",
    "GlobTool",
    "GrepTool",
    "LSTool",
    "ReadTool",
    "EditTool",
    "MultiEditTool",
    "WriteTool",
    # notebooks
    "NotebookReadTool",
    "NotebookEditTool",
    # web
    "WebFetchTool",
    "WebSearchTool",
    # plan / workflow
    "ExitPlanModeTool",
    "TodoReadTool",
    "TodoWriteTool",
    "TaskTool",
]


# ── File I/O ───────────────────────────────────────────────────────────────────

_READ_DEFAULT_LIMIT = 2000
_READ_MAX_LINE_CHARS = 2000


class ReadTool(Tool):
    name = "Read"
    description = (
        "Reads a file from the local filesystem. You can access any file directly by using this tool.\n"
        "Assume this tool is able to read all files on the machine. If the User provides a path to a "
        "file assume that path is valid. It is okay to read a file that does not exist; an error will "
        "be returned.\n\n"
        "Usage:\n"
        "- The file_path parameter must be an absolute path, not a relative path\n"
        "- By default, it reads up to 2000 lines starting from the beginning of the file\n"
        "- You can optionally specify a line offset and limit (especially handy for long files), "
        "but it's recommended to read the whole file by not providing these parameters\n"
        "- Any lines longer than 2000 characters will be truncated\n"
        "- Results are returned using cat -n format, with line numbers starting at 1\n"
        "- This tool can only read files, not directories. To read a directory, use an ls command "
        "via the Bash tool.\n"
        "- You can call multiple tools in a single response. It is always better to speculatively "
        "read multiple potentially useful files in parallel.\n"
        "- If you read a file that exists but has empty contents you will receive a system reminder "
        "warning in place of file contents."
    )

    def run(self, file_path: str, offset: int = 1, limit: int = _READ_DEFAULT_LIMIT) -> str:
        """
        Args:
            file_path: The absolute path to the file to read.
            offset: The line number to start reading from. Only provide if the file is too large to read at once.
            limit: The number of lines to read. Only provide if the file is too large to read at once.
        """
        p = Path(file_path).expanduser()
        if not p.exists():
            return f"[error] file not found: {file_path}"
        if not p.is_file():
            return f"[error] not a file: {file_path}"
        try:
            all_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(0, offset - 1)
            end = min(len(all_lines), start + limit)
            selected = all_lines[start:end]

            if not selected:
                return "[empty]"

            def fmt(i: int, line: str) -> str:
                if len(line) > _READ_MAX_LINE_CHARS:
                    line = line[:_READ_MAX_LINE_CHARS] + " [line truncated]"
                return f"{start + i + 1:>4}\t{line}"

            output = "\n".join(fmt(i, line) for i, line in enumerate(selected))

            if end < len(all_lines):
                output += (
                    f"\n\n[File has {len(all_lines)} lines total. "
                    f"Showing lines {start + 1}–{end}. "
                    f"Use offset={end + 1} to read more.]"
                )
            return output
        except Exception as exc:
            return f"[error] {exc}"


class WriteTool(Tool):
    name = "Write"
    description = "Write text to a file, creating it (and parent dirs) if needed."

    def run(self, file_path: str, content: str) -> str:
        """
        Args:
            file_path: Destination file path.
            content: Full text content to write.
        """
        p = Path(file_path).expanduser()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            return f"[ok] wrote {lines} lines to {file_path}"
        except Exception as exc:
            return f"[error] {exc}"


class EditTool(Tool):
    name = "Edit"
    description = (
        "Performs exact string replacements in files.\n\n"
        "Usage:\n"
        "- You must use your `Read` tool at least once in the conversation before editing. "
        "This tool will error if you attempt an edit without reading the file.\n"
        "- When editing text from Read tool output, ensure you preserve the exact indentation "
        "(tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format "
        "is: spaces + line number + tab. Everything after that tab is the actual file content to "
        "match. Never include any part of the line number prefix in the old_string or new_string.\n"
        "- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless "
        "explicitly required.\n"
        "- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.\n"
        "- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger "
        "string with more surrounding context to make it unique or use `replace_all` to change "
        "every instance of `old_string`.\n"
        "- Use `replace_all` for replacing and renaming strings across the file. This parameter "
        "is useful if you want to rename a variable for instance."
    )

    def run(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        """
        Args:
            file_path: The absolute path to the file to modify.
            old_string: The text to replace (must be different from new_string).
            new_string: The text to replace it with (must be different from old_string).
            replace_all: Replace all occurrences of old_string. Defaults to False.
        """
        p = Path(file_path).expanduser()
        if not p.exists():
            return f"[error] file not found: {file_path}"
        if not p.is_file():
            return f"[error] not a file: {file_path}"
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"[error] could not read: {exc}"

        count = content.count(old_string)
        if count == 0:
            snippet = repr(old_string[:80]) + ("..." if len(old_string) > 80 else "")
            first_line = next((l.strip() for l in old_string.splitlines() if l.strip()), "")
            hint = ""
            if first_line:
                lines = content.splitlines()
                nearby = [
                    f"  line {i+1}: {l}"
                    for i, l in enumerate(lines)
                    if first_line in l
                ]
                if nearby:
                    hint = "\nNearby lines containing the first line of old_string:\n" + "\n".join(nearby[:5])
            return f"[error] old_string not found: {snippet}{hint}"
        if count > 1 and not replace_all:
            snippet = repr(old_string[:80]) + ("..." if len(old_string) > 80 else "")
            return f"[error] old_string matches {count} times (must be unique): {snippet}"

        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
        try:
            p.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return f"[error] could not write: {exc}"
        replaced = count if replace_all else 1
        return f"[ok] edit applied to {file_path}" + (f" ({replaced} occurrences replaced)" if replace_all else "")


# ── Glob / Grep / MultiEdit — Claude Code names over the base implementations ──

class GlobTool(_GlobBase):
    """Claude Code `Glob` tool — same logic as the base, correct name."""
    name = "Glob"
    description = (
        "Find files by glob pattern (e.g. '**/*.py', 'src/*.ts'). "
        "Returns a newline-separated list of matching paths."
    )


class GrepTool(_GrepBase):
    """Claude Code `Grep` tool — same logic as the base, correct name."""
    name = "Grep"
    description = (
        "Search for lines matching a pattern in files. "
        "Returns matching lines with file path and line number. "
        "Use the 'path' parameter (not 'file_path') to specify the file or directory to search."
    )


class MultiEditTool(_MultiEditBase):
    """Claude Code `MultiEdit` tool — same logic as the base, correct name."""
    name = "MultiEdit"
    description = (
        "Apply multiple find-and-replace edits to a single file atomically. "
        "All edits are validated first; if any fail, the file is not modified."
    )


# ── Shell ──────────────────────────────────────────────────────────────────────

class BashTool(Tool):
    name = "Bash"
    description = (
        "Run a bash command and return its stdout + stderr. "
        "Use for git, running tests, installing packages, compiling, etc."
    )

    def run(self, command: str, timeout: int = 120) -> str:
        """
        Args:
            command: The bash command to execute.
            timeout: Max seconds to wait before killing the process. Defaults to 120.
        """
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            parts = []
            if result.stdout.strip():
                parts.append(result.stdout.rstrip())
            if result.stderr.strip():
                parts.append(f"[stderr]\n{result.stderr.rstrip()}")
            if not parts:
                parts.append(f"[exit {result.returncode}]")
            output = "\n".join(parts)
            limit = _max_read_chars()
            if len(output) > limit:
                output = output[:limit]
                output += f"\n\n[truncated — output exceeded {limit:,} chars]"
            return output
        except subprocess.TimeoutExpired:
            return f"[error] timed out after {timeout}s"
        except Exception as exc:
            return f"[error] {exc}"


# ── Directory listing ──────────────────────────────────────────────────────────

class LSTool(Tool):
    name = "LS"
    description = "List files and directories at a given path with sizes."

    def run(self, path: str = ".") -> str:
        """
        Args:
            path: Directory to list. Defaults to current working directory.
        """
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"[error] path not found: {path}"
        if not p.is_dir():
            return f"[error] not a directory: {path}"
        entries = []
        for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if item.is_dir():
                entries.append(f"  {item.name}/")
            else:
                entries.append(f"  {item.name:<40} {_human_size(item.stat().st_size):>8}")
        header = f"{p}\n{'─' * 50}"
        return header + "\n" + "\n".join(entries) if entries else f"{p}\n[empty]"


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
