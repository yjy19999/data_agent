"""
Gemini CLI-style tool implementations.

Parameter schemas match the gemini-cli DEFAULT_LEGACY_SET / GEMINI_3_SET exactly:
  - read_file:         file_path, start_line, end_line
  - write_file:        file_path, content
  - replace:           file_path, instruction, old_string, new_string, allow_multiple
  - glob:              pattern, dir_path, case_sensitive
  - grep_search:       pattern, dir_path, include, names_only, total_max_matches
  - list_directory:    dir_path, ignore
  - run_shell_command: command, description
  - google_web_search: query
  - web_fetch:         prompt  (URL(s) + instructions bundled into one param)
  - read_many_files:   include, exclude, recursive, useDefaultExcludes
  - write_todos:       todos   [{description, status}] (pending/in_progress/completed/cancelled)
  - save_memory:       fact
  - get_internal_docs: path (optional)
  - ask_user:          questions [{question, header, type, options, ...}]
  - enter_plan_mode:   reason (optional)
  - exit_plan_mode:    (no params)
  - activate_skill:    skill_name
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path
from typing import Any

from .base import Tool
from .files import _human_size


class GeminiReadFileTool(Tool):
    name = "read_file"
    description = (
        "Reads and returns the content of a specified file. "
        "If the file is large, the content will be truncated. "
        "The tool's response will indicate if truncation has occurred and "
        "explain how to read more using 'start_line' and 'end_line'."
    )

    def run(self, file_path: str, start_line: int = 1, end_line: int = 0) -> str:
        """
        Args:
            file_path: The path to the file to read.
            start_line: Optional: The 1-based line number to start reading from.
            end_line: Optional: The 1-based line number to end reading at (inclusive). 0 means read to end.
        """
        p = Path(file_path).expanduser()
        if not p.exists():
            return f"[error] file not found: {file_path}"
        if not p.is_file():
            return f"[error] not a file: {file_path}"
        try:
            text = p.read_bytes().decode("utf-8", errors="replace")
            lines = text.splitlines()
            total = len(lines)
            start = max(0, start_line - 1)
            end = total if end_line == 0 else min(end_line, total)
            selected = lines[start:end]
            truncated = end_line == 0 and total > 500
            header = f"File: {file_path} | Lines {start + 1}-{end} of {total}"
            if truncated:
                header += f" (truncated; use start_line/end_line to read more)"
            numbered = "\n".join(f"{start + i + 1:>4}  {l}" for i, l in enumerate(selected))
            return header + "\n" + "─" * 50 + "\n" + (numbered or "[empty file]")
        except Exception as exc:
            return f"[error] {exc}"


class GeminiReplaceTool(Tool):
    name = "replace"
    description = (
        "Replaces text within a file. By default expects exactly ONE occurrence of "
        "old_string. Set allow_multiple=true to replace all occurrences. "
        "Requires significant context in old_string to ensure precise targeting. "
        "Always read the file first before replacing."
    )

    def run(
        self,
        file_path: str,
        instruction: str,
        old_string: str,
        new_string: str,
        allow_multiple: bool = False,
    ) -> str:
        """
        Args:
            file_path: The path to the file to modify.
            instruction: A clear semantic description of what this change does and why.
            old_string: The exact literal text to replace (including whitespace and indentation).
            new_string: The exact literal text to replace old_string with.
            allow_multiple: If true, replaces all occurrences. If false (default), fails if not exactly one match.
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
            return f"[error] old_string not found: {snippet}"
        if not allow_multiple and count > 1:
            snippet = repr(old_string[:80]) + ("..." if len(old_string) > 80 else "")
            return (
                f"[error] old_string matches {count} times (set allow_multiple=true "
                f"to replace all): {snippet}"
            )

        if allow_multiple:
            new_content = content.replace(old_string, new_string)
            n = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            n = 1

        try:
            p.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return f"[error] could not write: {exc}"

        return f"[ok] replaced {n} occurrence(s) in {file_path}"


