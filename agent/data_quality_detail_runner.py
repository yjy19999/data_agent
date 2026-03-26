from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .agent import Agent, TurnEvent
from .data_quality_runner import (
    DataQualityRunner,
    _QUALITY_INTRO_PROMPT,
    _QUALITY_AGGREGATE_PROMPT,
    _read_jsonl_lines,
)

_DETAIL_BLOCK_SIZE = 4_000  # chars per block delivered to the agent


def _split_blocks(content: str, block_size: int = _DETAIL_BLOCK_SIZE) -> list[str]:
    """Split a string into consecutive char-aligned blocks."""
    return [content[i : i + block_size] for i in range(0, len(content), block_size)]


def _read_json_raw(path: str | Path) -> str:
    """Read a json or json.gz file as a raw string."""
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return p.read_text(encoding="utf-8", errors="replace")


class DataQualityDetailRunner(DataQualityRunner):
    """
    Variant of DataQualityRunner that guarantees full block coverage.

    - JSONL/JSONL.GZ: every line is read; each line's content is split into
      blocks of _DETAIL_BLOCK_SIZE chars and every block is delivered to the agent.
    - JSON/JSON.GZ: the raw file content is split into blocks and every block
      is delivered to the agent.

    No content is ever omitted or left to the agent's discretion.
    """

    def _run_quality_phase(
        self, agent: "Agent", manifest: dict[str, Any]
    ) -> Iterator[TurnEvent]:
        jsonl_kinds = {"jsonl", "jsonl_gz"}
        json_kinds = {"json", "json_gz"}
        files = manifest.get("files", [])

        # --- intro turn ---
        yield from agent.run(_QUALITY_INTRO_PROMPT)

        # --- JSONL: every line, every block ---
        for entry in files:
            if entry.get("kind") not in jsonl_kinds:
                continue
            path = entry["path"]
            filename = Path(path).name
            lines = _read_jsonl_lines(path)
            total = len(lines)

            for lineno, line_content in enumerate(lines, start=1):
                blocks = _split_blocks(line_content, _DETAIL_BLOCK_SIZE)
                total_blocks = len(blocks)

                parts = [
                    f"JSONL file: {filename}  "
                    f"(line {lineno} of {total},  {total_blocks} block(s))\n"
                ]
                for block_idx, block_text in enumerate(blocks, start=1):
                    parts.append(
                        f"--- block {block_idx}/{total_blocks} ---\n{block_text}"
                    )

                prompt = (
                    "\n".join(parts)
                    + "\n\nNote quality observations for this record. "
                    "Do NOT write the final report yet."
                )
                yield from agent.run(prompt)

        # --- JSON: every block of the raw file ---
        for entry in files:
            if entry.get("kind") not in json_kinds:
                continue
            path = entry["path"]
            filename = Path(path).name
            raw = _read_json_raw(path)
            blocks = _split_blocks(raw, _DETAIL_BLOCK_SIZE)
            total_blocks = len(blocks)

            for block_idx, block_text in enumerate(blocks, start=1):
                prompt = (
                    f"JSON file: {filename}  "
                    f"(block {block_idx} of {total_blocks})\n\n"
                    f"{block_text}\n\n"
                    "Note quality observations for this block. "
                    "Do NOT write the final report yet."
                )
                yield from agent.run(prompt)

        # --- final aggregation ---
        yield from agent.run(_QUALITY_AGGREGATE_PROMPT)
