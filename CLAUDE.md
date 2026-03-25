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

# Run the data quality workflow
python quality_run.py                           # default: inspects ./sample/
python quality_run.py data/sample.json          # single file
python quality_run.py data_dir/ --focus "Prioritize safety"
python quality_run.py --model claude-opus-4-6 data/

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
quality_run.py        → Standalone DataQualityRunner with CLI args

agent/
├── agent.py          → Agent class: main turn loop, streaming, tool dispatch,
│                       plan-then-execute mode
├── agent_factory.py  → AgentFactory: builds a configured Agent for a task type;
│                       decouples tool-profile + system-prompt from runner plumbing
├── runner_registry.py→ RunnerRegistry: maps task-type names to default AgentFactory
│                       configs; profile resolution order: explicit kwarg >
│                       LLM_<NAME>_PROFILE > LLM_TOOL_PROFILE > registered default
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
├── task_runner.py    → CodingTaskRunner: 8-phase automated coding pipeline;
│                       uses RunnerRegistry for default AgentFactory ("claude" profile)
├── data_quality_runner.py → DataQualityRunner: 3-phase data inspection pipeline;
│                       uses RunnerRegistry for default AgentFactory ("datacheck" profile)
└── tools/
    ├── base.py       → Tool (ABC) + ToolRegistry: auto-generates JSON schema
    │                   from run() type hints + Google-style Args: docstrings
    ├── profiles.py   → ToolProfile + 10 named profiles, auto-detection from model name
    ├── data.py       → ReadDataTool: reads json/jsonl/json_gz/jsonl_gz with
    │                   field-level value truncation to guard LLM context window;
    │                   handles uuid\t{json} and plain {json} JSONL formats
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

**AgentFactory + RunnerRegistry** — separates *what tools/role* from *where to run*. Each runner type registers a default `(profile, system_prompt)` pair in `RunnerRegistry`. At runtime the factory wraps workspace setup, sandboxing, and session/log wiring. Profile resolution order:
1. Explicit `agent_factory=` kwarg passed to a runner
2. Per-runner env var `LLM_<NAME>_PROFILE` (e.g. `LLM_CODING_PROFILE=claude`, `LLM_QUALITY_PROFILE=datacheck`)
3. Global `LLM_TOOL_PROFILE` env var (when not `"auto"`)
4. Profile registered for that task type in the registry

To add a new task type: register an entry in `RunnerRegistry`, write a runner class that calls `registry.make_factory(name, config)`, and add an entry-point script.

**Tool profiles** (`agent/tools/profiles.py`) map model name patterns to curated tool sets. Auto-detection infers the profile from the model name:
- `claude-*` → `claude` profile (Claude Code-style: `Bash`, `Read`, `Edit`, etc.)
- `gemini-*` → `gemini` profile (Gemini CLI-style: `replace`, `read_file`, etc.)
- `opencode-*` → `opencode` profile
- `codex-*` → `codex` profile
- `gpt-*`, `o1-*`, `o3-*`, `o4-*` → `gpt` profile
- `qwen-*` → `qwen` profile
- others → `default` profile

**ReadDataTool context protection** (`agent/tools/data.py`) — uses *field-level value truncation* rather than raw string slicing. Long string values inside a record are replaced with `"[truncated: N chars]"` before JSON serialisation, so the agent always receives structurally-valid JSON with all keys visible. Nested dicts and lists are handled recursively. Hard caps: `max_records=5` records, `max_chars=8000` total output.

**Context compression** (`agent/compression.py`) triggers at a configurable fraction of `LLM_CONTEXT_LIMIT`. Three-phase approach:
1. Truncate large tool outputs (budget-based)
2. Split history, summarise old portion via secondary LLM call
3. Self-correction probe to verify nothing was lost
Falls back to content truncation if summarisation fails or inflates. A hard safety net enforces the absolute context limit.

