# Repo Scan

## Conclusion

This repository is a Python AI-agent framework with two main execution paths:

- `run.py` starts the interactive terminal CLI.
- `task_run.py` runs an automated coding-task workflow that writes into `task_workspace/`.

The core implementation lives in `agent/` and `cli/`.

## Active Code Areas

- `agent/`: agent loop, API client, config, session handling, compression, telemetry, sandboxing, and tool registry/profile logic.
- `cli/`: Rich-based terminal interface and command handling.
- `tests/`: targeted coverage for API, sandbox, and task-runner behavior.

## Supporting And Non-Core Areas

- `agent_bak/` and `cli_bak/`: backup copies, likely not part of the active runtime.
- `api_logs/`: generated traces and request/response logs.
- `task_workspace/`: generated task execution outputs and per-run artifacts.
- `__pycache__/`, `.pytest_cache/`: generated caches.

## Entry Points

- `run.py`: imports and runs `cli.main.main`.
- `task_run.py`: builds a `CodingTaskRunner`, creates or reuses a workspace, and runs iterative code/test/fix cycles.

## Configuration

Configuration is loaded from `.env` through `agent/config.py`. Key settings include:

- model and API endpoint
- tool profile selection
- context/compression limits
- retry behavior
- logging format

## Dependencies

The repository uses a small Python dependency set:

- `openai`
- `pydantic`
- `python-dotenv`
- `rich`
- `prompt-toolkit`
- `httpx`
- `pyte`

## Practical Takeaway

If we are making functional changes, the primary files to inspect first are:

- `agent/agent.py`
- `agent/task_runner.py`
- `agent/config.py`
- `cli/main.py`

The backup directories and generated artifacts should generally be ignored unless we are doing comparison, migration, or cleanup work.
