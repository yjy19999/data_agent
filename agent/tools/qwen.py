"""
Qwen Code-style tool implementations.

Parameter schemas match qwen-code's actual tool declarations exactly:
  - read_file:         absolute_path, offset, limit
  - edit:              file_path, old_string, new_string, replace_all
  - glob:              pattern, path
  - grep_search:       pattern, path, glob, limit
  - list_directory:    dir_path
  - run_shell_command: command, is_background, timeout, description, directory
  - web_fetch:         url, prompt
  - web_search:        query
  - todo_write:        todos [{id, content, status}]
  - save_memory:       fact, scope (optional: global/project)
  - task:              description, prompt, subagent_type
  - skill:             skill
  - exit_plan_mode:    (no params)
  - lsp:               operation, filePath, line, character, ...
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path

from .base import Tool
from .files import _human_size


class QwenReadFileTool(Tool):
    name = "read_file"
    description = (
        "Reads and returns the content of a specified file. "
        "If the file is large, the content will be truncated. "
        "Use 'offset' and 'limit' to paginate through large files."
    )

    def run(self, absolute_path: str, offset: int = 0, limit: int = 0) -> str:
        """
        Args:
            absolute_path: The absolute path to the file to read (e.g. '/home/user/project/file.txt'). Relative paths are not supported.
            offset: Optional: The 0-based line number to start reading from. Use with limit to paginate.
            limit: Optional: Maximum number of lines to read. 0 means read to end.
        """
        p = Path(absolute_path).expanduser()
        if not p.exists():
            return f"[error] file not found: {absolute_path}"
        if not p.is_file():
            return f"[error] not a file: {absolute_path}"
        try:
            text = p.read_bytes().decode("utf-8", errors="replace")
            lines = text.splitlines()
            total = len(lines)
            start = max(0, offset)
            end = total if limit == 0 else min(start + limit, total)
            selected = lines[start:end]
            truncated = (end < total)
            header = f"File: {absolute_path} | Lines {start + 1}-{end} of {total}"
            if truncated:
                header += f" (truncated; use offset={end} to continue)"
            numbered = "\n".join(f"{start + i + 1:>4}  {l}" for i, l in enumerate(selected))
            return header + "\n" + "─" * 50 + "\n" + (numbered or "[empty file]")
        except Exception as exc:
            return f"[error] {exc}"


class QwenEditTool(Tool):
    name = "edit"
    description = (
        "Replaces text within a file. By default, replaces a single occurrence. "
        "Set replace_all=true to replace every instance of old_string. "
        "Always use read_file to examine the file's current content before editing."
    )

    def run(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        """
        Args:
            file_path: The absolute path to the file to modify. Must start with '/'.
            old_string: The exact literal text to replace (including all whitespace and indentation).
            new_string: The exact literal text to replace old_string with.
            replace_all: Replace all occurrences of old_string (default false).
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
        if not replace_all and count > 1:
            snippet = repr(old_string[:80]) + ("..." if len(old_string) > 80 else "")
            return (
                f"[error] old_string matches {count} times "
                f"(set replace_all=true to replace all): {snippet}"
            )

        if replace_all:
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


class QwenGlobTool(Tool):
    name = "glob"
    description = (
        "Fast file pattern matching tool that works with any codebase size. "
        "Supports glob patterns like '**/*.js' or 'src/**/*.ts'. "
        "Returns matching file paths sorted by modification time."
    )

    def run(self, pattern: str, path: str = ".") -> str:
        """
        Args:
            pattern: The glob pattern to match files against.
            path: The directory to search in. If not specified, the current working directory will be used. IMPORTANT: Omit this field to use the default directory.
        """
        base = Path(path).expanduser().resolve()
        if not base.exists():
            return f"[error] directory not found: {path}"
        try:
            matches = list(base.glob(pattern))
            matches.sort(key=lambda p: -p.stat().st_mtime if p.exists() else 0)
            paths = [str(m.relative_to(base)) for m in matches if m.is_file()]
            if not paths:
                return f"[no matches] pattern {pattern!r} in {path}"
            return "\n".join(paths)
        except Exception as exc:
            return f"[error] {exc}"


