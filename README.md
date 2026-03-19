# OpenCode Agent

A multi-provider AI agent CLI framework written in Python. Provides a unified interface for running AI agents with different LLM backends (Claude, Gemini, GPT, Qwen, local models via Ollama).

## Architecture

```
cc_rewrite/
├── run.py              # Entry point
├── agent/              # Core agent logic
│   ├── agent.py        # Main Agent class with run loop
│   ├── client.py       # LLM API client wrapper
│   ├── config.py       # Configuration from .env
│   ├── compression.py  # Context compression service
│   ├── session.py      # Session persistence
│   ├── telemetry.py    # Token/metrics tracking
│   └── tools/          # Tool implementations
│       ├── base.py     # Tool base class + Registry
│       ├── profiles.py # Pre-defined tool profiles
│       ├── claude.py   # Claude Code style tools
│       ├── gemini.py   # Gemini CLI style tools
│       ├── qwen.py     # Qwen Coder style tools
│       └── files.py, shell.py, web.py...
└── cli/
    └── main.py         # Rich-based terminal UI
```

## Key Features

### Tool Profiles

Different toolsets matching popular AI CLIs:

| Profile   | Description |
|-----------|-------------|
| `claude`  | Claude Code style (bash, read, edit, write, web search, etc.) |
| `gemini`  | Gemini CLI style (replace, read_file, grep_search, etc.) |
| `qwen`    | Qwen Coder style |
| `gpt`     | Conservative OpenAI style |
| `default` | All built-in tools |
| `readonly`| Read-only tools (safe for exploration) |
| `minimal` | Shell + read_file only |

### Agent Modes

- **Normal mode**: `agent.run(user_input)` - direct execution with full tool access
- **Plan-then-execute**: 
  1. `agent.generate_plan()` - explore and produce a plan
  2. User approves the plan
  3. `agent.execute()` - execute the approved steps

### Session Management

- Save and restore conversations
- Resume previous sessions with full context
- Session files stored in `.gemini/sessions/`

### Context Compression

Automatically compresses conversation history when approaching token limits:
- Configurable threshold (default: 50% of context limit)
- Preserves recent messages verbatim
- Summarizes older content

### Auto Profile Detection

Infers the best tool profile from the model name:

| Model Name Pattern | Profile |
|-------------------|---------|
| `claude-*` | `claude` |
| `gemini-*` | `gemini` |
| `gpt-*`, `o1-*`, `o3-*` | `gpt` |
| `qwen-*` | `qwen` |
| others | `default` |

## Configuration

Configuration is loaded from a `.env` file in the project root:

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `LLM_BASE_URL` | API endpoint | `http://localhost:11434/v1` |
| `LLM_API_KEY` | API key | `local` |
| `LLM_MODEL` | Model name | `llama3.2` |
| `LLM_TOOL_PROFILE` | Tool profile (`auto`, `claude`, `gemini`, etc.) | `auto` |
| `LLM_CONTEXT_LIMIT` | Token limit for context window | `200000` |
| `LLM_MAX_TOOL_ITERATIONS` | Max tool calls per turn | `10` |
| `LLM_STREAM` | Enable streaming responses | `true` |
| `LLM_COMPRESSION_THRESHOLD` | Fraction of context before compression | `0.5` |
| `LLM_COMPRESSION_PRESERVE_FRACTION` | Fraction of recent history to keep | `0.3` |
| `LLM_RETRY_MAX_ATTEMPTS` | Max retry attempts on API failure | `5` |

## Usage

### Basic Usage

```bash
python run.py
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

### Plan-Then-Execute

```python
from agent import Agent

agent = Agent()

# Generate a plan
for event in agent.generate_plan("refactor all functions"):
    if event.type == "plan_ready":
        plan = event.data
        # Show plan to user, get approval
        approved = ask_user(plan)
        break

# Execute if approved
if approved:
    for event in agent.execute():
        # Handle events...
        pass
```

### Session Management

```python
# List saved sessions
sessions = agent.list_sessions()

# Resume a previous session
agent.resume_session(sessions[0]["session_id"])

# Delete a session
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
        # Implementation
        return "result"

# Register it
from agent.tools import ToolRegistry
registry = ToolRegistry()
registry.register(MyTool())
```

### Adding a Custom Profile

```python
from agent.tools.profiles import ToolProfile, register_profile

profile = ToolProfile(
    name="custom",
    description="My custom tool set",
    _factories=[MyTool, ReadFileTool, ShellTool],
)
register_profile(profile)
```

## Requirements

- Python 3.10+
- OpenAI Python SDK (for API client)
- Rich (for terminal UI)
- python-dotenv (for configuration)
- pytest (required by the default `CodingTaskRunner` test command and the repo test suite)