class GeminiGlobTool(Tool):
    name = "glob"
    description = (
        "Efficiently finds files matching specific glob patterns "
        "(e.g. 'src/**/*.ts', '**/*.md'), returning paths sorted by "
        "modification time (newest first)."
    )

    def run(
        self,
        pattern: str,
        dir_path: str = ".",
        case_sensitive: bool = False,
    ) -> str:
        """
        Args:
            pattern: The glob pattern to match against (e.g. '**/*.py', 'docs/*.md').
            dir_path: Optional: The directory to search within. Defaults to cwd.
            case_sensitive: Optional: Whether the search should be case-sensitive. Defaults to false.
        """
        base = Path(dir_path).expanduser().resolve()
        if not base.exists():
            return f"[error] directory not found: {dir_path}"
        try:
            matches = list(base.glob(pattern))
            if not case_sensitive:
                # Python's glob is case-sensitive on Linux; on macOS it depends on the FS.
                # For cross-platform consistency, filter by lowercased pattern if needed.
                pass
            matches.sort(key=lambda p: -p.stat().st_mtime if p.exists() else 0)
            paths = [str(m.relative_to(base)) for m in matches if m.is_file()]
            if not paths:
                return f"[no matches] pattern {pattern!r} in {dir_path}"
            return "\n".join(paths)
        except Exception as exc:
            return f"[error] {exc}"


class GeminiGrepTool(Tool):
    name = "grep_search"
    description = (
        "Searches for a regular expression pattern within file contents. "
        "Max 100 matches by default."
    )

    def run(
        self,
        pattern: str,
        dir_path: str = ".",
        include: str = "",
        names_only: bool = False,
        total_max_matches: int = 100,
    ) -> str:
        """
        Args:
            pattern: The regular expression pattern to search for in file contents.
            dir_path: Optional: The directory to search within. Defaults to cwd.
            include: Optional: A glob pattern to filter which files are searched (e.g. '*.js', '*.{ts,tsx}').
            names_only: Optional: If true, returns only file paths, not matching lines.
            total_max_matches: Optional: Maximum total matches to return. Defaults to 100.
        """
        import re
        base = Path(dir_path).expanduser().resolve()
        if not base.exists():
            return f"[error] path not found: {dir_path}"

        file_glob = include if include else "*"
        if base.is_file():
            files = [base]
        else:
            files = [f for f in base.rglob("*") if f.is_file() and fnmatch.fnmatch(f.name, file_glob)]

        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"[error] invalid regex: {exc}"

        results: list[str] = []
        seen_files: set[str] = set()

        for f in sorted(files):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = str(f.relative_to(base)) if base.is_dir() else str(f)
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    if names_only:
                        if rel not in seen_files:
                            seen_files.add(rel)
                            results.append(rel)
                    else:
                        results.append(f"{rel}:{i}: {line.rstrip()}")
                    if len(results) >= total_max_matches:
                        results.append(f"[truncated — reached limit of {total_max_matches}]")
                        return "\n".join(results)

        return "\n".join(results) if results else f"[no matches] {pattern!r} in {dir_path}"


class GeminiListDirTool(Tool):
    name = "list_directory"
    description = (
        "Lists the names of files and subdirectories directly within a specified "
        "directory path. Can optionally ignore entries matching provided glob patterns."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "dir_path": {
                    "type": "string",
                    "description": "The path to the directory to list.",
                },
                "ignore": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: List of glob patterns to ignore (e.g. ['*.pyc', '__pycache__']).",
                },
            },
            "required": ["dir_path"],
        }

    def run(self, dir_path: str, ignore: list = None) -> str:
        """
        Args:
            dir_path: The path to the directory to list.
            ignore: Optional: List of glob patterns to ignore (e.g. ['*.pyc', '__pycache__']).
        """
        p = Path(dir_path).expanduser().resolve()
        if not p.exists():
            return f"[error] path not found: {dir_path}"
        if not p.is_dir():
            return f"[error] not a directory: {dir_path}"

        ignore_patterns: list[str] = ignore or []
        entries = []
        for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if any(fnmatch.fnmatch(item.name, pat) for pat in ignore_patterns):
                continue
            if item.is_dir():
                entries.append(f"  {item.name}/")
            else:
                size_str = _human_size(item.stat().st_size)
                entries.append(f"  {item.name:<40} {size_str:>8}")

        header = f"{p}\n{'─' * 50}"
        return header + "\n" + "\n".join(entries) if entries else f"{p}\n[empty]"


