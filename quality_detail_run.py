#!/usr/bin/env python3
"""
Run the DataQualityDetailRunner against one or more data files.

Unlike quality_run.py, this runner guarantees that the agent reads every block
of every data record — no sampling, no truncation, no agent discretion.

Usage:
    python quality_detail_run.py                                       # inspect ./sample/
    python quality_detail_run.py data/sample.json                      # single file
    python quality_detail_run.py data_dir/ --focus "Prioritize safety" # custom focus
    python quality_detail_run.py --quiet data/                         # no live output
    python quality_detail_run.py --model claude-opus-4-6 data/         # override model
"""
from __future__ import annotations

import argparse
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from agent import Config
from agent.data_quality_runner import _DEFAULT_FOCUS
from agent.data_quality_detail_runner import DataQualityDetailRunner

console = Console()

SAMPLE_DIR = Path(__file__).parent / "sample"
OUTPUT_ROOT = Path(__file__).parent / "output"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the detailed data-quality inspection workflow (full block coverage)"
    )
    parser.add_argument(
        "inputs", nargs="*",
        help="Input file(s) or folder(s) to inspect (defaults to all files in ./sample)",
    )
    parser.add_argument("--workspace", default=None, help="Override the files/ subfolder path")
    parser.add_argument("--focus", default=None, help="Optional extra inspection guidance")
    parser.add_argument("--clean", action="store_true", help="Remove output folder before starting")
    parser.add_argument("--quiet", action="store_true", help="No live output")
    parser.add_argument("--model", default=None, help="Override LLM model name")
    args = parser.parse_args()

    if not args.inputs:
        if not SAMPLE_DIR.exists():
            parser.error("No inputs given and ./sample folder does not exist")
        args.inputs = sorted(str(p) for p in SAMPLE_DIR.iterdir() if p.is_file())
        if not args.inputs:
            parser.error("No inputs given and ./sample folder is empty")

    session_id = uuid.uuid4().hex[:12]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_folder = f"{ts}_{session_id}"

    output_dir = OUTPUT_ROOT / run_folder
    workspace  = Path(args.workspace) if args.workspace else output_dir / "files"
    logs_dir   = output_dir / "trajectory"
    memory_dir = output_dir / "memory"

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
        console.print(f"[yellow]Cleaned output:[/yellow] {output_dir}")

    workspace.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)

    config = Config()
    if args.model:
        config = Config(
            base_url=config.base_url,
            api_key=config.api_key,
            model=args.model,
            stream=config.stream,
            max_tool_iterations=config.max_tool_iterations,
            context_limit=config.context_limit,
            tool_profile=config.tool_profile,
            compression_threshold=config.compression_threshold,
        )

    focus = args.focus or _DEFAULT_FOCUS

    # ── Pre-run config panel ────────────────────────────────────────────────
    cfg_table = Table(box=None, show_header=False, padding=(0, 1))
    cfg_table.add_column(style="bold cyan", no_wrap=True)
    cfg_table.add_column()
    cfg_table.add_row("Mode",      "[bold magenta]Detail (full block coverage)[/bold magenta]")
    cfg_table.add_row("Model",     config.model)
    cfg_table.add_row("Output",    str(output_dir))
    cfg_table.add_row("  files/",  str(workspace))
    cfg_table.add_row("  traj/",   str(logs_dir))
    cfg_table.add_row("  memory/", str(memory_dir))
    cfg_table.add_row("Focus",     focus[:80] + ("..." if len(focus) > 80 else ""))
    for i, item in enumerate(args.inputs):
        label = "Inputs" if i == 0 else ""
        cfg_table.add_row(label, str(Path(item).expanduser()))
    console.print(Panel(cfg_table, title="[bold]Run Configuration[/bold]", border_style="magenta"))

    runner = DataQualityDetailRunner(
        workspace=workspace,
        config=config,
        session_id=session_id,
        logs_dir=logs_dir,
        memory_log_dir=memory_dir,
    )
    result = runner.run(args.inputs, focus=focus, verbose=not args.quiet)

    # ── Result panel ────────────────────────────────────────────────────────
    status = result.status.upper()
    if result.status == "accept":
        status_text = Text(f"✓  {status}", style="bold green")
        border = "green"
    elif result.status == "review":
        status_text = Text(f"~  {status}", style="bold yellow")
        border = "yellow"
    else:
        status_text = Text(f"✗  {status}", style="bold red")
        border = "red"

    res_table = Table(box=None, show_header=False, padding=(0, 1))
    res_table.add_column(style="bold cyan", no_wrap=True)
    res_table.add_column()
    res_table.add_row("Decision",  status_text)
    res_table.add_row("Manifest",  result.manifest_file or "(none)")
    res_table.add_row("Schema",    ", ".join(result.schema_files) or "(none)")
    res_table.add_row("Reports",   ", ".join(result.report_files) or "(none)")
    if result.overall_summary:
        summary = result.overall_summary
        res_table.add_row("Summary", summary[:120] + ("..." if len(summary) > 120 else ""))
    if result.error:
        res_table.add_row("Error", Text(result.error, style="red"))
    console.print(Panel(res_table, title="[bold]Result[/bold]", border_style=border))

    # ── Output files table ──────────────────────────────────────────────────
    all_output_files = (
        ([result.manifest_file] if result.manifest_file else [])
        + result.schema_files
        + result.report_files
    )
    if all_output_files:
        files_table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        files_table.add_column("File", style="white")
        files_table.add_column("Lines", justify="right", style="dim")
        files_table.add_column("Bytes", justify="right", style="dim")
        for f in all_output_files:
            p = workspace / f
            if p.exists():
                size  = p.stat().st_size
                lines = p.read_text(errors="replace").count("\n") + 1
                files_table.add_row(f, str(lines), f"{size:,}")
        console.print(Panel(files_table, title="[bold]Output Files[/bold]", border_style="blue"))

    return 0 if result.status in {"accept", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
