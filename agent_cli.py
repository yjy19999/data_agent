#!/usr/bin/env python3
"""
agent_cli.py — llm-agent CLI entry point, compatible with processline.py.

Implements the ``llm-agent run`` interface so processline.py can invoke
this agent as a subprocess drop-in for any pipeline expecting:

    llm-agent run --local --query "..." --llm_name hosted_vllm/qwen \\
        --llm_base_url http://127.0.0.1:8000/v1 --api_key EMPTY \\
        --max_execution_time 7200 --max_tokens_per_call 4000 \\
        --max_token_limit 120000 \\
        --output_root_dir /path/to/output --work_root_dir /path/to/work

Exit codes:
    0  — task completed and tests passed
    1  — task failed or tests did not pass
    124 — execution timed out (SIGALRM, Unix only)
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import uuid
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# CLI definition
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-agent",
        description="LLM coding agent — processline.py compatible CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the coding agent on a single query")

    # processline.py flags (exact names preserved)
    run_p.add_argument(
        "--local", action="store_true",
        help="Run locally (required by processline.py; always true here)",
    )
    run_p.add_argument(
        "--query", required=True,
        help="Task / problem description to solve",
    )
    run_p.add_argument(
        "--llm_name", default=None,
        help="Model identifier, e.g. 'hosted_vllm/qwen' or 'qwen'. "
             "The part after the last '/' is used as the model name.",
    )
    run_p.add_argument(
        "--llm_base_url", default=None,
        help="OpenAI-compatible base URL (e.g. http://127.0.0.1:8000/v1)",
    )
    run_p.add_argument(
        "--api_key", default=None,
        help="API key (use 'EMPTY' for local vLLM)",
    )
    run_p.add_argument(
        "--max_execution_time", type=int, default=7200,
        help="Wall-clock timeout in seconds (default 7200). "
             "Kills the process via SIGALRM on Unix.",
    )
    run_p.add_argument(
        "--max_tokens_per_call", type=int, default=4000,
        help="Max tokens the LLM may generate per single call. "
             "Mapped to Config.compression_tool_budget_tokens as a proxy.",
    )
    run_p.add_argument(
        "--max_token_limit", type=int, default=120000,
        help="Total context window size (tokens). "
             "Mapped to Config.context_limit.",
    )
    run_p.add_argument(
        "--output_root_dir", default=None,
        help="Root directory for trace files and session output. "
             "Defaults to ./api_logs/",
    )
    run_p.add_argument(
        "--work_root_dir", default=None,
        help="Root directory for per-run workspaces. "
             "A unique subfolder is created inside for each run. "
             "Defaults to ./task_workspace/",
    )

    # Optional convenience overrides
    run_p.add_argument(
        "--max_iterations", type=int, default=5,
        help="Max test-fix iterations inside CodingTaskRunner (default 5)",
    )
    run_p.add_argument(
        "--quiet", action="store_true",
        help="Suppress live progress output",
    )

    return parser


# ---------------------------------------------------------------------------
# run subcommand
# ---------------------------------------------------------------------------

def _run(args: argparse.Namespace) -> int:
    from agent import CodingTaskRunner, Config

    # --- Model name ----------------------------------------------------------
    # llm_name can be "hosted_vllm/qwen" or just "qwen"
    model: str | None = None
    if args.llm_name:
        model = args.llm_name.split("/")[-1]

    # --- Config --------------------------------------------------------------
    config_kwargs: dict = {}
    if args.llm_base_url:
        config_kwargs["base_url"] = args.llm_base_url
    if args.api_key:
        config_kwargs["api_key"] = args.api_key
    if model:
        config_kwargs["model"] = model
    if args.max_token_limit:
        config_kwargs["context_limit"] = args.max_token_limit
    if args.max_tokens_per_call:
        # Use as the tool-output budget inside compressed history
        config_kwargs["compression_tool_budget_tokens"] = args.max_tokens_per_call

    config = Config(**config_kwargs)

    # --- Session & workspace paths -------------------------------------------
    session_id = uuid.uuid4().hex[:12]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_label = f"agent_{ts}_{session_id}"

    work_root = Path(args.work_root_dir) if args.work_root_dir else Path("task_workspace")
    workspace = work_root / run_label
    workspace.mkdir(parents=True, exist_ok=True)

    out_root = Path(args.output_root_dir) if args.output_root_dir else Path("api_logs")
    out_root.mkdir(parents=True, exist_ok=True)

    # Point the agent logger at the requested output directory
    os.environ.setdefault("AGENT_LOG_DIR", str(out_root))

    # --- Timeout (Unix SIGALRM) ----------------------------------------------
    _arm_timeout(args.max_execution_time)

    # --- Run -----------------------------------------------------------------
    try:
        runner = CodingTaskRunner(
            workspace=workspace,
            config=config,
            max_fix_iterations=args.max_iterations,
            session_id=session_id,
        )
        result = runner.run(args.query, verbose=not args.quiet)
    finally:
        _disarm_timeout()

    # Exit 0 = passed, 1 = failed/error
    return 0 if result.status == "passed" else 1


# ---------------------------------------------------------------------------
# Timeout helpers (SIGALRM, Unix only)
# ---------------------------------------------------------------------------

def _arm_timeout(seconds: int) -> None:
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        return

    def _handler(signum: int, frame) -> None:  # noqa: ANN001
        print(
            f"\n[llm-agent] timeout: execution exceeded {seconds}s limit",
            file=sys.stderr,
        )
        sys.exit(124)

    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)


def _disarm_timeout() -> None:
    if hasattr(signal, "SIGALRM"):
        signal.alarm(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run":
        sys.exit(_run(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
