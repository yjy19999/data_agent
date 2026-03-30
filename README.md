# OpenCode Agent

A multi-provider AI agent CLI framework written in Python. Provides a unified interface for running AI agents with different LLM backends (Claude, Gemini, GPT, Qwen, local models via Ollama) through any OpenAI-compatible API.

## Architecture

```
data_agent_1.0/
├── run.py                          # Interactive REPL entry point
├── task_run.py                     # Automated coding task runner CLI
├── quality_run.py                  # Data quality workflow CLI (sampled)
├── quality_detail_run.py           # Data quality workflow CLI (full block coverage)
├── agent_cli.py                    # Pipeline-compatible CLI (llm-agent run interface)
├── agent/
│   ├── agent.py                    # Main Agent class: turn loop, streaming, tool dispatch
│   ├── agent_factory.py            # AgentFactory: builds configured Agent per task type
│   ├── runner_registry.py          # RunnerRegistry: maps task types → AgentFactory configs
│   ├── task_runner.py              # CodingTaskRunner: 8-phase coding pipeline
│   ├── data_quality_runner.py      # DataQualityRunner: 3-phase sampled pipeline
│   ├── data_quality_detail_runner.py # DataQualityDetailRunner: full block coverage
│   ├── data_inspector.py           # Data inspection utilities (detect_data_kind, etc.)
│   ├── progress.py                 # ProgressPrinter: shared Rich progress base class
│   ├── memory_log.py               # MemoryLog: compression audit records
│   ├── multi_agent.py              # AgentManager: background sub-agent management
│   ├── client.py                   # LLM API client (OpenAI-compatible)
│   ├── config.py                   # Configuration from .env
│   ├── compression.py              # Context compression service
│   ├── session.py                  # Session persistence
│   ├── telemetry.py                # Token / metrics tracking
│   ├── logger.py                   # Pluggable trace formats
│   ├── retry.py                    # Exponential backoff with jitter
│   ├── sandbox.py                  # SandboxedRegistry: constrains file ops to workspace
│   └── tools/
│       ├── base.py                 # Tool ABC + ToolRegistry (auto JSON-schema)
│       ├── profiles.py             # 10 named tool profiles + auto-detection
│       ├── data.py                 # ReadFormat, ReadData, ReadBlockMemory,
│       │                           #   ReadBlockSummary, WriteScore tools
│       ├── claude.py               # Claude Code style tools
│       ├── gemini.py               # Gemini CLI style tools
│       ├── qwen.py                 # Qwen Coder style tools
│       ├── codex.py                # Codex-rs style tools
│       ├── opencode.py             # OpenCode style tools
│       ├── multi_agents.py         # Multi-agent tools (spawn, send, wait, close, resume)
│       └── files.py, shell.py, web.py, ...
└── cli/
    └── main.py                     # Rich-based terminal UI
```

## Key Features

### Tool Profiles

Different toolsets matching popular AI CLIs and task types:

| Profile     | Default for               | Description |
|-------------|---------------------------|-------------|
| `claude`    | `claude-*` models         | Claude Code style (Bash, Read, Edit, Write, web search, etc.) |
| `gemini`    | `gemini-*` models         | Gemini CLI style (replace, read_file, grep_search, etc.) |
| `qwen`      | `qwen-*` models           | Qwen Coder style with LSP support |
| `gpt`       | `gpt-*`, `o1-*`, `o3-*`, `o4-*` | Conservative OpenAI style |
| `opencode`  | `opencode-*` models       | OpenCode style (read, write, glob, bash, codesearch, etc.) |
| `codex`     | `codex-*` models          | Codex-rs style with multi-agent and patch tools |
| `datacheck` | `DataQualityRunner`, `DataQualityDetailRunner` | Data inspection: Bash, Glob, Grep, LS, Read, Edit, Write, ReadFormat, ReadData, ReadBlockMemory, ReadBlockSummary, WriteScore |
| `default`   | all other models          | All built-in tools |
| `readonly`  | safe exploration          | Read-only tools (no shell, no writes) |
| `minimal`   | lightweight tasks         | Shell + read_file only |

### AgentFactory + RunnerRegistry

Every runner type registers a default `(profile, system_prompt)` pair in a central `RunnerRegistry`. An `AgentFactory` built from that entry handles workspace setup, sandboxing, and session/log wiring — keeping runner code free of tool-configuration logic.

Profile resolution order (highest wins):
1. Explicit `agent_factory=` kwarg passed to the runner
2. `LLM_TOOL_PROFILE` env var (when not `"auto"`)
3. Profile registered for that task type in the registry

```python
from agent.runner_registry import default_registry
from agent.agent_factory import AgentFactory
from agent.config import Config

# Use the registered default for "coding"
factory = default_registry.make_factory("coding", Config())

# Or override the profile for one run
factory = default_registry.make_factory("quality", Config(), profile="readonly")
```

### Data Tools — Context-Safe Inspection Suite

