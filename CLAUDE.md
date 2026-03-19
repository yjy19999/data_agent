# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the interactive agent REPL
python run.py

# Run the automated coding task runner
python task_run.py                              # default task
python task_run.py "Build a stack class"        # custom task
python task_run.py --quiet --max-iterations 3 "Build X"
python task_run.py --model claude-opus-4-6 "Build Y"

# Run tests
pytest tests/ -v
```

There is no Makefile, tox, pyproject.toml, setup.py, or CI pipeline.

## Architecture

**OpenCode Agent** is a multi-provider AI agent CLI framework that provides a unified interface for running agents with different LLM backends (Claude, Gemini, GPT, Qwen, local models via Ollama) through any OpenAI-compatible API.

### Component Map

```
run.py                → Entry point: from cli.main import main; main()
task_run.py           → Standalone CodingTaskRunner with CLI args

agent/
├── agent.py          → Agent class: main turn loop, streaming, tool dispatch,
│                       plan-then-execute mode
├── api.py            → AgentAPI: sync/async wrapper around Agent
├── client.py         → LLMClient: OpenAI-compatible HTTP, streaming,
│                       ChatResponse for stream/non-stream
├── config.py         → Config (Pydantic): loads from .env, builds system prompts
├── compression.py    → CompressionService: 3-phase LLM-based history compression
│                       (truncate tool output → summarise old → self-correct)
├── session.py        → SessionRecordingService: save/resume to .gemini/sessions/
├── telemetry.py      → SessionMetrics, TokenUsageStats, ModelMetrics, ToolMetrics
├── logger.py         → APILogger: pluggable trace formats (OpenHands, SWE-agent,
│                       mini-SWE-agent), composite logger for multiple formats
├── retry.py          → retry_with_backoff: exponential backoff + jitter,
│                       respects Retry-After header
├── sandbox.py        → SandboxedRegistry: constrains all tool file ops to workspace
├── task_runner.py    → CodingTaskRunner: 8-phase automated coding pipeline
└── tools/
    ├── base.py       → Tool (ABC) + ToolRegistry: auto-generates JSON schema
    │                   from run() type hints + Google-style Args: docstrings
    ├── profiles.py   → ToolProfile + 7 named profiles, auto-detection from model name
    ├── shell.py      → ShellTool, OpenTerminalTool
    ├── files.py      → ReadFileTool, WriteFileTool, GlobTool, GrepTool,
    │                   ListDirTool, MultiEditTool, ReadManyFilesTool
    ├── web.py        → WebFetchTool, WebSearchTool
    ├── plan.py       → WritePlanTool, PLAN_READY_SENTINEL
    ├── task.py       → TaskTool
    ├── todo.py       → TodoReadTool, TodoWriteTool
    ├── claude.py     → Claude Code style tools (Bash, Read, Edit, Write, LS, etc.)
    ├── gemini.py     → Gemini CLI style tools (replace, read_file, grep_search, etc.)
    ├── qwen.py       → Qwen Coder style tools (edit, read_file, shell, lsp, etc.)
    └── notebook.py   → NotebookRead, NotebookEdit

