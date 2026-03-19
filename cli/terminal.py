"""
Embedded terminal pane using Python's stdlib pty + pyte for ANSI rendering.

Architecture (mirrors gemini-cli's approach):
  PTY process (shell/command)
       ↓ raw bytes
  pyte ByteStream  →  pyte Screen  (cell buffer with colors/attrs)
       ↓
  Rich Text  (char by char, fg/bg/bold/italic/underline)
       ↓
  Console output

For interactive sessions (/terminal command):
  pty.spawn() handles full I/O passthrough — no rendering overhead needed.
  pyte is used when capturing and re-rendering command output inside the UI.
"""

from __future__ import annotations

import fcntl
import os
import pty
import select
import shutil
import struct
import sys
import termios
import tty
from typing import Callable

import pyte
from rich.console import Console
from rich.rule import Rule
from rich.style import Style
from rich.text import Text


# ── pyte → Rich color mapping ─────────────────────────────────────────────────

_PYTE_TO_RICH: dict[str, str] = {
    "default":      "",
    "black":        "black",
    "red":          "red",
    "green":        "green",
    "yellow":       "yellow",
    "blue":         "blue",
    "magenta":      "magenta",
    "cyan":         "cyan",
    "white":        "white",
    "brightblack":  "bright_black",
    "brightred":    "bright_red",
    "brightgreen":  "bright_green",
    "brightyellow": "bright_yellow",
    "brightblue":   "bright_blue",
    "brightmagenta":"bright_magenta",
    "brightcyan":   "bright_cyan",
    "brightwhite":  "bright_white",
}


def _rich_color(pyte_color: str) -> str | None:
    """Convert a pyte color value to a Rich-compatible color string."""
    if not pyte_color or pyte_color == "default":
        return None
    # pyte passes 24-bit colors as '#rrggbb'
    if pyte_color.startswith("#"):
        return pyte_color
    return _PYTE_TO_RICH.get(pyte_color.lower())


def screen_to_rich_lines(screen: pyte.Screen) -> list[Text]:
    """Render a pyte Screen buffer into a list of Rich Text lines."""
    lines: list[Text] = []
    for y in range(screen.lines):
        row = screen.buffer[y]
        line = Text()
        for x in range(screen.columns):
            char = row[x]
            ch = char.data or " "
            fg = _rich_color(char.fg)
            bg = _rich_color(char.bg)
            style = Style(
                color=fg or None,
                bgcolor=bg or None,
                bold=char.bold,
                italic=char.italics,
                underline=char.underscore,
                strike=char.strikethrough,
                reverse=char.reverse,
            )
            line.append(ch, style=style)
        lines.append(line)
    return lines


# ── Captured (non-interactive) run ───────────────────────────────────────────

