from __future__ import annotations

import fnmatch
import os
import hashlib
import time
from pathlib import Path

from .base import Tool


def _max_read_chars() -> int:
    return int(os.getenv("LLM_READ_MAX_CHARS", "100000"))


def _max_read_many_chars() -> int:
    return int(os.getenv("LLM_READ_MANY_MAX_CHARS", "200000"))


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read the text contents of a file. "
        "Returns the file content with line numbers, "
        "preceded by metadata including mtime and SHA-256 hash. "
        "Fails clearly if the file doesn't exist or isn't text."
    )

    def run(self, path: str, start_line: int = 1, end_line: int = 0) -> str:
        """
        Args:
            path: Path to the file (absolute or relative to cwd).
            start_line: First line to return, 1-indexed. Defaults to 1.
            end_line: Last line to return (inclusive). 0 means read to end.
        """
        p = Path(path).expanduser()
        if not p.exists():
            return f"[error] file not found: {path}"
        if not p.is_file():
            return f"[error] not a file: {path}"
        try:
            # 1. Gather metadata
            stats = p.stat()
            mtime = stats.st_mtime
            readable_mtime = time.ctime(mtime)
            
            raw_content = p.read_bytes()
            file_hash = hashlib.sha256(raw_content).hexdigest()
            
            # 2. Process text content
            text_content = raw_content.decode("utf-8", errors="replace")
            lines = text_content.splitlines()
            start = max(0, start_line - 1)
            end = len(lines) if end_line == 0 else end_line
            selected = lines[start:end]
            
            # 3. Format output
            metadata = [
                f"File: {path}",
                f"Size: {_human_size(stats.st_size)}",
                f"Modified: {readable_mtime} (timestamp: {mtime})",
                f"SHA-256: {file_hash}",
                f"Lines: {start_line}-{end if end_line != 0 else len(lines)} of {len(lines)}",
                "─" * 50
            ]
            
            numbered = "\n".join(f"{start + i + 1:>4}  {line}" for i, line in enumerate(selected))
            output = "\n".join(metadata) + "\n" + (numbered or "[empty file]")

            limit = _max_read_chars()
            if len(output) > limit:
                output = output[:limit]
                last_newline = output.rfind("\n")
                if last_newline > 0:
                    output = output[:last_newline]
                last_shown = output.count("\n") + start
                output += (
                    f"\n\n[truncated — output exceeded {limit:,} chars. "
                    f"File has {len(lines)} lines total. "
                    f"Use start_line/end_line to read the remaining lines "
                    f"(next: start_line={last_shown + 1}).]"
                )

            return output
            
        except Exception as exc:
            return f"[error] {exc}"


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Write text content to a file, creating it (and any parent directories) "
        "if it doesn't exist, or overwriting it if it does."
    )

    def run(self, path: str, content: str) -> str:
        """
        Args:
            path: Path to the file to write.
            content: The full text content to write.
        """
        p = Path(path).expanduser()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            return f"[ok] wrote {lines} lines to {path}"
        except Exception as exc:
            return f"[error] {exc}"


class GlobTool(Tool):
    name = "glob"
    description = (
        "Find files matching a glob pattern (e.g. '**/*.py', 'src/*.ts'). "
        "Returns a newline-separated list of matching paths."
    )

    def run(self, pattern: str, directory: str = ".") -> str:
        """
        Args:
            pattern: Glob pattern to match (e.g. '**/*.py').
            directory: Root directory to search from. Defaults to cwd.
        """
        base = Path(directory).expanduser().resolve()
        if not base.exists():
            return f"[error] directory not found: {directory}"
        try:
            matches = sorted(str(p.relative_to(base)) for p in base.glob(pattern))
            if not matches:
                return f"[no matches] pattern {pattern!r} in {directory}"
            return "\n".join(matches)
        except Exception as exc:
            return f"[error] {exc}"


class GrepTool(Tool):
    name = "grep"
    description = (
        "Search for lines matching a substring or pattern in files. "
        "Returns matching lines with file name and line number. "
        "Use the 'path' parameter (not 'file_path') to specify the file or directory to search."
    )

    def run(self, pattern: str, path: str = ".", glob: str = "*", max_results: int = 50) -> str:
        """
        Args:
            pattern: Text or substring to search for (case-insensitive).
            path: File or directory to search in. IMPORTANT: this parameter is called 'path', not 'file_path'.
            glob: File name pattern to filter by (e.g. '*.py'). Defaults to all files.
            max_results: Maximum number of matching lines to return.
        """
        base = Path(path).expanduser().resolve()
        results: list[str] = []

        files: list[Path] = []
        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = [f for f in base.rglob("*") if f.is_file() and fnmatch.fnmatch(f.name, glob)]
        else:
            return f"[error] path not found: {path}"

        pattern_lower = pattern.lower()

        for file in sorted(files):
            try:
                for i, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if pattern_lower in line.lower():
                        rel = file.relative_to(base) if base.is_dir() else file
                        results.append(f"{rel}:{i}: {line.rstrip()}")
                        if len(results) >= max_results:
                            results.append(f"[truncated — more than {max_results} matches]")
                            return "\n".join(results)
            except Exception:
                continue

        return "\n".join(results) if results else f"[no matches] {pattern!r} in {path}"


