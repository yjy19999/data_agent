"""
OpenCode-style tool implementations.

Parameter schemas match opencode's actual tool declarations exactly:
  - read:           filePath, offset, limit
  - write:          content, filePath
  - list:           path, ignore
  - glob:           pattern, path
  - grep:           pattern, path, include
  - edit:           filePath, oldString, newString, replaceAll
  - bash:           command, timeout, workdir, description
  - webfetch:       url, format, timeout
  - websearch:      query, numResults, livecrawl, type, contextMaxCharacters
  - todowrite:      todos [{id, content, status}]
  - todoread:       (no params)
  - plan_exit:      (no params)
  - task:           description, prompt, subagent_type, task_id, command
  - apply_patch:    patchText
  - codesearch:     query, tokensNum
  - lsp:            operation, filePath, line, character
  - multiedit:      filePath, edits [{filePath, oldString, newString, replaceAll}]
  - question:       questions [{question, header, type, options, ...}]
  - skill:          name
  - batch:          tool_calls [{tool, parameters}]
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import json
from pathlib import Path

from .base import Tool
from .files import _human_size


class OpencodeReadTool(Tool):
    name = "read"
    description = (
        "Reads and returns the content of a specified file. "
        "If the file is large, the content will be truncated. "
        "Use 'offset' and 'limit' to paginate through large files."
    )

    def run(self, filePath: str, offset: int = 1, limit: int = 2000) -> str:
        """
        Args:
            filePath: The absolute path to the file or directory to read.
            offset: Optional: The line number to start reading from (1-indexed). Defaults to 1.
            limit: Optional: The maximum number of lines to read. Defaults to 2000.
        """
        p = Path(filePath).expanduser()
        if not p.exists():
            return f"[error] file not found: {filePath}"

        if p.is_dir():
            # Directory listing behavior from opencode read tool
            entries = sorted([e.name + ("/" if e.is_dir() else "") for e in p.iterdir()])
            start = max(0, offset - 1)
            end = start + limit
            selected = entries[start:end]
            truncated = end < len(entries)

            output = [
                f"<path>{filePath}</path>",
                "<type>directory</type>",
                "<entries>",
                "\n".join(selected),
                (
                    f"\n(Showing {len(selected)} of {len(entries)} entries. "
                    f"Use 'offset' parameter to read beyond entry {offset + len(selected)})"
                    if truncated else f"\n({len(entries)} entries)"
                ),
                "</entries>",
            ]
            return "\n".join(output)

        if not p.is_file():
            return f"[error] not a file: {filePath}"

        try:
            # Check for binary file
            try:
                with open(p, "rb") as f:
                    chunk = f.read(4096)
                    if b"\0" in chunk:
                        return f"[error] Cannot read binary file: {filePath}"
            except Exception:
                pass

            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            total = len(lines)

            start = max(0, offset - 1)
            end = min(start + limit, total)
            selected = lines[start:end]
            truncated = end < total

            content = []
            for i, line in enumerate(selected):
                content.append(f"{start + i + 1}: {line}")

            output = [
                f"<path>{filePath}</path>",
                "<type>file</type>",
                "<content>",
                "\n".join(content),
            ]

            if truncated:
                output.append(f"\n(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)")
            else:
                output.append(f"\n(End of file - total {total} lines)")

            output.append("</content>")
            return "\n".join(output)

        except Exception as exc:
            return f"[error] {exc}"


class OpencodeWriteTool(Tool):
    name = "write"
    description = (
        "Write content to a file. Overwrites existing content. "
        "Create parent directories if they don't exist."
    )

    def run(self, content: str, filePath: str) -> str:
        """
        Args:
            content: The content to write to the file.
            filePath: The absolute path to the file to write (must be absolute, not relative).
        """
        p = Path(filePath).expanduser()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return "Wrote file successfully."
        except Exception as exc:
            return f"[error] could not write: {exc}"


class OpencodeListTool(Tool):
    name = "list"
    description = (
        "Lists the names of files and subdirectories directly within a specified "
        "directory path. Can optionally ignore entries matching provided glob patterns."
    )

    def run(self, path: str = ".", ignore: list[str] = None) -> str:
        """
        Args:
            path: The absolute path to the directory to list (must be absolute, not relative).
            ignore: Optional: List of glob patterns to ignore.
        """
        dir_path = Path(path).expanduser().resolve()
        if not dir_path.exists():
            return f"[error] path not found: {path}"
        if not dir_path.is_dir():
            return f"[error] not a directory: {path}"

        ignore_patterns = [
            "node_modules", "__pycache__", ".git", "dist", "build",
            "target", "vendor", "bin", "obj", ".idea", ".vscode",
            ".zig-cache", "zig-out", ".coverage", "coverage",
            "tmp", "temp", ".cache", "cache", "logs", ".venv", "venv", "env",
        ]
        if ignore:
            ignore_patterns.extend(ignore)

        output_lines = [f"{dir_path}/"]

        try:
            files_found = []
            for root, dirs, files in os.walk(dir_path):
                # Filter ignored dirs in place
                dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, pat) for pat in ignore_patterns)]

                for file in files:
                    if any(fnmatch.fnmatch(file, pat) for pat in ignore_patterns):
                        continue
                    full_path = Path(root) / file
                    files_found.append(str(full_path.relative_to(dir_path)))
                    if len(files_found) >= 100:
                        break
                if len(files_found) >= 100:
                    break

            for f in sorted(files_found):
                output_lines.append(f"  {f}")

            return "\n".join(output_lines)

        except Exception as exc:
            return f"[error] {exc}"


class OpencodeGlobTool(Tool):
    name = "glob"
    description = (
        "Fast file pattern matching tool. "
        "Returns matching file paths sorted by modification time."
    )

    def run(self, pattern: str, path: str = ".") -> str:
        """
        Args:
            pattern: The glob pattern to match files against.
            path: The directory to search in. Defaults to current working directory.
        """
        base = Path(path).expanduser().resolve()
        if not base.exists():
            return f"[error] directory not found: {path}"
        try:
            matches = list(base.glob(pattern))
            matches.sort(key=lambda p: -p.stat().st_mtime if p.exists() else 0)
            paths = [str(m.relative_to(base)) for m in matches if m.is_file()]

            output = []
            limit = 100
            if not paths:
                output.append("No files found")
            else:
                output.extend(paths[:limit])
                if len(paths) > limit:
                    output.append("")
                    output.append(f"(Results are truncated: showing first {limit} results.)")

            return "\n".join(output)
        except Exception as exc:
            return f"[error] {exc}"


class OpencodeGrepTool(Tool):
    name = "grep"
    description = (
        "Searches for a regular expression pattern within file contents. "
        "Filter files with the include parameter."
    )

    def run(self, pattern: str, path: str = ".", include: str = "") -> str:
        """
        Args:
            pattern: The regex pattern to search for in file contents.
            path: The directory to search in. Defaults to current working directory.
            include: File pattern to include in the search (e.g. "*.js", "*.{ts,tsx}").
        """
        import re

        base = Path(path).expanduser().resolve()
        if not base.exists():
            return f"[error] path not found: {path}"

        file_glob = include if include else "*"
        if base.is_file():
            files = [base]
        else:
            files = [f for f in base.rglob("*") if f.is_file() and fnmatch.fnmatch(f.name, file_glob)]

        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"[error] invalid regex: {exc}"

        matches = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        matches.append({
                            "path": str(f.relative_to(base)) if base.is_dir() else str(f),
                            "line": i,
                            "text": line.rstrip(),
                            "mtime": f.stat().st_mtime,
                        })
            except Exception:
                continue

        matches.sort(key=lambda x: x["mtime"], reverse=True)

        limit = 100
        truncated = len(matches) > limit
        final_matches = matches[:limit]

        if not final_matches:
            return "No files found"

        output = [f"Found {len(matches)} matches" + (f" (showing first {limit})" if truncated else "")]

        current_file = ""
        for m in final_matches:
            if current_file != m["path"]:
                if current_file:
                    output.append("")
                current_file = m["path"]
                output.append(f"{m['path']}:")

            line_text = m["text"]
            if len(line_text) > 2000:
                line_text = line_text[:2000] + "..."
            output.append(f"  Line {m['line']}: {line_text}")

        if truncated:
            output.append("")
            output.append(f"(Results truncated: showing {limit} of {len(matches)} matches)")

        return "\n".join(output)


class OpencodeEditTool(Tool):
    name = "edit"
    description = (
        "Replaces text within a file. By default, replaces a single occurrence. "
        "Set replaceAll=true to replace every instance of oldString. "
        "Allows flexible matching (whitespace normalization, etc)."
    )

    def run(self, filePath: str, oldString: str, newString: str, replaceAll: bool = False) -> str:
        """
        Args:
            filePath: The absolute path to the file to modify.
            oldString: The text to replace.
            newString: The text to replace it with.
            replaceAll: Replace all occurrences of oldString (default false).
        """
        p = Path(filePath).expanduser()
        if not p.exists():
            return f"[error] file not found: {filePath}"
        if not p.is_file():
            return f"[error] not a file: {filePath}"

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"[error] could not read: {exc}"

        if oldString == newString:
            return "No changes to apply: oldString and newString are identical."

        if oldString in content:
            if replaceAll:
                new_content = content.replace(oldString, newString)
            else:
                new_content = content.replace(oldString, newString, 1)
        else:
            # Try trimming
            if oldString.strip() in content:
                oldString = oldString.strip()
                if replaceAll:
                    new_content = content.replace(oldString, newString)
                else:
                    new_content = content.replace(oldString, newString, 1)
            else:
                return "[error] Could not find oldString in the file. It must match exactly."

        try:
            p.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return f"[error] could not write: {exc}"

        return "Edit applied successfully."


class OpencodeBashTool(Tool):
    name = "bash"
    description = "Executes a shell command. Use for git, npm, build tools, etc."

    def run(self, command: str, timeout: int = 120000, workdir: str = "", description: str = "") -> str:
        """
        Args:
            command: The command to execute.
            timeout: Optional timeout in milliseconds. Defaults to 120000 (2 minutes).
            workdir: The working directory to run the command in. Defaults to cwd.
            description: Brief description of what this command does.
        """
        cwd = workdir if workdir else os.getcwd()
        timeout_s = timeout / 1000.0

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=cwd,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if not output and result.returncode == 0:
                output = "[command executed successfully with no output]"
            elif not output:
                output = f"[exit code {result.returncode}]"

            return output
        except subprocess.TimeoutExpired:
            return f"[error] command timed out after {timeout}ms"
        except Exception as exc:
            return f"[error] {exc}"


class OpencodeWebFetchTool(Tool):
    name = "webfetch"
    description = "Fetches content from a URL."

    def run(self, url: str, format: str = "markdown", timeout: int = 30) -> str:
        """
        Args:
            url: The URL to fetch content from.
            format: The format to return (text, markdown, html). Defaults to markdown.
            timeout: Optional timeout in seconds.
        """
        import httpx
        import re
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                resp = client.get(url)
                resp.raise_for_status()

                text = resp.text

                if format == "markdown":
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()

                return text
        except Exception as exc:
            return f"[error] {exc}"


class OpencodeWebSearchTool(Tool):
    name = "websearch"
    description = "Searches the web for information."

    def run(self, query: str, numResults: int = 8, livecrawl: str = "fallback", type: str = "auto", contextMaxCharacters: int = 10000) -> str:
        """
        Args:
            query: Websearch query.
            numResults: Number of results (default 8).
            livecrawl: 'fallback' or 'preferred'.
            type: 'auto', 'fast', or 'deep'.
            contextMaxCharacters: Max chars for context.
        """
        from urllib.parse import quote_plus
        import re
        import httpx

        # Fallback to DDG as we don't have Exa API key here
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            with httpx.Client(follow_redirects=True, timeout=10) as client:
                resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()

            # Simple parsing
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', resp.text, re.S)
            urls   = re.findall(r'class="result__url"[^>]*>\s*(.*?)\s*</a>', resp.text, re.S)
            snips  = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.S)

            results = []
            for i, (t, u, s) in enumerate(zip(titles, urls, snips)):
                if i >= numResults:
                    break
                results.append(f"**{t.strip()}**\n{u.strip()}\n{s.strip()}")

            return "\n\n".join(results) if results else "No results found."
        except Exception as exc:
            return f"[error] {exc}"


class OpencodeTodoWriteTool(Tool):
    name = "todowrite"
    description = "Creates and manages a structured task list."

    def run(self, todos: list) -> str:
        """
        Args:
            todos: List of {id, content, status} dicts.
        """
        path = Path(".agent_todos.json")
        try:
            path.write_text(json.dumps(todos, indent=2), encoding="utf-8")
            return f"Saved {len(todos)} todos."
        except Exception as exc:
            return f"[error] {exc}"


class OpencodeTodoReadTool(Tool):
    name = "todoread"
    description = "Reads the todo list."

    def run(self) -> str:
        path = Path(".agent_todos.json")
        if not path.exists():
            return "[]"
        return path.read_text(encoding="utf-8")


class OpencodePlanExitTool(Tool):
    name = "plan_exit"
    description = "Signal that planning is complete and request permission to proceed with implementation."

    def run(self) -> str:
        return "User approved switching to build agent. Wait for further instructions."


class OpencodeTaskTool(Tool):
    name = "task"
    description = "Delegate tasks to specialized subagents."

    def run(self, description: str, prompt: str, subagent_type: str, task_id: str = "", command: str = "") -> str:
        """
        Args:
            description: Task description.
            prompt: Task prompt.
            subagent_type: Agent type.
            task_id: Optional ID to resume.
            command: Optional triggering command.
        """
        return f"[task] Delegated '{description}' to {subagent_type}. (Mock implementation)"


class OpencodeApplyPatchTool(Tool):
    name = "apply_patch"
    description = (
        "Apply a unified diff patch to the filesystem. "
        "Can handle additions, deletions, updates, and moves."
    )

    def run(self, patchText: str) -> str:
        """
        Args:
            patchText: The full patch text that describes all changes to be made.
        """
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
                tmp.write(patchText)
                tmp_path = tmp.name

            proc = subprocess.run(["patch", "-p1", "-i", tmp_path], capture_output=True, text=True)
            os.remove(tmp_path)

            if proc.returncode == 0:
                return f"Patch applied successfully.\n{proc.stdout}"
            else:
                return f"[error] patch command failed: {proc.stderr}\n{proc.stdout}"
        except Exception as exc:
            return f"[error] apply_patch failed: {exc}"


class OpencodeCodeSearchTool(Tool):
    name = "codesearch"
    description = "Search for code context, APIs, libraries, and SDKs."

    def run(self, query: str, tokensNum: int = 5000) -> str:
        """
        Args:
            query: Search query.
            tokensNum: Number of tokens to return.
        """
        return f"[codesearch] Searching for '{query}' (mock). No external API access configured."


class OpencodeLspTool(Tool):
    name = "lsp"
    description = "Language Server Protocol (LSP) tool for code intelligence."

    def run(self, operation: str, filePath: str, line: int, character: int) -> str:
        """
        Args:
            operation: LSP operation (goToDefinition, findReferences, etc.)
            filePath: File path.
            line: 1-based line number.
            character: 1-based character offset.
        """
        return f"[lsp] {operation} at {filePath}:{line}:{character} (LSP not available in this environment)"


class OpencodeMultiEditTool(Tool):
    name = "multiedit"
    description = "Perform multiple edits sequentially on a single file."

    def run(self, filePath: str, edits: list[dict]) -> str:
        """
        Args:
            filePath: The absolute path to the file to modify.
            edits: Array of edit operations {filePath, oldString, newString, replaceAll}.
        """
        edit_tool = OpencodeEditTool()
        results = []
        for edit in edits:
            if "oldString" not in edit or "newString" not in edit:
                return "[error] Invalid edit object: missing oldString or newString"

            res = edit_tool.run(
                filePath=filePath,
                oldString=edit["oldString"],
                newString=edit["newString"],
                replaceAll=edit.get("replaceAll", False),
            )
            results.append(res)
            if "[error]" in res:
                return f"Multiedit failed at step: {res}\nPrevious steps: {results[:-1]}"

        return f"Applied {len(results)} edits successfully.\nLast result: {results[-1]}"


class OpencodeQuestionTool(Tool):
    name = "question"
    description = "Ask the user questions."

    def run(self, questions: list) -> str:
        """
        Args:
            questions: List of question objects.
        """
        q_texts = [f"- {q.get('question')}" for q in questions]
        return "[question] The agent has questions:\n" + "\n".join(q_texts)


class OpencodeSkillTool(Tool):
    name = "skill"
    description = "Load a specialized skill."

    def run(self, name: str) -> str:
        """
        Args:
            name: Name of the skill to load.
        """
        return f"[skill] Loading skill '{name}' (mock). Skill content would appear here."


class OpencodeBatchTool(Tool):
    name = "batch"
    description = "Execute multiple tools in parallel."

    def run(self, tool_calls: list) -> str:
        """
        Args:
            tool_calls: Array of {tool, parameters} objects.
        """
        results = []
        for call in tool_calls:
            tool_name = call.get("tool")
            params = call.get("parameters", {})

            try:
                if tool_name == "read":
                    res = OpencodeReadTool().run(**params)
                elif tool_name == "write":
                    res = OpencodeWriteTool().run(**params)
                else:
                    res = f"[error] Batch tool: unknown tool '{tool_name}' or execution not supported in this mock."

                results.append(f"--- {tool_name} ---\n{res}")
            except Exception as exc:
                results.append(f"--- {tool_name} ---\n[error] {exc}")

        return "\n".join(results)