def run_captured(
    command: list[str],
    console: Console,
    cols: int | None = None,
    rows: int | None = None,
) -> int:
    """
    Run a command in a PTY, feed output through pyte, render with Rich.
    Returns the exit code.
    """
    term_cols, term_rows = shutil.get_terminal_size((80, 24))
    cols = cols or term_cols
    rows = rows or max(10, term_rows - 6)

    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)

    master_fd, slave_fd = os.openpty()

    pid = os.fork()
    if pid == 0:
        # Child
        os.close(master_fd)
        os.setsid()
        import fcntl, struct
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(slave_fd)
        os.execvp(command[0], command)

    # Parent
    os.close(slave_fd)

    buf = b""
    while True:
        try:
            r, _, _ = select.select([master_fd], [], [], 0.1)
        except (ValueError, OSError):
            break
        if r:
            try:
                chunk = os.read(master_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            stream.feed(chunk)
        else:
            result = os.waitpid(pid, os.WNOHANG)
            if result[0] != 0:
                # Drain any remaining output
                try:
                    r2, _, _ = select.select([master_fd], [], [], 0.05)
                    if r2:
                        chunk = os.read(master_fd, 65536)
                        stream.feed(chunk)
                except OSError:
                    pass
                exit_code = result[1] >> 8
                break
    else:
        exit_code = 0

    os.close(master_fd)

    # Render the pyte screen
    for line in screen_to_rich_lines(screen):
        stripped = line.rstrip()
        if stripped:
            console.print(stripped)

    return exit_code


# ── Interactive terminal ──────────────────────────────────────────────────────

# TIOCSWINSZ ioctl to set PTY window size (not always exposed by termios).
_TIOCSWINSZ = 0x80087467 if sys.platform == "darwin" else 0x5414


def _spawn_interactive(shell: str, rows: int, cols: int, env: dict) -> None:
    """
    Fork, exec shell in a PTY sized (rows × cols), then run the I/O copy loop.
    Blocks until the shell exits.
    """
    master_fd, slave_fd = os.openpty()

    # Tell the PTY its logical size so programs like vim lay out correctly.
    fcntl.ioctl(slave_fd, _TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    pid = os.fork()
    if pid == 0:                        # ── child ──────────────────────────
        os.close(master_fd)
        os.setsid()                     # new session → PTY slave becomes ctty
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvpe(shell, [shell], env)
        os._exit(1)                     # unreachable unless exec fails

    # ── parent ───────────────────────────────────────────────────────────────
    os.close(slave_fd)

    mode = None
    try:
        mode = termios.tcgetattr(0)
        tty.setraw(0)
    except termios.error:
        pass

    try:
        while True:
            rfds, _, _ = select.select([master_fd, 0], [], [])
            if master_fd in rfds:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                os.write(1, data)
            if 0 in rfds:
                try:
                    data = os.read(0, 1024)
                except OSError:
                    break
                if not data:
                    break
                try:
                    os.write(master_fd, data)
                except OSError:
                    break
    finally:
        # TCSAFLUSH discards any bytes zsh left in stdin during exit teardown,
        # preventing prompt_toolkit from reading them as a spurious EOF/Ctrl-C.
        if mode:
            termios.tcsetattr(0, termios.TCSAFLUSH, mode)
        os.close(master_fd)

    os.waitpid(pid, 0)


def open_terminal(
    console: Console | None = None,
    shell: str | None = None,
    on_exit: Callable[[], None] | None = None,
) -> None:
    """
    Open an embedded interactive terminal in a bordered alternate-screen window.

    Layout (alternate screen, so agent output is fully preserved on exit):
      row 1        : top border  ── /bin/zsh ──────────────────────────────────
      rows 2..N-1  : shell content (scrolling region — borders never scroll away)
      row N        : bottom border  ── Ctrl+D or exit to return ────────────────

    console is optional; when None a plain Rule is printed on return.
    """
    if sys.platform == "win32":
        msg = "Embedded terminal is not supported on Windows."
        if console:
            console.print(f"[red]{msg}[/red]")
        else:
            print(msg)
        return

    shell = shell or os.environ.get("SHELL", "/bin/bash")
    cols, rows = shutil.get_terminal_size((80, 24))

    # ── Build border strings ──────────────────────────────────────────────────
    label = f"  {shell}  "
    pad = max(0, cols - len(label))
    top_border = "─" * (pad // 2) + label + "─" * (pad - pad // 2)

    hint = "  Ctrl+D or exit to return  "
    pad2 = max(0, cols - len(hint))
    bot_border = "─" * (pad2 // 2) + hint + "─" * (pad2 - pad2 // 2)

    inner_rows = rows - 2   # rows 2 .. N-1

    # ── Switch to alternate screen and draw the frame ─────────────────────────
    sys.stdout.write(
        "\033[?1049h"           # enter alternate screen (saves current content)
        "\033[2J"               # clear alternate screen
        "\033[1;1H"             # cursor → top-left
        + top_border[:cols]     # row 1: top border
        + f"\033[{rows};1H"     # cursor → bottom row
        + bot_border[:cols]     # row N: bottom border
        + "\033[2;1H"           # cursor → first content row
    )
    sys.stdout.flush()

    # Restrict scrolling to the inner rows so the borders stay pinned.
    sys.stdout.write(f"\033[2;{rows - 1}r\033[2;1H")
    sys.stdout.flush()

    env = os.environ.copy()
    env["SHELL_SESSION_DID_INIT"] = "1"     # suppress macOS zsh "Restored session"

    try:
        _spawn_interactive(shell, rows=inner_rows, cols=cols, env=env)
    except Exception as exc:
        sys.stdout.write(f"\r\n[terminal error] {exc}\r\n")
        sys.stdout.flush()
    finally:
        sys.stdout.write(
            "\033[r"        # reset scroll region to full screen
            "\033[?1049l"   # exit alternate screen → original content restored
        )
        sys.stdout.flush()

    if console:
        console.print()
        console.print(Rule("  agent  ", style="#555555"))
        console.print()
    else:
        cols = shutil.get_terminal_size((80, 24)).columns
        print("\n" + "─" * cols + "\n")

    if on_exit:
        on_exit()