Five tools are bundled in the `datacheck` profile for structured data inspection:

| Tool | Purpose |
|------|---------|
| `ReadFormatTool` | File format metadata (kind, size, record count, sample keys) without loading full content |
| `ReadDataTool` | Bounded data preview with field-level truncation (see below) |
| `ReadBlockMemoryTool` | Stream a file in fixed-size blocks with memory context injected between blocks |
| `ReadBlockSummaryTool` | Stream a file in fixed-size blocks with a running summary context |
| `WriteScoreTool` | Write per-record or per-file quality scores; upserts by line number (no duplicates) |

**ReadDataTool** returns structurally-valid JSON with all keys intact, regardless of value length:

```
# Raw-string truncation (broken — keys disappear):
--- record 1 ---
{"body": "The quick brown fox jumps over the lazy dog The quick brow... [truncated]

# Field-level truncation (current — all keys visible):
--- record 1 ---
{"id": 1, "title": "My Doc", "body": "[truncated: 18,432 chars]", "label": "positive"}
```

Supported formats: `json`, `jsonl`, `json_gz`, `jsonl_gz`. JSONL handles both `{json}` and `uuid\t{json}` line formats. Hard caps: `max_records=5`, `max_chars=8000`. Truncation is applied recursively through nested dicts and lists.

**WriteScoreTool** uses a line-number-indexed upsert strategy: it reads the existing output JSONL file keyed by `_trace_line_num`, overwrites the entry for the current line, and rewrites the file sorted by line number. Calling `WriteScore` twice for the same line overwrites rather than appends — the output always has exactly one record per scored line.

### Agent Modes

- **Normal mode**: `agent.run(user_input)` — direct execution with full tool access
- **Plan-then-execute**:
  1. `agent.generate_plan()` — explore and produce a plan
  2. User approves the plan
  3. `agent.execute()` — execute the approved steps

### Session Management

- Save and restore conversations
- Resume previous sessions with full context
- Session files stored in `.gemini/sessions/`

### Context Compression

Automatically compresses conversation history when approaching token limits:
- Three-phase: truncate large tool outputs → summarise old history → self-correct
- Configurable threshold (default: 50% of context limit)
- Preserves recent messages verbatim
- **MemoryLog** (`agent/memory_log.py`) — optionally audits each compression event to `memory_logs/`, recording original/new token counts, reduction percentage, and the resulting `<state_snapshot>`

### Multi-Agent Support

`AgentManager` (`agent/multi_agent.py`) manages a pool of background sub-agents running in threads. Five matching tools (`agent/tools/multi_agents.py`) let the LLM orchestrate parallel work:

| Tool | Action |
|------|--------|
| `spawn_agent` | Launch a named sub-agent with a task |
| `send_input` | Send a follow-up message to a running agent |
| `wait_for_agents` | Block until agents finish and collect results |
| `close_agent` | Signal an agent to stop |
| `resume_agent` | Spawn an agent that resumes a saved session |

### Auto Profile Detection

Infers the best tool profile from the model name:

| Model Name Pattern | Profile |
|-------------------|---------|
| `claude-*` | `claude` |
| `gemini-*` | `gemini` |
| `opencode-*` | `opencode` |
| `codex-*` | `codex` |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | `gpt` |
| `qwen-*` | `qwen` |
| others | `default` |

## Configuration

Configuration is loaded from a `.env` file in the project root:

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `LLM_BASE_URL` | API endpoint | `http://localhost:11434/v1` |
| `LLM_API_KEY` | API key | `local` |
| `LLM_MODEL` | Model name | `llama3.2` |
| `LLM_TOOL_PROFILE` | Global tool profile (`auto`, `claude`, `datacheck`, etc.) | `auto` |
| `LLM_CODING_PROFILE` | Per-runner override for `CodingTaskRunner` | `claude` |
| `LLM_QUALITY_PROFILE` | Per-runner override for `DataQualityRunner` / `DataQualityDetailRunner` | `datacheck` |
| `LLM_CONTEXT_LIMIT` | Token limit for context window | `200000` |
| `LLM_MAX_TOOL_ITERATIONS` | Max tool calls per turn | `10` |
| `LLM_STREAM` | Enable streaming responses | `true` |
| `LLM_COMPRESSION_THRESHOLD` | Fraction of context before compression | `0.5` |
| `LLM_COMPRESSION_PRESERVE_FRACTION` | Fraction of recent history to keep verbatim | `0.3` |
| `LLM_COMPRESSION_TOOL_BUDGET_TOKENS` | Max tokens of tool results in preserved history | `50000` |
| `LLM_LOG_FORMAT` | Trace format: `openhands`, `swe-agent`, `mini-swe-agent`, `all`, `none` | `openhands` |
| `LLM_READ_MAX_CHARS` | Max chars per single read_file call | `100000` |
| `LLM_RETRY_MAX_ATTEMPTS` | Max retry attempts on API failure | `5` |
| `LLM_RETRY_INITIAL_DELAY_MS` | Starting retry delay | `1000` |
| `LLM_RETRY_MAX_DELAY_MS` | Max retry delay | `30000` |

