#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from agent import Config
from agent.data_quality_runner import DataQualityRunner, _DEFAULT_FOCUS


_FORMAT_TO_PREFIX = {
    "openhands": "trace_openhands",
    "swe-agent": "trace_sweagent",
    "mini-swe-agent": "trace_miniswe",
    "both": "trace_openhands",
    "all": "trace_openhands",
    "none": "trace",
}

WORKSPACE_ROOT = Path(__file__).parent / "quality_workspace"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the data-quality inspection workflow")
    parser.add_argument("inputs", nargs="+", help="Input file(s) or folder(s) to inspect")
    parser.add_argument("--workspace", default=None, help="Workspace folder (overrides auto-naming)")
    parser.add_argument("--focus", default=None, help="Optional extra inspection guidance")
    parser.add_argument("--clean", action="store_true", help="Remove workspace before starting")
    parser.add_argument("--model", default=None, help="Override LLM model name")
    args = parser.parse_args()

    session_id = uuid.uuid4().hex[:12]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_format = os.getenv("LLM_LOG_FORMAT", "openhands").strip().lower().replace("_", "-")
    trace_prefix = _FORMAT_TO_PREFIX.get(log_format, "trace_openhands")

    if args.workspace:
        workspace = Path(args.workspace)
    else:
        folder_name = f"{trace_prefix}_{ts}_{session_id}_quality_workspace"
        workspace = WORKSPACE_ROOT / folder_name

    if args.clean and workspace.exists():
        shutil.rmtree(workspace)

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

    print(f"Model:     {config.model}")
    print(f"Workspace: {workspace}")
    print("Inputs:")
    for item in args.inputs:
        print(f"  - {Path(item).expanduser()}")
    print()

    runner = DataQualityRunner(
        workspace=workspace,
        config=config,
        session_id=session_id,
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