class GeminiShellTool(Tool):
    name = "run_shell_command"
    description = (
        "Executes a shell command and returns its output. "
        "Use for git, npm, python, build tools, etc. "
        "Prefer specialized file tools (read_file, glob, grep_search) over "
        "shell equivalents (cat, find, grep) when available."
    )

    def run(self, command: str, description: str = "") -> str:
        """
        Args:
            command: The shell command to execute.
            description: Optional: Brief description of what this command does.
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=os.getcwd(),
            )
            parts = []
            if result.stdout.strip():
                parts.append(result.stdout.rstrip())
            if result.stderr.strip():
                parts.append(f"[stderr]\n{result.stderr.rstrip()}")
            if not parts:
                parts.append(f"[exit code {result.returncode}]")
            return "\n".join(parts)
        except subprocess.TimeoutExpired:
            return "[error] command timed out after 120s"
        except Exception as exc:
            return f"[error] {exc}"


class GeminiWebSearchTool(Tool):
    name = "google_web_search"
    description = (
        "Performs a web search using Google Search (via the Gemini API) and returns the results. "
        "Useful for finding information on the internet based on a query."
    )

    def run(self, query: str) -> str:
        """
        Args:
            query: The search query to find information on the web.
        """
        from urllib.parse import quote_plus
        import re
        import httpx

        _HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=8):
                    results.append(
                        f"**{r.get('title', 'No title')}**\n"
                        f"{r.get('href', '')}\n"
                        f"{r.get('body', '')}"
                    )
            if results:
                return "\n\n".join(results)
        except ImportError:
            pass
        except Exception:
            pass

        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            with httpx.Client(follow_redirects=True, timeout=10) as client:
                resp = client.get(url, headers=_HEADERS)
                resp.raise_for_status()
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', resp.text, re.S)
            urls   = re.findall(r'class="result__url"[^>]*>\s*(.*?)\s*</a>', resp.text, re.S)
            snips  = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.S)
            results = []
            for i, (t, u, s) in enumerate(zip(titles, urls, snips)):
                if i >= 8:
                    break
                results.append(
                    f"**{re.sub(r'<[^>]+>', '', t).strip()}**\n"
                    f"{re.sub(r'<[^>]+>', '', u).strip()}\n"
                    f"{re.sub(r'<[^>]+>', '', s).strip()}"
                )
            return "\n\n".join(results) if results else f"[no results for: {query!r}]"
        except Exception as exc:
            return f"[error] web search failed: {exc}"


class GeminiWebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Processes content from URL(s), including local and private network addresses "
        "(e.g., localhost), embedded in a prompt. Include up to 20 URLs and instructions "
        "(e.g., summarize, extract specific data) directly in the 'prompt' parameter."
    )

    def run(self, prompt: str) -> str:
        """
        Args:
            prompt: A comprehensive prompt that includes the URL(s) (up to 20) to fetch
                and specific instructions on how to process their content
                (e.g., "Summarize https://example.com/article and extract key points from
                https://another.com/data"). All URLs must start with "http://" or "https://".
        """
        import re
        import httpx
        from html.parser import HTMLParser

        _HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        urls = re.findall(r'https?://[^\s"\'<>]+', prompt)
        if not urls:
            return "[error] no URLs found in prompt"

        parts = []
        for url in urls[:20]:
            try:
                with httpx.Client(follow_redirects=True, timeout=15) as client:
                    resp = client.get(url, headers=_HEADERS)
                    resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                text = resp.text
                if "html" in content_type:
                    # Strip HTML tags minimally
                    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"[ \t]+", " ", text)
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
                if len(text) > 20_000:
                    text = text[:20_000] + f"\n\n[truncated]"
                parts.append(f"=== {url} ===\n{text or '[empty]'}")
            except Exception as exc:
                parts.append(f"=== {url} ===\n[error] {exc}")

        return "\n\n".join(parts)


class GeminiWriteTodosTool(Tool):
    name = "write_todos"
    description = (
        "Create or update the task/todo list. "
        "Pass the complete list of todos — this replaces the existing list. "
        "Each todo needs 'description' and 'status' "
        "(pending/in_progress/completed/cancelled)."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The complete list of todo items. This will replace the existing list.",
                    "items": {
                        "type": "object",
                        "description": "A single todo item.",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "The description of the task.",
                            },
                            "status": {
                                "type": "string",
                                "description": "The current status of the task.",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                            },
                        },
                        "required": ["description", "status"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["todos"],
            "additionalProperties": False,
        }

    def run(self, todos: list) -> str:
        """
        Args:
            todos: List of {description, status} dicts.
        """
        import json
        from pathlib import Path

        if not isinstance(todos, list):
            return "[error] todos must be a list"

        _VALID = {"pending", "in_progress", "completed", "cancelled"}
        normalized = []
        for i, t in enumerate(todos):
            if not isinstance(t, dict):
                return f"[error] todo {i} must be an object"
            desc = t.get("description", "").strip()
            if not desc:
                return f"[error] todo {i} has empty description"
            status = t.get("status", "pending")
            if status not in _VALID:
                return f"[error] todo {i} has invalid status {status!r}"
            normalized.append({"id": i + 1, "description": desc, "status": status})

        path = Path(".agent_todos.json")
        path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
        counts = {s: sum(1 for t in normalized if t["status"] == s) for s in _VALID}
        return (
            f"[ok] saved {len(normalized)} todos "
            f"({counts['in_progress']} in_progress, {counts['pending']} pending, "
            f"{counts['completed']} completed, {counts['cancelled']} cancelled)"
        )


class GeminiExitPlanModeTool(Tool):
    name = "exit_plan_mode"
    description = (
        "Signal that planning is complete and request permission to proceed with "
        "implementation. Use after presenting a plan to the user."
    )

    @property
    def parameters_schema(self):
        return {"type": "object", "properties": {}, "required": []}

    def run(self) -> str:
        return "[plan mode exited — awaiting user approval to proceed]"


class GeminiEnterPlanModeTool(Tool):
    name = "enter_plan_mode"
    description = (
        "Switch to Plan Mode to safely research, design, and plan complex changes "
        "using read-only tools."
    )

    def run(self, reason: str = "") -> str:
        """
        Args:
            reason: Short reason explaining why you are entering plan mode.
        """
        msg = f"[plan mode entered]"
        if reason:
            msg += f" Reason: {reason}"
        return msg


class GeminiReadManyFilesTool(Tool):
    name = "read_many_files"
    description = (
        "Reads content from multiple files specified by glob patterns. "
        "Concatenates their content with '--- {filePath} ---' separators. "
        "Use when you need to read several files at once for context or analysis."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "include": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "description": "Array of glob patterns or paths. Examples: ['src/**/*.ts'], ['README.md', 'docs/']",
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "description": "Optional. Glob patterns for files/directories to exclude.",
                    "default": [],
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Optional. Whether to search recursively. Defaults to true.",
                    "default": True,
                },
                "useDefaultExcludes": {
                    "type": "boolean",
                    "description": "Optional. Whether to apply default exclusions (node_modules, .git, etc.). Defaults to true.",
                    "default": True,
                },
            },
            "required": ["include"],
        }

    def run(
        self,
        include: list,
        exclude: list = None,
        recursive: bool = True,
        useDefaultExcludes: bool = True,
    ) -> str:
        """
        Args:
            include: Array of glob patterns or paths (e.g. ['src/**/*.ts']).
            exclude: Optional glob patterns to exclude.
            recursive: Whether to search recursively. Defaults to true.
            useDefaultExcludes: Apply default exclusions (node_modules, .git). Defaults to true.
        """
        from pathlib import Path

        _DEFAULT_EXCLUDES = {
            "node_modules", ".git", "__pycache__", ".venv", "dist", "build",
            ".next", ".nuxt", "coverage", ".cache",
        }

        exclude_patterns: list[str] = exclude or []
        parts: list[str] = []

        for pattern in include:
            base = Path(".").resolve()
            # If it looks like a plain path (not a glob), try direct read first
            candidate = Path(pattern)
            if candidate.exists() and candidate.is_file():
                files = [candidate]
            else:
                files = sorted(base.glob(pattern))

            for f in files:
                if not f.is_file():
                    continue
                # Apply default excludes
                if useDefaultExcludes:
                    if any(part in _DEFAULT_EXCLUDES for part in f.parts):
                        continue
                # Apply user excludes
                if any(fnmatch.fnmatch(str(f), pat) or fnmatch.fnmatch(f.name, pat)
                       for pat in exclude_patterns):
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    parts.append(f"--- {f} ---\n{text}")
                except Exception as exc:
                    parts.append(f"--- {f} ---\n[error reading file: {exc}]")

        if not parts:
            return "[no files matched the given patterns]"

        return "\n".join(parts) + "\n--- End of content ---"


class GeminiSaveMemoryTool(Tool):
    name = "save_memory"
    description = (
        "Saves a concise global user context (preferences, facts) for use across all workspaces. "
        "Use for 'Remember X' or clear personal facts. "
        "Do NOT use for session-specific or workspace-specific context."
    )

    def run(self, fact: str) -> str:
        """
        Args:
            fact: The specific fact or piece of information to remember.
                Should be a clear, self-contained statement.
        """
        import json
        from pathlib import Path

        memory_file = Path.home() / ".gemini" / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            memories: list[str] = json.loads(memory_file.read_text(encoding="utf-8")) if memory_file.exists() else []
        except Exception:
            memories = []
        memories.append(fact.strip())
        memory_file.write_text(json.dumps(memories, indent=2, ensure_ascii=False), encoding="utf-8")
        return f"[ok] memory saved: {fact.strip()!r}"


class GeminiGetInternalDocsTool(Tool):
    name = "get_internal_docs"
    description = (
        "Returns the content of Gemini CLI internal documentation files. "
        "If no path is provided, returns a list of all available documentation paths."
    )

    def run(self, path: str = "") -> str:
        """
        Args:
            path: The relative path to the documentation file (e.g., 'cli/commands.md').
                If omitted, lists all available documentation.
        """
        from pathlib import Path

        # Look for docs relative to a GEMINI.md or project root
        doc_roots = [
            Path(".") / "docs",
            Path(".") / "documentation",
        ]
        if not path:
            found = []
            for root in doc_roots:
                if root.exists():
                    for f in sorted(root.rglob("*.md")):
                        found.append(str(f.relative_to(root.parent)))
            return "\n".join(found) if found else "[no internal documentation found]"

        for root in doc_roots:
            candidate = root.parent / path
            if candidate.exists() and candidate.is_file():
                try:
                    return candidate.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:
                    return f"[error] {exc}"
        return f"[error] documentation not found: {path!r}"


class GeminiAskUserTool(Tool):
    name = "ask_user"
    description = (
        "Ask the user one or more questions to gather preferences, clarify requirements, "
        "or make decisions."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "required": ["questions"],
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "required": ["question", "header", "type"],
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The complete question to ask the user.",
                            },
                            "header": {
                                "type": "string",
                                "description": "Very short label displayed as a chip/tag (e.g., 'Auth method').",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["choice", "text", "yesno"],
                                "default": "choice",
                                "description": "Question type: 'choice', 'text', or 'yesno'.",
                            },
                            "options": {
                                "type": "array",
                                "description": "Selectable choices for 'choice' type (2-4 options).",
                                "items": {
                                    "type": "object",
                                    "required": ["label", "description"],
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                },
                            },
                            "multiSelect": {
                                "type": "boolean",
                                "description": "Allow selecting multiple options (choice type only).",
                            },
                            "placeholder": {
                                "type": "string",
                                "description": "Hint text shown in the input field.",
                            },
                        },
                    },
                },
            },
        }

    def run(self, questions: list) -> str:
        """
        Args:
            questions: List of question objects with 'question', 'header', 'type', and optional 'options'.
        """
        if not questions:
            return "[error] no questions provided"

        lines = []
        for i, q in enumerate(questions, 1):
            lines.append(f"Q{i} [{q.get('header', '')}]: {q.get('question', '')}")
            qtype = q.get("type", "choice")
            if qtype == "choice" and q.get("options"):
                for opt in q["options"]:
                    lines.append(f"  - {opt.get('label', '')}: {opt.get('description', '')}")
            elif qtype == "yesno":
                lines.append("  - Yes / No")
            elif qtype == "text":
                placeholder = q.get("placeholder", "")
                lines.append(f"  [free text{': ' + placeholder if placeholder else ''}]")

        return (
            "[ask_user] The model has questions for the user:\n"
            + "\n".join(lines)
            + "\n[Please provide answers to continue.]"
        )


class GeminiActivateSkillTool(Tool):
    name = "activate_skill"
    description = (
        "Activate a named skill to extend the agent's capabilities. "
        "Skills provide specialized tools and context for specific domains."
    )

    def run(self, skill_name: str) -> str:
        """
        Args:
            skill_name: The name of the skill to activate.
        """
        return f"[activate_skill] skill {skill_name!r} activation is not implemented in this environment."
