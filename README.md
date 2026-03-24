# OpenCode Agent

A multi-provider AI agent CLI framework written in Python. Provides a unified interface for running AI agents with different LLM backends (Claude, Gemini, GPT, Qwen, local models via Ollama) through any OpenAI-compatible API.

## Architecture

```
data_agent_1.0/
├── run.py                      # Interactive REPL entry point
├── task_run.py                 # Automated coding task runner CLI
├── quality_run.py              # Data quality workflow CLI
├── agent/
│   ├── agent.py                # Main Agent class: turn loop, streaming, tool dispatch
│   ├── agent_factory.py        # AgentFactory: builds configured Agent per task type
│   ├── runner_registry.py      # RunnerRegistry: maps task types → AgentFactory configs
│   ├── task_runner.py          # CodingTaskRunner: 8-phase coding pipeline
│   ├── data_quality_runner.py  # DataQualityRunner: 3-phase data inspection pipeline
│   ├── client.py               # LLM API client (OpenAI-compatible)
│   ├── config.py               # Configuration from .env
│   ├── compression.py          # Context compression service
│   ├── session.py              # Session persistence
│   ├── telemetry.py            # Token / metrics tracking
│   ├── logger.py               # Pluggable trace formats
│   ├── retry.py                # Exponential backoff with jitter
│   ├── sandbox.py              # SandboxedRegistry: constrains file ops to workspace
│   └── tools/
│       ├── base.py             # Tool ABC + ToolRegistry (auto JSON-schema)
│       ├── profiles.py         # 10 named tool profiles + auto-detection
│       ├── data.py             # ReadDataTool: json/jsonl/json_gz/jsonl_gz
│       ├── claude.py           # Claude Code style tools
│       ├── gemini.py           # Gemini CLI style tools
│       ├── qwen.py             # Qwen Coder style tools
│       └── files.py, shell.py, web.py, ...
└── cli/
    └── main.py                 # Rich-based terminal UI
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
| `datacheck` | `DataQualityRunner`       | Data inspection: Bash, Glob, Grep, LS, Read, Edit, Write, ReadData |
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

### ReadDataTool — Context-Safe Data Inspection

`ReadDataTool` reads structured data files and returns a bounded preview that is safe to insert into an LLM context window:

- **Supported formats**: `json`, `jsonl`, `json_gz`, `jsonl_gz`
- **JSONL variants**: handles both `{json}` and `uuid\t{json}` line formats
- **Field-level truncation**: long string values are replaced with `"[truncated: N chars]"` before JSON serialisation — the agent always sees valid JSON with all keys intact, never a broken string cut mid-character
- **Hard caps**: `max_records=5` records, `max_chars=8000` total output
- **Nested structures**: truncation is applied recursively through dicts and lists

```
# Broken raw-string approach (old):
--- record 1 ---
{"body": "The quick brown fox jumps over the lazy dog The quick brow... [record truncated]

# Field-level truncation (current):
--- record 1 ---
{"id": 1, "title": "My Doc", "body": "[truncated: 18,432 chars]", "label": "positive"}
```

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
| `LLM_TOOL_PROFILE` | Tool profile (`auto`, `claude`, `datacheck`, etc.) | `auto` |
| `LLM_CONTEXT_LIMIT` | Token limit for context window | `200000` |
| `LLM_MAX_TOOL_ITERATIONS` | Max tool calls per turn | `10` |
| `LLM_STREAM` | Enable streaming responses | `true` |
| `LLM_COMPRESSION_THRESHOLD` | Fraction of context before compression | `0.5` |
| `LLM_COMPRESSION_PRESERVE_FRACTION` | Fraction of recent history to keep | `0.3` |
| `LLM_RETRY_MAX_ATTEMPTS` | Max retry attempts on API failure | `5` |

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

### Data Quality Workflow

```bash
python quality_run.py                           # default: inspects ./sample/
python quality_run.py data/sample.json          # single file
python quality_run.py data_dir/ --focus "Prioritize safety and trajectory usefulness"
python quality_run.py --model claude-opus-4-6 data/
```

The quality runner runs a 3-phase pipeline: schema analysis → quality assessment (6 dimensions, 0–5 scale) → gate decision (ACCEPT / REVIEW / REJECT). Outputs: `Schema.md`, `Schema.json`, `QualityReport.json`, `QualityReport.md`, `GateDecision.md`.

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