**Streaming events** — `Agent.run()` yields `TurnEvent` objects consumed by `cli/main.py` for incremental rendering. Event types: `text`, `tool_start`, `tool_end`, `usage`, `compressed`, `error`, `done`.

**Agent modes** — `agent.run()` for direct execution, `agent.generate_plan()` + `agent.execute()` for plan-then-execute.

**Sandboxing** (`agent/sandbox.py`) — `SandboxedRegistry` wraps tool operations so all file paths are resolved within a workspace folder. Used by both `CodingTaskRunner` and `DataQualityRunner`.

**Retry** (`agent/retry.py`) — Exponential backoff with ±30% jitter. Retries on network errors, rate limits (respects `Retry-After`), server errors.

**Trace logging** (`agent/logger.py`) — Pluggable formats via `APILogger` ABC. Supports OpenHands event-stream, SWE-agent trajectory, mini-SWE-agent flat message list. Composite logger can write multiple formats simultaneously. Both runners produce trace files in `api_logs/`.

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

Default profile: `claude`. Workspace folders are named to match the trace file:
`trace_{format}_{ts}_{session_id}_workspace/` alongside `trace_{format}_{ts}_{session_id}.json` in `api_logs/`.

### DataQualityRunner Flow (quality_run.py)

The quality runner orchestrates a 3-phase data inspection pipeline:

1. **Phase 1 — Schema Analysis**: Agent reads `InputManifest.json`, samples files using `ReadData`, identifies data format families; produces `Schema.md` and `Schema.json`
2. **Phase 2 — Quality Assessment**: Agent scores six dimensions (0–5 scale) across all input files:
   - `completeness` — missing fields, null rates
   - `consistency` — format/type uniformity across records
   - `executability_verifiability` — whether outputs can be validated
   - `signal_to_noise` — ratio of useful content to boilerplate
   - `safety_and_compliance` — PII, harmful content, license issues
   - `task_utility` — fitness for the intended downstream task
   Produces `QualityReport.json` and `QualityReport.md`; every score must cite concrete evidence.
3. **Phase 3 — Gate Decision**: Agent issues a final verdict (`ACCEPT` / `REVIEW` / `REJECT`) with rationale; produces `GateDecision.md`

Default profile: `datacheck` (Bash, Glob, Grep, LS, Read, Edit, Write, ReadData).
Inputs default to `./sample/` when no paths are given.
Trace files and workspace folders follow the same naming convention as `CodingTaskRunner`.

### Configuration (.env)

| Variable | Default | Notes |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama default |
| `LLM_API_KEY` | `local` | Use `local` for local LLMs |
| `LLM_MODEL` | `llama3.2` | Model name |
| `LLM_STREAM` | `true` | Enable streaming |
| `LLM_MAX_TOOL_ITERATIONS` | `10` | Max tool calls per user turn |
| `LLM_TOOL_PROFILE` | `auto` | Global profile: `auto`, `claude`, `gemini`, `gpt`, `qwen`, `datacheck`, `default`, `readonly`, `minimal` |
| `LLM_CODING_PROFILE` | `claude` | Per-runner override for `CodingTaskRunner` |
| `LLM_QUALITY_PROFILE` | `datacheck` | Per-runner override for `DataQualityRunner` |
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
- `task_workspace/` — per-task coding workspace folders
- `quality_workspace/` — per-run data quality workspace folders
- `.agent_todos.json` — todo list used by TodoRead/TodoWrite tools

### Dependencies (requirements.txt)

- `openai` — OpenAI SDK for API client
- `pydantic` — Config model
- `python-dotenv` — .env loading
- `rich` — Terminal UI (Console, Live, Panel, Table, Markdown, Syntax)
- `prompt-toolkit` — Input with history and auto-suggest
- `httpx` — HTTP transport (used via openai SDK, also used by WebFetchTool)
- `pyte` — Terminal emulator (used by cli/terminal.py)