class QwenGrepTool(Tool):
    name = "grep_search"
    description = (
        "A powerful search tool for finding patterns in files. "
        "Supports full regex syntax. Filter files with the glob parameter. "
        "Case-insensitive by default."
    )

    def run(
        self,
        pattern: str,
        path: str = ".",
        glob: str = "",
        limit: int = 0,
    ) -> str:
        """
        Args:
            pattern: The regular expression pattern to search for in file contents.
            path: File or directory to search in. Defaults to current working directory.
            glob: Glob pattern to filter files (e.g. '*.js', '*.{ts,tsx}').
            limit: Limit output to first N matching lines. 0 means show all matches.
        """
        import re
        base = Path(path).expanduser().resolve()
        if not base.exists():
            return f"[error] path not found: {path}"

        file_glob = glob if glob else "*"
        if base.is_file():
            files = [base]
        else:
            files = [f for f in base.rglob("*") if f.is_file() and fnmatch.fnmatch(f.name, file_glob)]

        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"[error] invalid regex: {exc}"

        results: list[str] = []
        max_results = limit if limit > 0 else 100

        for f in sorted(files):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = str(f.relative_to(base)) if base.is_dir() else str(f)
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    results.append(f"{rel}:{i}: {line.rstrip()}")
                    if len(results) >= max_results:
                        results.append(f"[truncated — reached limit of {max_results}]")
                        return "\n".join(results)

        return "\n".join(results) if results else f"[no matches] {pattern!r} in {path}"


class QwenListDirTool(Tool):
    name = "list_directory"
    description = (
        "Lists the names of files and subdirectories directly within a "
        "specified directory path."
    )

    def run(self, dir_path: str) -> str:
        """
        Args:
            dir_path: The path to the directory to list.
        """
        p = Path(dir_path).expanduser().resolve()
        if not p.exists():
            return f"[error] path not found: {dir_path}"
        if not p.is_dir():
            return f"[error] not a directory: {dir_path}"

        entries = []
        for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if item.is_dir():
                entries.append(f"  {item.name}/")
            else:
                size_str = _human_size(item.stat().st_size)
                entries.append(f"  {item.name:<40} {size_str:>8}")

        header = f"{p}\n{'─' * 50}"
        return header + "\n" + "\n".join(entries) if entries else f"{p}\n[empty]"


class QwenShellTool(Tool):
    name = "run_shell_command"
    description = (
        "Executes a shell command with optional timeout and working directory. "
        "Use for git, npm, pytest, build tools, etc. "
        "Prefer specialized file tools (read_file, glob, grep_search, edit) "
        "over shell equivalents when available."
    )

    def run(
        self,
        command: str,
        is_background: bool = False,
        timeout: int = 120,
        description: str = "",
        directory: str = "",
    ) -> str:
        """
        Args:
            command: The shell command to execute.
            is_background: Optional: Whether to run the command in the background. Defaults to false.
            timeout: Optional: Timeout in milliseconds (max 600000). Defaults to 120000ms.
            description: Optional: Brief description of what this command does (5-10 words).
            directory: Optional: The absolute path of the directory to run the command in. Defaults to project root.
        """
        cwd = directory if directory else os.getcwd()
        # timeout param from qwen is in ms; convert to seconds for subprocess
        timeout_s = max(1, timeout // 1000) if timeout > 1000 else timeout

        if is_background:
            try:
                subprocess.Popen(
                    command,
                    shell=True,
                    cwd=cwd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return f"[ok] background command started: {command}"
            except Exception as exc:
                return f"[error] {exc}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=cwd,
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
            return f"[error] command timed out after {timeout_s}s"
        except Exception as exc:
            return f"[error] {exc}"


class QwenWebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Fetches content from a specified URL and processes it using an AI model. "
        "Takes a URL and a prompt as input, fetches the URL content, converts HTML to markdown, "
        "and returns the model's response about the content."
    )

    def run(self, url: str, prompt: str) -> str:
        """
        Args:
            url: The URL to fetch content from. Must be a fully-formed valid URL starting with http:// or https://.
            prompt: The prompt to run on the fetched content (e.g., 'Summarize this page').
        """
        import re
        import httpx

        _HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            with httpx.Client(follow_redirects=True, timeout=10) as client:
                resp = client.get(url, headers=_HEADERS)
                resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            text = resp.text
            if "html" in content_type:
                text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) > 20_000:
                text = text[:20_000] + "\n\n[truncated]"
            return f"Content from {url}:\n{text or '[empty]'}\n\n[Prompt: {prompt}]"
        except Exception as exc:
            return f"[error] {exc}"