cli/
├── main.py           → Rich-based REPL, slash commands, event rendering
├── input.py          → InputPrompt: prompt_toolkit input with history
├── terminal.py       → Terminal utilities
└── statusbar.py      → Status bar rendering
```

### Key Design Decisions

**Tool schema generation** is automatic: the framework inspects `run()` type hints and Google-style `Args:` docstrings to build the JSON schema sent to the LLM. To add a tool, subclass `Tool`, set `name`/`description`, implement `run()` with typed parameters and an `Args:` docstring, then register it.

**Tool profiles** (`agent/tools/profiles.py`) map model name patterns to curated tool sets. Auto-detection infers the profile from the model name:
- `claude-*` → `claude` profile (Claude Code-style: `Bash`, `Read`, `Edit`, etc.)
- `gemini-*` → `gemini` profile (Gemini CLI-style: `replace`, `read_file`, etc.)
- `gpt-*`, `o1-*`, `o3-*`, `o4-*` → `gpt` profile
- `qwen-*` → `qwen` profile
- others → `default` profile

**Context compression** (`agent/compression.py`) triggers at a configurable fraction of `LLM_CONTEXT_LIMIT`. Three-phase approach:
1. Truncate large tool outputs (budget-based)
2. Split history, summarise old portion via secondary LLM call
3. Self-correction probe to verify nothing was lost
Falls back to content truncation if summarisation fails or inflates. A hard safety net enforces the absolute context limit.

**Streaming events** — `Agent.run()` yields `TurnEvent` objects consumed by `cli/main.py` for incremental rendering. Event types: `text`, `tool_start`, `tool_end`, `usage`, `compressed`, `error`, `done`.

**Agent modes** — `agent.run()` for direct execution, `agent.generate_plan()` + `agent.execute()` for plan-then-execute.

**Sandboxing** (`agent/sandbox.py`) — `SandboxedRegistry` wraps tool operations so all file paths are resolved within a workspace folder. Used by `CodingTaskRunner`.

**Retry** (`agent/retry.py`) — Exponential backoff with ±30% jitter. Retries on network errors, rate limits (respects `Retry-After`), server errors.

**Trace logging** (`agent/logger.py`) — Pluggable formats via `APILogger` ABC. Supports OpenHands event-stream, SWE-agent trajectory, mini-SWE-agent flat message list. Composite logger can write multiple formats simultaneously.

### CodingTaskRunner Flow (task_run.py)

The task runner orchestrates an 8-phase automated coding loop:

0. **Phase 0 — Task Intake**: Agent analyses the task without writing code; produces `Task.md` with goal, inputs/outputs, constraints, modification scope, risks, and success criteria
1. **Phase 1 — Repo Reconnaissance**: Agent explores the workspace using tools (ls, read, grep, glob); produces `Repo.md` with relevant files, dependency graph, candidate modification points, and risky/sensitive modules
2. **Phase 2 — Plan / Solution Design**: Agent creates `Plan.md` with files to modify, changes per file, test plan, execution order, and expected risks
3. **Phase 3 — Write Code**: Agent creates implementation `.py` files following `Plan.md`
4. **Phase 4 — Write Tests**: Agent creates `test_*.py` files using pytest
5. **Phase 5 — Test & Fix Loop**: Runs `pytest` externally, feeds failures back to the agent for fixes, repeats up to `max_fix_iterations`
6. **Phase 6 — Review**: Agent reviews code and tests against `Task.md` requirements; produces `Review.md` with verdict (PASS/FAIL). If FAIL, loops back to Phase 4. Up to `max_review_iterations` rounds.
7. **Phase 7 — Write Documentation**: Agent produces four doc files:
   - `README.md` — user-facing: usage, API reference, known limitations
   - `CHANGES.md` — developer-facing: what changed and why, design decisions
   - `TESTS.md` — validation: test results, coverage gaps, how to run
   - `FOLLOWUPS.md` — honest about: unresolved problems, workarounds, next steps

Workspace folders are named to match the trace file: `trace_{format}_{ts}_{session_id}_workspace/` alongside `trace_{format}_{ts}_{session_id}.json` in `api_logs/`.

### Configuration (.env)

| Variable | Default | Notes |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama default |
| `LLM_API_KEY` | `local` | Use `local` for local LLMs |
| `LLM_MODEL` | `llama3.2` | Model name |
| `LLM_STREAM` | `true` | Enable streaming |
| `LLM_MAX_TOOL_ITERATIONS` | `10` | Max tool calls per user turn |
| `LLM_TOOL_PROFILE` | `auto` | `auto`, `claude`, `gemini`, `gpt`, `qwen`, `default`, `readonly`, `minimal` |
| `LLM_CONTEXT_LIMIT` | `200000` | Token context window |
| `LLM_COMPRESSION_THRESHOLD` | `0.5` | Fraction of context that triggers compression |
| `LLM_COMPRESSION_PRESERVE_FRACTION` | `0.3` | Fraction of recent history to keep verbatim |
| `LLM_COMPRESSION_TOOL_BUDGET_TOKENS` | `50000` | Max tokens of tool results in preserved history |
| `LLM_LOG_FORMAT` | `openhands` | `openhands`, `swe-agent`, `mini-swe-agent`, `both`, `all`, `none` |
| `LLM_READ_MAX_CHARS` | `100000` | Max chars per single read_file call |
| `LLM_READ_MANY_MAX_CHARS` | `200000` | Max chars across read_many_files |
| `LLM_RETRY_MAX_ATTEMPTS` | `5` | Max retry attempts on API failure |
| `LLM_RETRY_INITIAL_DELAY_MS` | `1000` | Starting retry delay |
| `LLM_RETRY_MAX_DELAY_MS` | `30000` | Max retry delay |

### CLI Slash Commands

`/plan`, `/verbose`, `/profile [name]`, `/reset`, `/history`, `/tools`, `/model <name>`, `/stats`, `/sessions`, `/resume <id>`, `/delete <id>`, `/exit`. Direct shell via `!cmd`.

### Session & Log Files

- `.gemini/sessions/` — saved conversation JSON (auto-created)
- `api_logs/` — trace files per format:
  - `trace_openhands_{ts}_{session_id}.json` — OpenHands event-stream
  - `trace_sweagent_{ts}_{session_id}.traj` — SWE-agent trajectory
  - `trace_miniswe_{ts}_{session_id}.json` — mini-SWE-agent flat messages
- `task_workspace/` — per-task workspace folders (named to match trace files)
- `.agent_todos.json` — todo list used by TodoRead/TodoWrite tools

### Dependencies (requirements.txt)

- `openai` — OpenAI SDK for API client
- `pydantic` — Config model
- `python-dotenv` — .env loading
- `rich` — Terminal UI (Console, Live, Panel, Table, Markdown, Syntax)
- `prompt-toolkit` — Input with history and auto-suggest
- `httpx` — HTTP transport (used via openai SDK, also used by WebFetchTool)
- `pyte` — Terminal emulator (used by cli/terminal.py)
