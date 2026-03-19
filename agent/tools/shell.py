from __future__ import annotations

import subprocess
from typing import Any

from .base import Tool


class OpenTerminalTool(Tool):
    name = "open_terminal"
    description = (
        "Open an interactive terminal window for the user. "
        "Use this when a task requires interactive input that cannot be automated — "
        "e.g. launching a Python/Node REPL, running an interactive debugger (pdb, ipdb), "
        "a TUI program (htop, vim, lazygit), or a setup wizard that prompts the user. "
        "The terminal opens in a bordered window; the agent resumes when the user exits "
        "(Ctrl+D or `exit`)."
    )

    def run(self, command: str | None = None) -> str:
        """
        Args:
            command: Program to launch (e.g. 'python', 'ipython', 'node', 'pdb script.py').
                     Defaults to the system shell when omitted.
        """
        from cli.terminal import open_terminal
        open_terminal(console=None, shell=command)
        return "Interactive session ended. Returned to agent."


class ShellTool(Tool):
    name = "shell"
    description = (
        "Run a shell command and return its stdout + stderr. "
        "Use for git, file operations, running scripts, installing packages, etc. "
        "Avoid interactive commands that require user input."
    )

    def run(self, command: str, timeout: int = 30) -> str:
        """
        Args:
            command: The shell command to execute.
            timeout: Max seconds to wait before killing the process.
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
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
