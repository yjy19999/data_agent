from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env from the project root (one level up from agent/)
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path, override=True)


class Config(BaseModel):
    base_url: str = Field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    )
    api_key: str = Field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "local")
    )
    model: str = Field(
        default_factory=lambda: os.getenv("LLM_MODEL", "llama3.2")
    )
    system_prompt: str = ""
    max_tool_iterations: int = Field(
        default_factory=lambda: int(os.getenv("LLM_MAX_TOOL_ITERATIONS", "10"))
    )
    stream: bool = Field(
        default_factory=lambda: os.getenv("LLM_STREAM", "true").lower() == "true"
    )
    # Tool profile: explicit name or "auto" to detect from model name
    tool_profile: str = Field(
        default_factory=lambda: os.getenv("LLM_TOOL_PROFILE", "auto")
    )
    # Compression settings
    # Token limit of the model's context window (e.g. 200000 for Claude, 1048576 for Gemini)
    context_limit: int = Field(
        default_factory=lambda: int(os.getenv("LLM_CONTEXT_LIMIT", "200000"))
    )
    # Compress when history exceeds this fraction of context_limit (0.0–1.0)
    compression_threshold: float = Field(
        default_factory=lambda: float(os.getenv("LLM_COMPRESSION_THRESHOLD", "0.5"))
    )
    # Fraction of recent history to keep verbatim after compression (0.0–1.0)
    compression_preserve_fraction: float = Field(
        default_factory=lambda: float(os.getenv("LLM_COMPRESSION_PRESERVE_FRACTION", "0.3"))
    )
    # Token budget for tool results in the preserved (recent) history
    compression_tool_budget_tokens: int = Field(
        default_factory=lambda: int(os.getenv("LLM_COMPRESSION_TOOL_BUDGET_TOKENS", "50000"))
    )
    # Tool output size limits
    # Max characters returned by a single read_file call (~33k tokens at 3 chars/token)
    read_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("LLM_READ_MAX_CHARS", "100000"))
    )
    # Max characters returned by a single read_many_files call across all files
    read_many_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("LLM_READ_MANY_MAX_CHARS", "200000"))
    )
    # Log format: openhands, swe-agent, both, none
    log_format: str = Field(
        default_factory=lambda: os.getenv("LLM_LOG_FORMAT", "openhands")
    )
    # Retry settings
    retry_max_attempts: int = Field(
        default_factory=lambda: int(os.getenv("LLM_RETRY_MAX_ATTEMPTS", "5"))
    )
    retry_initial_delay_ms: int = Field(
        default_factory=lambda: int(os.getenv("LLM_RETRY_INITIAL_DELAY_MS", "1000"))
    )
    retry_max_delay_ms: int = Field(
        default_factory=lambda: int(os.getenv("LLM_RETRY_MAX_DELAY_MS", "30000"))
    )
    # Multi-agent settings
    # Maximum number of concurrently running sub-agents
    agent_max_threads: int = Field(
        default_factory=lambda: int(os.getenv("LLM_AGENT_MAX_THREADS", "4"))
    )
    # Maximum spawn depth for nested agent hierarchies
    agent_max_depth: int = Field(
        default_factory=lambda: int(os.getenv("LLM_AGENT_MAX_DEPTH", "3"))
    )


def build_system_prompt(tool_names: list[str]) -> str:
    """Build a system prompt that accurately lists the available tools.

    This is called at agent init time so the prompt always matches
    the tools actually registered for the current model / profile.
    """
    names_str = ", ".join(tool_names)
    return (
        "You are a helpful AI agent running in a terminal. "
        "You have access to tools for reading/writing files, running shell commands, "
        "and searching the filesystem. Use them to help the user accomplish their goals. "
        "Be concise and direct.\n\n"
        "IMPORTANT: Call exactly ONE tool per function call. "
        f"Available tools are: {names_str}. "
        "Never combine or concatenate tool names. Each tool call must use one of "
        "the exact names listed above.\n\n"
        "When making function calls using tools that accept array or object parameters "
        "ensure those are structured using JSON. For example:\n"
        '{"color": "orange", "options": {"option_key_1": true, "option_key_2": "value"}}\n\n'
        "If you intend to call multiple tools and there are no dependencies between "
        "the calls, make all of the independent calls in the same response, otherwise "
        "you MUST wait for previous calls to finish first to determine the dependent "
        "values (do NOT use placeholders or guess missing parameters).\n\n"
        "Answer the user's request using at most one relevant tool, if they are available. "
        "Check that the all required parameters for each tool call is provided or can "
        "reasonably be inferred from context. IF there are no relevant tools or there are "
        "missing values for required parameters, ask the user to supply these values; "
        "otherwise proceed with the tool calls. If the user provides a specific value for "
        "a parameter (for example provided in quotes), make sure to use that value EXACTLY. "
        "DO NOT make up values for or ask about optional parameters."
    )
