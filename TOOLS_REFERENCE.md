# Tools Reference

Complete reference for the tools this agent can use, modelled after the
[Claude Code tools reference](https://code.claude.com/docs/en/tools-reference).

Tool names below are the exact strings used in tool profiles (`agent/tools/profiles.py`),
permission rules, and hook matchers. The **Status** column shows the current
implementation state for the **claude** profile (`agent/tools/claude.py`).

| Status legend | Meaning |
| :------------ | :------ |
| ✅ Done        | Implemented and tested in `agent/tools/claude.py` |
| 🔨 Planned    | On the roadmap; not yet implemented |
| ➖ N/A        | Requires infrastructure we intentionally omit (e.g. MCP, worktrees) |

---

## Tool table

| Tool | Description | Permission Required | Status |
| :--- | :---------- | :------------------ | :----- |
| `Agent` | Spawns a subagent with its own context window to handle a task | No | 🔨 Planned |
| `AskUserQuestion` | Asks multiple-choice questions to gather requirements or clarify ambiguity | No | 🔨 Planned |
| `Bash` | Executes shell commands in your environment. See [Bash tool behavior](#bash-tool-behavior) | Yes | ✅ Done |
| `CronCreate` | Schedules a recurring or one-shot prompt within the current session | No | 🔨 Planned |
| `CronDelete` | Cancels a scheduled task by ID | No | 🔨 Planned |
| `CronList` | Lists all scheduled tasks in the session | No | 🔨 Planned |
| `Edit` | Makes targeted edits to specific files | Yes | ✅ Done |
| `EnterPlanMode` | Switches to plan mode to design an approach before coding | No | 🔨 Planned |
| `EnterWorktree` | Creates an isolated git worktree and switches into it | No | ➖ N/A |
| `ExitPlanMode` | Presents a plan for approval and exits plan mode | Yes | ✅ Done |
| `ExitWorktree` | Exits a worktree session and returns to the original directory | No | ➖ N/A |
| `Glob` | Finds files based on pattern matching | No | ✅ Done |
| `Grep` | Searches for patterns in file contents | No | ✅ Done |
| `ListMcpResourcesTool` | Lists resources exposed by connected MCP servers | No | ➖ N/A |
| `LSP` | Code intelligence via language servers (type errors, jump-to-definition, find references, etc.) | No | 🔨 Planned |
| `NotebookEdit` | Modifies Jupyter notebook cells | Yes | ✅ Done |
| `Read` | Reads the contents of files | No | ✅ Done |
| `ReadMcpResourceTool` | Reads a specific MCP resource by URI | No | ➖ N/A |
| `Skill` | Executes a skill within the main conversation | Yes | 🔨 Planned |
| `TaskCreate` | Creates a new task in the task list | No | 🔨 Planned |
| `TaskGet` | Retrieves full details for a specific task | No | 🔨 Planned |
| `TaskList` | Lists all tasks with their current status | No | 🔨 Planned |
| `TaskOutput` | Retrieves output from a background task | No | 🔨 Planned |
| `TaskStop` | Kills a running background task by ID | No | 🔨 Planned |
| `TaskUpdate` | Updates task status, dependencies, details, or deletes tasks | No | 🔨 Planned |
| `TodoWrite` | Manages the session task checklist | No | ✅ Done |
| `ToolSearch` | Searches for and loads deferred tools | No | ➖ N/A |
| `WebFetch` | Fetches content from a specified URL | Yes | ✅ Done |
| `WebSearch` | Performs web searches | Yes | ✅ Done |
| `Write` | Creates or overwrites files | Yes | ✅ Done |

---

## Extra tools (not in Claude Code reference)

These tools exist in our codebase but have no direct equivalent in the Claude Code
reference. They are kept because they are useful or required by other tool profiles.

| Tool | Description | Profile | Notes |
| :--- | :---------- | :------ | :---- |
| `MultiEdit` | Applies multiple find-and-replace edits to a single file atomically | claude | Useful shortcut; not a separate tool in the reference |
| `NotebookRead` | Reads Jupyter notebook cells and outputs | claude | Reference only documents `NotebookEdit` |
| `TodoRead` | Reads the current session task checklist | claude | Reference only documents `TodoWrite` |
| `LS` | Lists files and directories with sizes | claude | Reference uses `Bash` for directory listing |

---

## Bash tool behavior

The Bash tool runs each command in a fresh subprocess with the following persistence
behaviour:

- **Working directory** persists across commands within a session.
- **Environment variables** do not persist. An `export` in one command is not
  available in the next command.

Activate your virtualenv before starting the agent. To make environment variables
persist, source them explicitly in each command or add them to the system prompt.

---

## Implementation notes

### Done (✅ 12 tools)

`Bash`, `Edit`, `ExitPlanMode`, `Glob`, `Grep`, `NotebookEdit`, `Read`,
`TodoWrite`, `WebFetch`, `WebSearch`, `Write`, `MultiEdit`*

\* `MultiEdit` is a bonus tool not in the reference.

### Planned (🔨 12 tools)

| Tool | Priority | Notes |
| :--- | :------- | :---- |
| `AskUserQuestion` | High | Needed for interactive clarification flows |
| `EnterPlanMode` | High | Counterpart to the already-implemented `ExitPlanMode` |
| `LSP` | Medium | Requires language server process management |
| `Agent` | Medium | Subagent spawning via recursive `Agent` instantiation |
| `TaskCreate` | Medium | Replace current generic `Task` tool with full task CRUD |
| `TaskGet` | Medium | — |
| `TaskList` | Medium | — |
| `TaskUpdate` | Medium | — |
| `TaskStop` | Medium | — |
| `TaskOutput` | Medium | — |
| `Skill` | Low | Skill loading and execution |
| `CronCreate` | Low | In-session scheduling |
| `CronDelete` | Low | — |
| `CronList` | Low | — |

### Not applicable (➖ 4 tools)

`EnterWorktree`, `ExitWorktree`, `ListMcpResourcesTool`, `ReadMcpResourceTool` —
these require git worktree isolation or an MCP server bus, neither of which is
part of this project's scope.

---

## See also

- `agent/tools/claude.py` — Claude profile tool implementations
- `agent/tools/profiles.py` — tool profile definitions and auto-detection
- `agent/tools/base.py` — `Tool` base class and `ToolRegistry`
- `CLAUDE.md` — project architecture overview
