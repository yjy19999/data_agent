"""
Sandboxed tool execution.

SandboxedRegistry wraps a ToolRegistry to enforce all file operations and
shell commands stay within a designated workspace folder.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .tools.base import Tool, ToolRegistry

# Parameter names that hold file/directory paths (covers all wired profiles)
_SINGLE_PATH_PARAMS = {
    "path",
    "file_path",
    "filePath",
    "absolute_path",
    "directory",
    "dir_path",
    "workdir",
}
_LIST_PATH_PARAMS = {"paths"}
# Tool names that run shell commands
_SHELL_TOOL_NAMES = {"shell", "bash", "run_shell_command"}


def _resolve_within(raw_path: str, sandbox: Path) -> Path:
    """
    Resolve a path so it's guaranteed to be inside the sandbox.

    - Absolute paths: must be under sandbox, otherwise rejected.
    - Relative paths: resolved relative to sandbox.
    - Symlinks / '..' traversal: resolved and checked.
    """
    p = Path(raw_path).expanduser()
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (sandbox / p).resolve()
    # Ensure resolved path is within sandbox
    sandbox_resolved = sandbox.resolve()
    try:
        resolved.relative_to(sandbox_resolved)
    except ValueError:
        raise PermissionError(
            f"Path escapes sandbox: {raw_path!r} resolves to {resolved} "
            f"which is outside {sandbox_resolved}"
        )
    return resolved


class SandboxedRegistry(ToolRegistry):
    """
    A ToolRegistry that constrains all tool operations to a workspace folder.

    - File tool path arguments are resolved within the sandbox.
    - Shell commands execute with cwd set to the sandbox.
    - Paths outside the sandbox are rejected with a clear error.
    """

    def __init__(self, workspace: str | Path):
        super().__init__()
        self.workspace = Path(workspace).resolve()
        if not self.workspace.exists():
            self.workspace.mkdir(parents=True, exist_ok=True)

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """
        Execute a tool with sandboxed path resolution.
        """
        # Shell commands: delegate to sandboxed shell execution
        if name.lower() in _SHELL_TOOL_NAMES:
            return self._sandboxed_shell(name, arguments)

        # Rewrite path arguments to be absolute within sandbox
        try:
            arguments = self._rewrite_paths(arguments)
        except PermissionError as e:
            return f"[error] {e}"

        return super().execute(name, arguments)

    def _rewrite_paths(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve and validate all path-like arguments."""
        args = dict(arguments)
        for param in _SINGLE_PATH_PARAMS:
            if param in args and isinstance(args[param], str):
                resolved = _resolve_within(args[param], self.workspace)
                args[param] = str(resolved)
        for param in _LIST_PATH_PARAMS:
            if param in args and isinstance(args[param], list):
                args[param] = [
                    str(_resolve_within(p, self.workspace))
                    for p in args[param]
                    if isinstance(p, str)
                ]
        return args

    def _sandboxed_shell(self, name: str, arguments: dict[str, Any]) -> str:
        """Run shell command with cwd locked to workspace."""
        tool = self._tools.get(name)
        if tool is None:
            return f"[error] unknown tool: {name!r}"
        command = arguments.get("command", "")
        timeout = arguments.get("timeout", 120)
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.workspace),
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
            return f"[error] command timed out after {timeout}s"
        except Exception as exc:
            return f"[error] {exc}"
