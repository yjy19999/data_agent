from __future__ import annotations

import gzip
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from .agent import Agent, TurnEvent
from .data_quality_runner import (
    DataQualityRunner,
    DataQualityResult,
    _QualityProgressPrinter,
    _read_jsonl_lines,
)

_DETAIL_BLOCK_SIZE = 40_000      # chars per block delivered to the agent
_CONSOLIDATION_INTERVAL = 50     # records between consolidation turns

_OBSERVATION_LOG = "ObservationLog.jsonl"
_OBSERVATION_SUMMARY = "ObservationSummary.json"

_DETAIL_QUALITY_INTRO_PROMPT = """\
You are now in Phase 2: Quality Assessment.
Use `InputManifest.json`, `Schema.md`, and `Schema.json` for context.

ALL data content will be delivered to you block by block as messages.
Do NOT call ReadData, ReadFormat, Read, or any tool to read data files — the data
comes to you directly. Your response will be automatically saved — you do not
need to call any write tool.

## How data is delivered

- **JSONL files**: each line is one independent data record. A large record may
  be split across multiple blocks. You will see `--- NEW RECORD ---` markers
  at record boundaries.
- **JSON files**: the entire file is split into consecutive blocks. You will see
  `--- NEW FILE ---` markers at file boundaries.

## What to write for each block

- **Non-final block of a multi-block record**: note your observations for this
  block only (fields seen, quality issues, anomalies). Do NOT score yet.
- **Final (or only) block of a record**: write observations for this block, then
  give a complete assessment of the **entire record** across all six dimensions.
- **JSON file blocks**: each block is assessed independently across all six
  dimensions.

## Assessment format (for final/only blocks and JSON blocks)

- completeness: ...
- consistency: ...
- executability_or_verifiability: ...
- signal_to_noise: ...
- safety_and_compliance: ...
- task_utility: ...
Overall: brief summary sentence.

Scoring scale (used in the final report):
  5 = strong  |  3 = mixed  |  1 = poor  |  0 = unusable / blocked

Dimensions:
- completeness              — missing fields, null rates
- consistency               — format/type uniformity across records
- executability_or_verifiability — can outputs be validated?
- signal_to_noise           — ratio of useful content to boilerplate
- safety_and_compliance     — PII, harmful content, licence issues
- task_utility              — fitness for intended downstream task

Do NOT produce the final QualityReport yet — that comes after all data is delivered.
"""

_CONSOLIDATION_PROMPT = """\
You have now assessed blocks 1–{n}.

Write `{summary}` (overwrite if it exists) with a structured JSON summary of your
findings so far. Use this exact schema:

{{
  "as_of_block": {n},
  "dimensions": {{
    "completeness":                  {{"score_estimate": 0-5, "notes": "...", "evidence_blocks": [1, 3, ...]}},
    "consistency":                   {{"score_estimate": 0-5, "notes": "...", "evidence_blocks": [...]}},
    "executability_or_verifiability":{{"score_estimate": 0-5, "notes": "...", "evidence_blocks": [...]}},
    "signal_to_noise":               {{"score_estimate": 0-5, "notes": "...", "evidence_blocks": [...]}},
    "safety_and_compliance":         {{"score_estimate": 0-5, "notes": "...", "evidence_blocks": [...]}},
    "task_utility":                  {{"score_estimate": 0-5, "notes": "...", "evidence_blocks": [...]}}
  }}
}}

This file is your durable reference. Be specific — cite block numbers in evidence_blocks.
Do NOT write the final QualityReport yet.
"""

_DETAIL_AGGREGATE_PROMPT = """\
All data blocks have been delivered.

Review your full observation record using these tools:
- Read `BlockObservations.md`  — your per-block assessments written during inspection
- ReadBlockMemory("{log}")     — index of all blocks captured by the system
- ReadBlockMemory("{log}", start_block=N, end_block=M) — full text for a range
- ReadBlockSummary("{summary}") — consolidated per-dimension summary (if written)

Using that evidence, produce the final output files:
- `QualityReport.json`   — scores (0–5) for each of the six dimensions with evidence
- `QualityReport.md`     — human-readable report with per-dimension commentary
- `GateDecision.md`      — final verdict: ACCEPT / REVIEW / REJECT with rationale

Every score must cite specific ## block N labels from BlockObservations.md.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _append_observation(
    log_path: Path,
    block_num: int,
    source: str,
    observation: str,
) -> None:
    """Append one block's agent response as a JSONL entry to ObservationLog.jsonl."""
    record = {"block": block_num, "source": source, "observation": observation.strip()}
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Progress printer
# ---------------------------------------------------------------------------

