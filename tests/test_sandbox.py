"""
Tests for SandboxedRegistry (agent/sandbox.py).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.sandbox import SandboxedRegistry, _resolve_within
from agent.tools.base import Tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeReadTool(Tool):
    name = "read_file"
    description = "Read a file."
    last_path: str | None = None

    def run(self, path: str) -> str:
        self.last_path = path
        return f"[read] {path}"


class FakeWriteTool(Tool):
    name = "write_file"
    description = "Write a file."
    last_path: str | None = None

    def run(self, path: str, content: str = "") -> str:
        self.last_path = path
        return f"[wrote] {path}"


class FakeShellTool(Tool):
    name = "shell"
    description = "Run a command."

    def run(self, command: str, timeout: int = 30) -> str:
        return f"[ran] {command}"


class FakeGlobTool(Tool):
    name = "glob"
    description = "Glob files."
    last_directory: str | None = None

    def run(self, pattern: str, directory: str = ".") -> str:
        self.last_directory = directory
        return f"[glob] {pattern} in {directory}"


class FakeDirPathTool(Tool):
    name = "list_directory"
    description = "List dir by dir_path."
    last_dir_path: str | None = None

    def run(self, dir_path: str = ".") -> str:
        self.last_dir_path = dir_path
        return f"[ls] {dir_path}"


class FakeFilePathTool(Tool):
    name = "read"
    description = "Read by filePath."
    last_file_path: str | None = None

    def run(self, filePath: str) -> str:
        self.last_file_path = filePath
        return f"[read] {filePath}"


class FakeNotebookTool(Tool):
    name = "NotebookRead"
    description = "Read a notebook."
    last_notebook_path: str | None = None

    def run(self, notebook_path: str) -> str:
        self.last_notebook_path = notebook_path
        return f"[notebook] {notebook_path}"


class FakeListDirTool(Tool):
    name = "list_dir"
    description = "List dir."
    last_path: str | None = None

    def run(self, path: str = ".") -> str:
        self.last_path = path
        return f"[ls] {path}"


def make_sandbox(tmp_path: Path, tools: list[Tool] | None = None) -> SandboxedRegistry:
    sandbox = SandboxedRegistry(tmp_path)
    for tool in (tools or []):
        sandbox.register(tool)
    return sandbox


# ---------------------------------------------------------------------------
# _resolve_within
# ---------------------------------------------------------------------------

class TestResolveWithin:
    def test_relative_path(self, tmp_path):
        result = _resolve_within("foo.py", tmp_path)
        assert result == (tmp_path / "foo.py").resolve()

    def test_nested_relative(self, tmp_path):
        result = _resolve_within("src/main.py", tmp_path)
        assert result == (tmp_path / "src" / "main.py").resolve()

    def test_absolute_inside_sandbox(self, tmp_path):
        abs_path = str(tmp_path / "file.py")
        result = _resolve_within(abs_path, tmp_path)
        assert result == tmp_path.resolve() / "file.py"

    def test_absolute_outside_sandbox_rejected(self, tmp_path):
        with pytest.raises(PermissionError, match="escapes sandbox"):
            _resolve_within("/etc/passwd", tmp_path)

    def test_dotdot_escape_rejected(self, tmp_path):
        with pytest.raises(PermissionError, match="escapes sandbox"):
            _resolve_within("../../../etc/passwd", tmp_path)

    def test_dotdot_within_sandbox_ok(self, tmp_path):
        """sub/../file.py resolves to file.py which is still inside."""
        result = _resolve_within("sub/../file.py", tmp_path)
        assert result == (tmp_path / "file.py").resolve()

    def test_dot_path(self, tmp_path):
        result = _resolve_within(".", tmp_path)
        assert result == tmp_path.resolve()


# ---------------------------------------------------------------------------
# SandboxedRegistry — path rewriting
# ---------------------------------------------------------------------------

class TestPathRewriting:
    def test_read_file_path_rewritten(self, tmp_path):
        tool = FakeReadTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("read_file", {"path": "hello.py"})
        assert tool.last_path == str((tmp_path / "hello.py").resolve())

    def test_write_file_path_rewritten(self, tmp_path):
        tool = FakeWriteTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("write_file", {"path": "out.py", "content": "x=1"})
        assert tool.last_path == str((tmp_path / "out.py").resolve())

    def test_glob_directory_rewritten(self, tmp_path):
        tool = FakeGlobTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("glob", {"pattern": "*.py", "directory": "src"})
        assert tool.last_directory == str((tmp_path / "src").resolve())

    def test_list_dir_path_rewritten(self, tmp_path):
        tool = FakeListDirTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("list_dir", {"path": "."})
        assert tool.last_path == str(tmp_path.resolve())

    def test_dir_path_rewritten(self, tmp_path):
        tool = FakeDirPathTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("list_directory", {"dir_path": "src"})
        assert tool.last_dir_path == str((tmp_path / "src").resolve())

    def test_file_path_camel_case_rewritten(self, tmp_path):
        tool = FakeFilePathTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("read", {"filePath": "hello.py"})
        assert tool.last_file_path == str((tmp_path / "hello.py").resolve())

    def test_notebook_path_rewritten(self, tmp_path):
        tool = FakeNotebookTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("NotebookRead", {"notebook_path": "notes.ipynb"})
        assert tool.last_notebook_path == str((tmp_path / "notes.ipynb").resolve())

    def test_escape_blocked(self, tmp_path):
        tool = FakeReadTool()
        sandbox = make_sandbox(tmp_path, [tool])
        result = sandbox.execute("read_file", {"path": "/etc/passwd"})
        assert "[error]" in result
        assert "escapes sandbox" in result
        assert tool.last_path is None  # tool was never called

    def test_dotdot_escape_blocked(self, tmp_path):
        tool = FakeWriteTool()
        sandbox = make_sandbox(tmp_path, [tool])
        result = sandbox.execute("write_file", {"path": "../../evil.py", "content": "x"})
        assert "[error]" in result
        assert tool.last_path is None

    def test_notebook_path_escape_blocked(self, tmp_path):
        tool = FakeNotebookTool()
        sandbox = make_sandbox(tmp_path, [tool])
        result = sandbox.execute("NotebookRead", {"notebook_path": "/tmp/escape.ipynb"})
        assert "[error]" in result
        assert "escapes sandbox" in result
        assert tool.last_notebook_path is None


# ---------------------------------------------------------------------------
# SandboxedRegistry — shell sandboxing
# ---------------------------------------------------------------------------

class TestShellSandbox:
    def test_shell_runs_in_workspace(self, tmp_path):
        tool = FakeShellTool()
        sandbox = make_sandbox(tmp_path, [tool])
        # The sandbox overrides shell execution to use subprocess with cwd
        result = sandbox.execute("shell", {"command": "pwd"})
        # Since we use real subprocess, pwd should return the sandbox path
        assert str(tmp_path) in result or "[error]" not in result

    def test_shell_pwd_is_workspace(self, tmp_path):
        """Shell commands have their cwd set to the workspace."""
        tool = FakeShellTool()
        sandbox = make_sandbox(tmp_path, [tool])
        result = sandbox.execute("shell", {"command": "pwd"})
        # Result should be the resolved sandbox path
        assert result.strip() == str(tmp_path.resolve())

    def test_shell_creates_file_in_workspace(self, tmp_path):
        tool = FakeShellTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("shell", {"command": "touch created.txt"})
        assert (tmp_path / "created.txt").exists()

    def test_shell_timeout(self, tmp_path):
        tool = FakeShellTool()
        sandbox = make_sandbox(tmp_path, [tool])
        result = sandbox.execute("shell", {"command": "sleep 10", "timeout": 1})
        assert "timed out" in result

    def test_bash_runs_in_workspace(self, tmp_path):
        class FakeBashTool(Tool):
            name = "bash"
            description = "Run bash."

            def run(self, command: str, timeout: int = 30) -> str:
                return f"[ran] {command}"

        sandbox = make_sandbox(tmp_path, [FakeBashTool()])
        result = sandbox.execute("bash", {"command": "pwd"})
        assert result.strip() == str(tmp_path.resolve())

    def test_run_shell_command_runs_in_workspace(self, tmp_path):
        class FakeRunShellCommandTool(Tool):
            name = "run_shell_command"
            description = "Run shell command."

            def run(self, command: str, timeout: int = 30, directory: str = "") -> str:
                return f"[ran] {command}"

        sandbox = make_sandbox(tmp_path, [FakeRunShellCommandTool()])
        result = sandbox.execute("run_shell_command", {"command": "pwd"})
        assert result.strip() == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# SandboxedRegistry — workspace creation
# ---------------------------------------------------------------------------

class TestWorkspaceCreation:
    def test_creates_workspace_if_missing(self, tmp_path):
        new_dir = tmp_path / "sub" / "project"
        assert not new_dir.exists()
        sandbox = SandboxedRegistry(new_dir)
        assert new_dir.exists()
        assert sandbox.workspace == new_dir.resolve()

    def test_existing_workspace_ok(self, tmp_path):
        sandbox = SandboxedRegistry(tmp_path)
        assert sandbox.workspace == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Non-path arguments pass through unchanged
# ---------------------------------------------------------------------------

class TestPassthrough:
    def test_non_path_args_unchanged(self, tmp_path):
        """Arguments that aren't path-like pass through untouched."""

        class FakeGrepTool(Tool):
            name = "grep"
            description = "Search."
            received_args: dict = {}

            def run(self, pattern: str, path: str = ".", glob: str = "*", max_results: int = 50) -> str:
                self.received_args = {
                    "pattern": pattern, "path": path,
                    "glob": glob, "max_results": max_results,
                }
                return "[ok]"

        tool = FakeGrepTool()
        sandbox = make_sandbox(tmp_path, [tool])
        sandbox.execute("grep", {
            "pattern": "import os",
            "path": "src",
            "glob": "*.py",
            "max_results": 10,
        })
        assert tool.received_args["pattern"] == "import os"
        assert tool.received_args["glob"] == "*.py"
        assert tool.received_args["max_results"] == 10
        # path should be rewritten to absolute within sandbox
        assert str(tmp_path) in tool.received_args["path"]