## Usage

### Interactive REPL

```bash
python run.py
```

### Automated Coding Task

```bash
python task_run.py "Build a stack class"
python task_run.py --quiet --max-iterations 3 "Build X"
python task_run.py --model claude-opus-4-6 "Build Y"
```

The task runner runs an 8-phase pipeline: task intake → repo recon → plan → code → tests → test/fix loop → review → documentation. Outputs land in a sandboxed workspace folder alongside a trace file in `api_logs/`.

### Data Quality Workflow (Sampled)

```bash
python quality_run.py                           # default: inspects ./sample/
python quality_run.py data/sample.json          # single file
python quality_run.py data_dir/ --focus "Prioritize safety and trajectory usefulness"
python quality_run.py --model claude-opus-4-6 data/
```

The quality runner runs a 3-phase pipeline: schema analysis → quality assessment (6 dimensions, 0–5 scale) → gate decision (ACCEPT / REVIEW / REJECT). The agent uses tools to selectively sample data. Outputs: `Schema.md`, `Schema.json`, `QualityReport.json`, `QualityReport.md`, `GateDecision.md`.

### Data Quality Workflow (Full Block Coverage)

```bash
python quality_detail_run.py                    # default: inspects ./sample/
python quality_detail_run.py data/sample.json   # single file
python quality_detail_run.py data_dir/ --focus "Prioritize safety"
python quality_detail_run.py --model claude-opus-4-6 data/
python quality_detail_run.py --clean data/      # wipe output folder first
```

`DataQualityDetailRunner` guarantees every block of every data record is delivered directly to the agent — no sampling, no agent discretion. The runner pushes blocks as messages; the agent writes per-record observations. Additional outputs beyond the standard quality pipeline: `ObservationLog.jsonl`, `ObservationSummary.json`.

Output is written to a structured run folder:

```
output/{timestamp}_{session_id}/
├── files/       ← Schema.md, QualityReport.md, GateDecision.md, ObservationLog.jsonl, …
├── trajectory/  ← trace files (OpenHands, SWE-agent, mini-SWE-agent formats)
└── memory/      ← MemoryLog compression audit records
```

### Programmatic Usage

```python
from agent import Agent, Config

# Create agent with default config
agent = Agent()

# Run a single turn
for event in agent.run("list all python files"):
    if event.type == "text":
        print(event.data, end="")
    elif event.type == "tool_start":
        print(f"Calling: {event.data['name']}")
    elif event.type == "tool_end":
        print(f"Result: {event.data['result']}")
```

### Using AgentFactory Directly

```python
from agent.runner_registry import default_registry
from agent.config import Config
from agent.task_runner import CodingTaskRunner
from pathlib import Path

config = Config()

# Build a factory using the registered "coding" defaults
factory = default_registry.make_factory("coding", config)

runner = CodingTaskRunner(
    workspace=Path("my_workspace"),
    agent_factory=factory,
)
result = runner.run("Build a binary search tree")
```

### Plan-Then-Execute

```python
from agent import Agent

agent = Agent()

for event in agent.generate_plan("refactor all functions"):
    if event.type == "plan_ready":
        plan = event.data
        approved = ask_user(plan)
        break

if approved:
    for event in agent.execute():
        pass
```

### Session Management

```python
sessions = agent.list_sessions()
agent.resume_session(sessions[0]["session_id"])
agent.delete_session("abc123")
```

## Extending

### Adding a Custom Tool

```python
from agent.tools import Tool

class MyTool(Tool):
    name = "my_tool"
    description = "Does something useful"

    def run(self, path: str, count: int = 10) -> str:
        """
        Args:
            path: The file path to process.
            count: Number of items to process.
        """
        return "result"

from agent.tools import ToolRegistry
registry = ToolRegistry()
registry.register(MyTool())
```

### Adding a Custom Profile

```python
from agent.tools.profiles import ToolProfile, register_profile
from agent.tools.files import ReadFileTool
from agent.tools.shell import ShellTool

profile = ToolProfile(
    name="custom",
    description="My custom tool set",
    _factories=[MyTool, ReadFileTool, ShellTool],
)
register_profile(profile)
```

### Adding a New Task Type (RunnerRegistry)

```python
from agent.runner_registry import default_registry

default_registry.register(
    name="paper_to_code",
    profile="claude",
    system_prompt="You are an expert at translating ML papers into runnable Python code.",
    description="Convert academic papers to executable implementations",
)

# In your runner:
factory = default_registry.make_factory("paper_to_code", config)
```

## Requirements

- Python 3.10+
- OpenAI Python SDK (for API client)
- Rich (for terminal UI)
- python-dotenv (for configuration)
- pytest (required by the default `CodingTaskRunner` test command and the repo test suite)