class ListDirTool(Tool):
    name = "list_dir"
    description = (
        "List files and directories at a given path. "
        "Shows file sizes and distinguishes files from directories."
    )

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
                size = item.stat().st_size
                size_str = _human_size(size)
                entries.append(f"  {item.name:<40} {size_str:>8}")

        header = f"{p}\n{'─' * 50}"
        return header + "\n" + "\n".join(entries) if entries else f"{p}\n[empty]"


class ReadManyFilesTool(Tool):
    name = "read_many_files"
    description = (
        "Read multiple files at once. "
        "Returns the contents of all files concatenated with headers. "
        "Useful for gathering context from multiple related files quickly."
    )

    def run(self, paths: list[str]) -> str:
        """
        Args:
            paths: List of file paths to read.
        """
        reader = ReadFileTool()
        results = []
        total_chars = 0
        many_limit = _max_read_many_chars()
        for path in paths:
            content = reader.run(path)
            if total_chars + len(content) > many_limit:
                remaining = many_limit - total_chars
                if remaining > 0:
                    content = content[:remaining]
                    results.append(content)
                skipped = paths[paths.index(path):]
                results.append(
                    f"\n[truncated — combined output exceeded {many_limit:,} chars. "
                    f"Skipped {len(skipped)} file(s): {', '.join(skipped)}. "
                    f"Read them individually with read_file.]"
                )
                break
            results.append(content)
            results.append("\n" + "=" * 80 + "\n")
            total_chars += len(content)

        return "\n".join(results)


class MultiEditTool(Tool):
    name = "multi_edit"
    description = (
        "Apply multiple find-and-replace edits to a single file atomically. "
        "All edits are validated first; if any fail, the file is not modified. "
        "Each old_string must match exactly once in the file. "
        "Edits are applied in order, so later edits see the result of earlier ones. "
        "Prefer this over calling write_file when modifying an existing file."
    )

    # Override schema manually: the base class can't auto-generate list-of-dicts
    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit.",
                },
                "edits": {
                    "type": "array",
                    "description": "Ordered list of edits to apply.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string": {
                                "type": "string",
                                "description": "Exact text to find. Must appear exactly once.",
                            },
                            "new_string": {
                                "type": "string",
                                "description": "Text to replace it with.",
                            },
                        },
                        "required": ["old_string", "new_string"],
                    },
                },
            },
            "required": ["path", "edits"],
        }

    def run(self, path: str, edits: list) -> str:
        """
        Args:
            path: Path to the file to edit.
            edits: List of {old_string, new_string} dicts to apply in order.
        """
        p = Path(path).expanduser()

        if not p.exists():
            return f"[error] file not found: {path}"
        if not p.is_file():
            return f"[error] not a file: {path}"
        if not edits:
            return "[error] edits list is empty"

        try:
            original = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"[error] could not read file: {exc}"

        # ── Validate all edits before touching the file ────────────────
        errors = []
        for i, edit in enumerate(edits):
            old = edit.get("old_string", "")
            if not old:
                errors.append(f"  edit {i+1}: old_string is empty")
                continue
            count = original.count(old)
            if count == 0:
                # Show a snippet of context to help the model debug
                snippet = repr(old[:60]) + ("..." if len(old) > 60 else "")
                errors.append(f"  edit {i+1}: old_string not found: {snippet}")
            elif count > 1:
                snippet = repr(old[:60]) + ("..." if len(old) > 60 else "")
                errors.append(
                    f"  edit {i+1}: old_string matches {count} times (must be unique): {snippet}"
                )

        if errors:
            return "[error] validation failed — file not modified:\n" + "\n".join(errors)

        # ── Apply edits sequentially to an in-memory copy ─────────────
        content = original
        applied = []
        for i, edit in enumerate(edits):
            old = edit["old_string"]
            new = edit.get("new_string", "")
            # Re-check uniqueness after prior edits may have changed the content
            count = content.count(old)
            if count != 1:
                return (
                    f"[error] edit {i+1}: old_string now matches {count} times after "
                    f"previous edits — file not modified"
                )
            content = content.replace(old, new, 1)
            applied.append(f"  edit {i+1}: replaced {len(old)}→{len(new)} chars")

        # ── Write atomically only after all edits succeed ──────────────
        try:
            p.write_text(content, encoding="utf-8")
        except Exception as exc:
            return f"[error] could not write file: {exc}"

        lines_before = original.count("\n") + 1
        lines_after = content.count("\n") + 1
        summary = f"[ok] {len(edits)} edit(s) applied to {path}"
        if lines_before != lines_after:
            summary += f" ({lines_before}→{lines_after} lines)"
        return summary + "\n" + "\n".join(applied)


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
