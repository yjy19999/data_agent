# Rust Mapping

## Scope

This document maps the Python implementation in this repository against the
Rust reference implementation under `../codex/codex-rs`, then summarizes the
main differences and concrete improvement opportunities.

## High-Level Mapping

### Agent Runtime

Python:

- `agent/agent.py` holds the main runtime loop.
- `AgentState` stores message history in memory.
- The agent runs tool calls in a synchronous turn loop.

Rust reference:

- `codex-rs/core/src/thread_manager.rs` creates and tracks threads.
- `codex-rs/core/src/codex_thread.rs` represents one live conversation thread.
- The runtime is event-driven and centered around `thread_id` plus streamed protocol events.

Mapping conclusion:

- Python `Agent` is closest to a simplified single-thread version of Rust's
  `ThreadManager + CodexThread`.
- Python currently behaves like one mutable conversation object.
- Rust treats each session as an explicit thread with lifecycle, identity, and config snapshotting.

### Tool System

Python:

- `agent/tools/base.py` defines `Tool` and `ToolRegistry`.
- Tool schemas are mostly inferred from Python signatures and docstrings.
- `agent/tools/profiles.py` assembles tool profiles manually.

Rust reference:

- `codex-rs/mcp-server/src/codex_tool_config.rs` defines explicit typed tool-call parameters and schema.
- `codex-rs/mcp-server/src/codex_tool_runner.rs` runs sessions and emits structured events.

Mapping conclusion:

- Python is class-based and dynamic.
- Rust is schema-first and protocol-first.
- Python is easier to extend quickly.
- Rust is safer and more precise for external integrations.

### Transport And API Layer

Python:

- `agent/client.py` is a thin OpenAI-compatible chat wrapper.
- `agent/api.py` provides sync and async convenience wrappers around `Agent`.

Rust reference:

- `codex-rs/mcp-server/src/message_processor.rs` parses tool-call requests and replies.
- The MCP server spawns asynchronous tasks for long-running sessions.
- Events are streamed back in a structured way.

Mapping conclusion:

- Python transport is compact and direct.
- Rust transport is more layered and better suited for multi-client protocol handling.

### Sandbox And Execution Policy

Python:

- `agent/sandbox.py` constrains path resolution and some shell execution.

Rust reference:

- sandbox and approval policy are first-class runtime concepts
- configuration includes approval policy and sandbox mode
- approval requests are represented as events and handled explicitly

Mapping conclusion:

- Python has a basic sandbox wrapper.
- Rust has a real execution policy model.

## Main Differences

### 1. Thread Model

Rust has first-class thread lifecycle management:

- thread creation
- thread lookup by id
- event streaming per thread
- config snapshots per thread

Python has:

- one in-memory message list per agent instance
- session save/resume support
- no equivalent thread manager abstraction

Impact:

- Python is simpler, but less scalable for concurrent sessions, richer resumability,
  and protocol-facing integrations.

### 2. Approval And Sandbox Design

Rust has:

- explicit approval policies
- explicit sandbox modes
- approval request / response flow
- structured handling for execution and patch approval

Python has:

- a lightweight sandbox wrapper
- no approval policy abstraction
- no evented approval workflow

Impact:

- Python is missing an important safety and control layer that the Rust design treats as core.

### 3. Event Model

Rust uses structured protocol events for:

- session configured
- approval requests
- plan deltas
- errors
- turn completion

Python uses `TurnEvent`, which is useful but narrower:

- `text`
- `tool_start`
- `tool_end`
- `plan_ready`
- `error`
- `done`
- `usage`
- `compressed`

Impact:

- Python has the beginning of an event model, but not the same depth of structured runtime state.

### 4. Type Safety And Tool Contracts

Rust:

- strong typed tool input structs
- explicit schema generation
- cleaner validation boundaries

Python:

- auto-inferred schemas from signatures
- string-based tool outputs
- many failures represented as `"[error] ..."`

Impact:

- Python is easier to prototype in, but weaker for robust orchestration and machine-readable handling.

### 5. Separation Of Concerns

Rust separates:

- thread management
- model management
- skills management
- file watching
- MCP server
- TUI
- approval logic

Python concentrates more logic in:

- `agent/agent.py`
- `agent/client.py`
- `agent/tools/*`

Impact:

- Python is easier to read initially, but key responsibilities are coupled more tightly.

## Concrete Improvement Points

### 1. Fix Sandbox Coverage

This is the most immediate correctness issue.

Observed problem:

- `agent/sandbox.py` only treats `shell` and `Bash` as shell tools.
- Gemini and Qwen profiles use `run_shell_command`.
- Path rewriting only covers a limited set of parameter names and misses names such as:
  - `dir_path`
  - `absolute_path`

Why this matters:

- sandbox guarantees are incomplete across profiles
- some tools may bypass intended workspace restrictions

Recommended change:

- centralize tool capability metadata
- explicitly mark which tools execute commands
- explicitly mark which parameters are paths and whether they are file, dir, or optional

### 2. Introduce A Session/Thread Abstraction

Recommended direction:

- split the current `Agent` into:
  - a session/thread object
  - a manager responsible for creating, listing, and resuming sessions

Why this matters:

- aligns better with the Rust design
- simplifies multi-session support
- makes background execution and session continuation cleaner

### 3. Replace Stringly-Typed Tool Results

Current pattern:

- tool success and failure are mostly returned as strings
- callers inspect text like `"[error] ..."`

Recommended direction:

- define a structured result object, for example:
  - `ok`
  - `content`
  - `error`
  - `metadata`

Why this matters:

- improves control flow
- makes logging and UI rendering more reliable
- creates a better base for approvals, retries, and richer telemetry

### 4. Add Approval Policy To Config And Runtime

Recommended direction:

- extend configuration with approval policy and sandbox mode
- emit approval request events before sensitive execution
- support explicit approve / deny paths

Why this matters:

- this is one of the strongest ideas in the Rust design
- it turns execution safety from an implicit convention into explicit runtime behavior

### 5. Tighten Tool Schemas

Current pattern:

- schema generation is based mostly on Python signature reflection

Recommended direction:

- allow explicit schema definitions for more tools
- validate nested structures more strictly
- use typed parameter models where needed

Why this matters:

- reduces malformed tool calls
- makes profile compatibility more reliable
- helps when adding protocol-facing integrations later

### 6. Decompose The Core Runtime

Recommended direction:

- reduce the amount of orchestration concentrated in `agent/agent.py`
- pull out:
  - session lifecycle
  - tool execution orchestration
  - approval logic
  - event translation

Why this matters:

- improves maintainability
- makes testing easier
- creates clearer boundaries for future ports from the Rust reference

## Suggested Porting Order

If this repository adopts ideas from the Rust reference, the most practical order is:

1. Fix sandbox coverage and shell/path handling.
2. Add explicit execution policy and approval concepts.
3. Introduce structured tool results.
4. Split agent runtime into session/thread plus manager.
5. Expand the event model and reduce orchestration coupling.

## Final Conclusion

The Python implementation is a practical, compact approximation of the Rust
system, but it is materially simpler in four important areas:

- thread/session lifecycle
- approval and sandbox policy
- event richness
- type safety around tool contracts

The best immediate improvement is to harden the Python sandbox and align tool
execution rules across all profiles. The best medium-term improvement is to
move from a single mutable agent loop toward a thread/session-oriented design
closer to the Rust reference.