class _DetailProgressPrinter(_QualityProgressPrinter):
    """Extends the quality printer to show block-send and consolidation events."""

    def handle(self, event: TurnEvent) -> None:
        if event.type == "progress":
            self._console.print(f"  [dim cyan]{event.data}[/]")
        else:
            super().handle(event)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class DataQualityDetailRunner(DataQualityRunner):
    """
    Variant of DataQualityRunner that guarantees full block coverage and
    maintains durable per-block observation memory.

    - JSONL/JSONL.GZ: every line split into blocks; each block delivered as
      a separate agent turn; agent response appended to ObservationLog.md.
    - JSON/JSON.GZ: raw file split into blocks; same per-block delivery.
    - Every `consolidation_interval` records Python injects a consolidation
      turn so the agent writes a structured ObservationSummary.md.
    - Final aggregation reads from ObservationLog.md + ObservationSummary.md
      rather than relying on conversation history.
    """

    def __init__(self, *args: Any, consolidation_interval: int = _CONSOLIDATION_INTERVAL, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.consolidation_interval = consolidation_interval

    def run(
        self,
        inputs: Sequence[str | Path],
        *,
        focus: str = "",
        verbose: bool = True,
    ) -> DataQualityResult:
        from .data_quality_runner import _DEFAULT_FOCUS
        printer = _DetailProgressPrinter() if verbose else None
        result = DataQualityResult(inputs=[str(Path(item)) for item in inputs])
        try:
            for event in self.run_stream(inputs, focus=focus or _DEFAULT_FOCUS):
                if printer:
                    printer.handle(event)
                if event.type == "result":
                    return event.data
        except Exception as exc:
            if printer:
                printer.error(str(exc))
            result.status = "error"
            result.error = str(exc)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_and_log(
        self,
        agent: Agent,
        prompt: str,
        log_path: Path,
        block_num: int,
        source: str,
    ) -> Iterator[TurnEvent]:
        """Run one agent turn, yield events, and write the response to both log files."""
        text_parts: list[str] = []
        for event in agent.run(prompt):
            if event.type == "text":
                text_parts.append(event.data)
            yield event
        observation = "".join(text_parts).strip()

        # Python writes ObservationLog.jsonl — no tool call required from agent
        _append_observation(log_path, block_num, source, observation)

        # Python also writes BlockObservations.md — agent just needs to reply with text
        obs_md = log_path.parent / "BlockObservations.md"
        with obs_md.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## block {block_num}  [{source}]\n{observation}\n")

    def _consolidate(
        self,
        agent: Agent,
        block_count: int,
    ) -> Iterator[TurnEvent]:
        prompt = _CONSOLIDATION_PROMPT.format(
            n=block_count,
            summary=_OBSERVATION_SUMMARY,
        )
        yield TurnEvent(
            type="progress",
            data=f"consolidating observations after block {block_count} → {_OBSERVATION_SUMMARY}",
        )
        yield from agent.run(prompt)

    # ------------------------------------------------------------------
    # Phase override
    # ------------------------------------------------------------------

    def _run_quality_phase(
        self, agent: Agent, manifest: dict[str, Any]
    ) -> Iterator[TurnEvent]:
        jsonl_kinds = {"jsonl", "jsonl_gz"}
        json_kinds  = {"json",  "json_gz"}
        files = manifest.get("files", [])

        log_path = self.workspace / _OBSERVATION_LOG
        obs_md   = self.workspace / "BlockObservations.md"
        # Start fresh each run
        log_path.write_text("", encoding="utf-8")
        obs_md.write_text("# Block Observations\n", encoding="utf-8")

        # --- intro turn ---
        yield from agent.run(_DETAIL_QUALITY_INTRO_PROMPT)

        block_count = 0  # tracks delivered blocks across all files for consolidation

        prev_file: str | None = None   # track file transitions

        # --- JSONL: every line, every block ---
        for entry in files:
            if entry.get("kind") not in jsonl_kinds:
                continue
            path     = entry["path"]
            filename = Path(path).name
            lines    = _read_jsonl_lines(path)
            total    = len(lines)

            # ── file boundary ──
            if filename != prev_file:
                yield TurnEvent(type="progress", data=f"[{filename}] starting file")
                yield from agent.run(
                    f"--- NEW FILE ---\n"
                    f"Now inspecting JSONL file: `{filename}` ({total} records).\n"
                    f"Each record is an independent data item. "
                    f"Blocks from different records are NOT related to each other."
                )
                prev_file = filename

            for lineno, line_content in enumerate(lines, start=1):
                blocks       = _split_blocks(line_content, _DETAIL_BLOCK_SIZE)
                total_blocks = len(blocks)

                for block_idx, block_text in enumerate(blocks, start=1):
                    is_last = block_idx == total_blocks
                    block_source = f"{filename} record {lineno}/{total} block {block_idx}/{total_blocks}"

                    yield TurnEvent(
                        type="progress",
                        data=f"[{filename}] record {lineno}/{total}  "
                             f"block {block_idx}/{total_blocks}",
                    )

                    # ── record boundary on first block ──
                    record_boundary = ""
                    if block_idx == 1:
                        record_boundary = (
                            f"--- NEW RECORD (record {lineno}/{total} in `{filename}`) ---\n"
                            f"This is a separate, independent record from any previous one.\n\n"
                        )

                    header = (
                        f"{record_boundary}"
                        f"JSONL file: `{filename}` | record {lineno}/{total} | "
                        f"block {block_idx}/{total_blocks}\n\n"
                        f"{block_text}\n\n"
                    )

                    if is_last:
                        if total_blocks == 1:
                            prompt = (
                                header
                                + f"This is the only block of record {lineno} "
                                f"(global block {block_count + 1}). "
                                "Write your observations and give a complete "
                                "assessment of this record across all six dimensions. "
                                "Do NOT write the final QualityReport yet."
                            )
                        else:
                            prompt = (
                                header
                                + f"This is the final block of record {lineno} "
                                f"(global block {block_count + 1}). "
                                "Write your observations for this block, then give a complete "
                                "assessment of this entire record (all blocks combined) "
                                "across all six dimensions. "
                                "Do NOT write the final QualityReport yet."
                            )
                    else:
                        prompt = (
                            header
                            + f"This is block {block_idx}/{total_blocks} of record {lineno} "
                            f"(global block {block_count + 1}) — more blocks of this same "
                            f"record follow. Write your observations for this block. "
                            "Do not give the final record assessment yet."
                        )

                    yield from self._run_and_log(agent, prompt, log_path, block_count + 1, block_source)
                    block_count += 1
                    if block_count % self.consolidation_interval == 0:
                        yield from self._consolidate(agent, block_count)

        # --- JSON: every block of the raw file ---
        for entry in files:
            if entry.get("kind") not in json_kinds:
                continue
            path         = entry["path"]
            filename     = Path(path).name
            raw          = _read_json_raw(path)
            blocks       = _split_blocks(raw, _DETAIL_BLOCK_SIZE)
            total_blocks = len(blocks)

            # ── file boundary ──
            if filename != prev_file:
                yield TurnEvent(type="progress", data=f"[{filename}] starting file")
                yield from agent.run(
                    f"--- NEW FILE ---\n"
                    f"Now inspecting JSON file: `{filename}` "
                    f"({total_blocks} block{'s' if total_blocks != 1 else ''}).\n"
                    f"All blocks belong to this single file — they are consecutive "
                    f"portions of the same JSON document."
                )
                prev_file = filename

            for file_block_idx, block_text in enumerate(blocks, start=1):
                yield TurnEvent(
                    type="progress",
                    data=f"[{filename}] block {file_block_idx}/{total_blocks}",
                )

                source = f"{filename} block {file_block_idx}/{total_blocks}"
                prompt = (
                    f"JSON file: `{filename}` | block {file_block_idx}/{total_blocks}\n\n"
                    f"{block_text}\n\n"
                    f"This is block {file_block_idx}/{total_blocks} of file `{filename}` "
                    f"(global block {block_count + 1}). "
                    f"Assess this block across all six dimensions. "
                    "Do NOT write the final QualityReport yet."
                )
                yield from self._run_and_log(agent, prompt, log_path, block_count + 1, source)

                block_count += 1
                if block_count % self.consolidation_interval == 0:
                    yield from self._consolidate(agent, block_count)

        # --- final aggregation ---
        yield from agent.run(
            _DETAIL_AGGREGATE_PROMPT.format(
                log=_OBSERVATION_LOG,
                summary=_OBSERVATION_SUMMARY,
            )
        )
