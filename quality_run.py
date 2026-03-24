#!/usr/bin/env python3
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
    parser.add_argument("inputs", nargs="*", help="Input file(s) or folder(s) to inspect (defaults to all files in ./sample)")
    parser.add_argument("--workspace", default=None, help="Override the files/ subfolder path")
    parser.add_argument("--focus", default=None, help="Optional extra inspection guidance")
    parser.add_argument("--clean", action="store_true", help="Remove output folder before starting")
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

    print(f"Model:      {config.model}")
    print(f"Output dir: {output_dir}")
    print(f"  files/      → {workspace}")
    print(f"  trajectory/ → {logs_dir}")
    print(f"  memory/     → {memory_dir}")
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
    result = runner.run(args.inputs, focus=args.focus or _DEFAULT_FOCUS)

    print("=" * 60)
    print(f"Decision:   {result.status.upper()}")
    print(f"Manifest:   {result.manifest_file}")
    print(f"Schema:     {result.schema_files}")
    print(f"Reports:    {result.report_files}")
    if result.overall_summary:
        print(f"Summary:    {result.overall_summary}")
    if result.error:
        print(f"Error:      {result.error}")
    print("=" * 60)
    return 0 if result.status in {"accept", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