class QwenWebSearchTool(Tool):
    name = "web_search"
    description = (
        "Searches the web for information based on a query. "
        "Returns search results with titles, URLs, and snippets."
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


class QwenTodoWriteTool(Tool):
    name = "todo_write"
    description = (
        "Creates and manages a structured task list for your current coding session. "
        "This helps track progress, organize complex tasks, and demonstrate thoroughness."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The updated todo list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique identifier for the todo item.",
                            },
                            "content": {
                                "type": "string",
                                "minLength": 1,
                                "description": "The task description.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Current status of the task.",
                            },
                        },
                        "required": ["content", "status", "id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["todos"],
        }

    def run(self, todos: list) -> str:
        """
        Args:
            todos: List of {id, content, status} dicts.
        """
        import json
        from pathlib import Path

        if not isinstance(todos, list):
            return "[error] todos must be a list"

        _VALID = {"pending", "in_progress", "completed"}
        normalized = []
        for i, t in enumerate(todos):
            if not isinstance(t, dict):
                return f"[error] todo {i} must be an object"
            content = t.get("content", "").strip()
            if not content:
                return f"[error] todo {i} has empty content"
            status = t.get("status", "pending")
            if status not in _VALID:
                return f"[error] todo {i} has invalid status {status!r}"
            todo_id = t.get("id", str(i + 1))
            normalized.append({"id": todo_id, "content": content, "status": status})

        Path(".agent_todos.json").write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        counts = {s: sum(1 for t in normalized if t["status"] == s) for s in _VALID}
        return (
            f"[ok] saved {len(normalized)} todos "
            f"({counts['in_progress']} in_progress, {counts['pending']} pending, "
            f"{counts['completed']} completed)"
        )


class QwenSaveMemoryTool(Tool):
    name = "save_memory"
    description = (
        "Saves a specific piece of information or fact to long-term memory. "
        "Use when the user explicitly asks you to remember something, or states "
        "a clear, concise fact important to retain for future interactions."
    )

    def run(self, fact: str, scope: str = "") -> str:
        """
        Args:
            fact: The specific fact or piece of information to remember. Should be a clear, self-contained statement.
            scope: Where to save the memory: 'global' saves to ~/.qwen/QWEN.md (shared across all projects),
                'project' saves to current project's QWEN.md. If not specified, defaults to global.
        """
        import json
        from pathlib import Path

        scope = scope or "global"
        if scope not in ("global", "project"):
            return f"[error] invalid scope {scope!r} (use 'global' or 'project')"

        if scope == "global":
            memory_file = Path.home() / ".qwen" / "memory.json"
        else:
            memory_file = Path(".qwen") / "memory.json"

        memory_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            memories: list[str] = json.loads(memory_file.read_text(encoding="utf-8")) if memory_file.exists() else []
        except Exception:
            memories = []
        memories.append(fact.strip())
        memory_file.write_text(json.dumps(memories, indent=2, ensure_ascii=False), encoding="utf-8")
        return f"[ok] memory saved ({scope}): {fact.strip()!r}"


