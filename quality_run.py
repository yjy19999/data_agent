#!/usr/bin/env python3
"""
Run the DataQualityRunner against one or more data files.

Usage:
    python quality_run.py                                       # inspect ./sample/
    python quality_run.py data/sample.json                      # single file
    python quality_run.py data_dir/ --focus "Prioritize safety" # custom focus
    python quality_run.py --quiet data/                         # no live output
    python quality_run.py --model claude-opus-4-6 data/         # override model
"""
from __future__ import annotations

import argparse
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from agent import Config
from agent.data_quality_runner import DataQualityRunner, _DEFAULT_FOCUS


SAMPLE_DIR = Path(__file__).parent / "sample"

OUTPUT_ROOT = Path(__file__).parent / "output"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the data-quality inspection workflow")
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
        print(f"Cleaned output: {output_dir}")

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

    print(f"Model:      {config.model}")
    print(f"Output dir: {output_dir}")
    print(f"  files/      → {workspace}")
    print(f"  trajectory/ → {logs_dir}")
    print(f"  memory/     → {memory_dir}")
    print(f"Focus:      {focus[:80]}{'...' if len(focus) > 80 else ''}")
    print("Inputs:")
    for item in args.inputs:
        print(f"  - {Path(item).expanduser()}")
    print()

    runner = DataQualityRunner(
        workspace=workspace,
        config=config,
        session_id=session_id,
        logs_dir=logs_dir,
        memory_log_dir=memory_dir,
    )
    result = runner.run(args.inputs, focus=focus, verbose=not args.quiet)

    # Final summary — always printed regardless of --quiet
    print()
    print("=" * 60)
    print(f"Decision:   {result.status.upper()}")
    print(f"Manifest:   {result.manifest_file}")

    if result.schema_files:
        print("Schema:")
        for f in result.schema_files:
            print(f"  {f}")
    else:
        print("Schema:     (none)")

    if result.report_files:
        print("Reports:")
        for f in result.report_files:
            print(f"  {f}")
    else:
        print("Reports:    (none)")

    if result.overall_summary:
        summary = result.overall_summary
        print(f"Summary:    {summary[:120]}{'...' if len(summary) > 120 else ''}")

    if result.error:
        print(f"Error:      {result.error}")

    print("=" * 60)

    # Per-file listing with line count + byte size (mirrors task_run.py)
    all_output_files = (
        ([result.manifest_file] if result.manifest_file else [])
        + result.schema_files
        + result.report_files
    )
    if all_output_files:
        print("\nOutput files:")
        for f in all_output_files:
            p = workspace / f
            if p.exists():
                size = p.stat().st_size
                lines = p.read_text(errors="replace").count("\n") + 1
                print(f"  {f:<40} {lines:>4} lines  {size:>6} bytes")

    return 0 if result.status in {"accept", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
