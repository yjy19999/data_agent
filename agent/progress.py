"""Shared Rich-powered progress printer base class.

Each runner subclasses ProgressPrinter and overrides:
  - PHASES         dict[phase_name, display_label]
  - _print_result  renders the final result panel
  - handle         call super().handle(event) for common events,
                   intercept runner-specific event types before that

Common events handled here:
  phase, text, tool_start, tool_end, usage, error, result
"""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .agent import TurnEvent


class ProgressPrinter:
    """Base Rich progress printer. All runners share this core event loop."""

    # Subclasses set this to map phase name → human label.
    PHASES: dict[str, str] = {}

    def __init__(self) -> None:
        self._console = Console()
        self._text_buf: list[str] = []
        self._tool_count = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def handle(self, event: TurnEvent) -> None:
        if event.type == "phase":
            self._flush_text()
            self._tool_count = 0
            self._console.print()
            self._console.rule(
                f"[bold cyan]>>> {self._phase_label(event.data)}[/]",
                style="cyan",
            )

        elif event.type == "text":
            self._text_buf.append(event.data)

        elif event.type == "tool_start":
            self._flush_text()
            self._tool_count += 1
            name = event.data.get("name", "?")
            args = event.data.get("arguments", {})
            summary = self._summarize_tool(name, args)
            self._console.print(
                f"  [dim]{self._tool_count}.[/] [bold yellow]{name}[/]"
                f"[dim]({summary})[/]"
            )

        elif event.type == "tool_end":
            result = event.data.get("result", "")
            first_line = result.split("\n")[0][:120] if result else ""
            if first_line.startswith("[ok]"):
                self._console.print(f"     [green]{first_line}[/]")
            elif first_line.startswith("[error]"):
                self._console.print(f"     [red]{first_line}[/]")
            else:
                self._console.print(f"     [dim]{first_line}[/]")

        elif event.type == "result":
            self._flush_text()
            self._print_result(event.data)

        elif event.type == "usage":
            pass

        elif event.type == "error":
            self._flush_text()
            self._console.print(f"  [bold red]Error:[/] {event.data}")

    def error(self, msg: str) -> None:
        """Call this when an unexpected exception is caught by the runner."""
        self._flush_text()
        self._console.print(Panel(
            f"[bold red]{msg}[/]",
            title="[red]Exception[/]",
            border_style="red",
        ))

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _phase_label(self, phase: str) -> str:
        return self.PHASES.get(phase, phase)

    def _print_result(self, data: Any) -> None:
        """Render the final result panel. Override in each runner's subclass."""

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _flush_text(self) -> None:
        if self._text_buf:
            text = "".join(self._text_buf).strip()
            if text:
                self._console.print()
                self._console.print(Markdown(text), style="white")
            self._text_buf.clear()

    @staticmethod
    def _summarize_tool(name: str, args: dict) -> str:
        """One-line summary of tool arguments for the progress display."""
        if name in ("shell", "Bash"):
            cmd = args.get("command", "")
            return (cmd[:77] + "...") if len(cmd) > 80 else cmd
        if "path" in args:
            return args["path"]
        if "file_path" in args:
            return args["file_path"]
        if "pattern" in args:
            return args["pattern"]
        for v in args.values():
            if isinstance(v, str):
                return (v[:57] + "...") if len(v) > 60 else v
        return ""