class QwenTaskTool(Tool):
    name = "task"
    description = (
        "Delegate tasks to specialized subagents. "
        "Each subagent has specific capabilities and tools available to it."
    )

    def run(self, description: str, prompt: str, subagent_type: str) -> str:
        """
        Args:
            description: A short (3-5 word) description of the task.
            prompt: The task for the agent to perform.
            subagent_type: The type of specialized agent to use for this task.
        """
        return (
            f"[task] subagent={subagent_type!r} | {description}\n"
            f"Prompt: {prompt}\n"
            f"[Task delegation is not implemented in this environment.]"
        )


class QwenSkillTool(Tool):
    name = "skill"
    description = (
        "Execute a skill within the main conversation. "
        "Skills provide specialized capabilities and domain knowledge."
    )

    def run(self, skill: str) -> str:
        """
        Args:
            skill: The skill name (no arguments). E.g., 'pdf' or 'xlsx'.
        """
        return f"[skill] {skill!r} execution is not implemented in this environment."


class QwenLspTool(Tool):
    name = "lsp"
    description = (
        "Language Server Protocol (LSP) tool for code intelligence: "
        "definitions, references, hover, symbols, call hierarchy, diagnostics, and code actions. "
        "ALWAYS use LSP as the primary tool for code intelligence when available."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "LSP operation to execute.",
                    "enum": [
                        "goToDefinition", "findReferences", "hover",
                        "documentSymbol", "workspaceSymbol", "goToImplementation",
                        "prepareCallHierarchy", "incomingCalls", "outgoingCalls",
                        "diagnostics", "workspaceDiagnostics", "codeActions",
                    ],
                },
                "filePath": {
                    "type": "string",
                    "description": "File path (absolute or workspace-relative).",
                },
                "line": {
                    "type": "number",
                    "description": "1-based line number for the target location.",
                },
                "character": {
                    "type": "number",
                    "description": "1-based character/column number for the target location.",
                },
                "endLine": {
                    "type": "number",
                    "description": "1-based end line number for range-based operations.",
                },
                "endCharacter": {
                    "type": "number",
                    "description": "1-based end character for range-based operations.",
                },
                "includeDeclaration": {
                    "type": "boolean",
                    "description": "Include the declaration itself when looking up references.",
                },
                "query": {
                    "type": "string",
                    "description": "Symbol query for workspace symbol search.",
                },
                "serverName": {
                    "type": "string",
                    "description": "Optional LSP server name to target.",
                },
                "limit": {
                    "type": "number",
                    "description": "Optional maximum number of results to return.",
                },
            },
            "required": ["operation"],
        }

    def run(
        self,
        operation: str,
        filePath: str = "",
        line: int = 0,
        character: int = 0,
        endLine: int = 0,
        endCharacter: int = 0,
        includeDeclaration: bool = True,
        query: str = "",
        serverName: str = "",
        limit: int = 0,
    ) -> str:
        """
        Args:
            operation: LSP operation to execute (goToDefinition, findReferences, hover, etc.).
            filePath: File path (absolute or workspace-relative).
            line: 1-based line number for the target location.
            character: 1-based character/column number for the target location.
            endLine: 1-based end line number for range-based operations.
            endCharacter: 1-based end character for range-based operations.
            includeDeclaration: Include the declaration when looking up references.
            query: Symbol query for workspaceSymbol search.
            serverName: Optional LSP server name to target.
            limit: Optional maximum number of results to return.
        """
        return (
            f"[lsp] operation={operation!r}"
            + (f" file={filePath!r}" if filePath else "")
            + (f" line={line} char={character}" if line else "")
            + (f" query={query!r}" if query else "")
            + "\n[LSP is not available in this environment.]"
        )
