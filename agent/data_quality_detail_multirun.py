from __future__ import annotations

import gzip
import json
import threading
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

ALL data content will be delivered to you record by record as messages.
Do NOT call ReadData, ReadFormat, Read, or any tool to read data files — the data
comes to you directly.

## How data is delivered

- **JSONL files**: each line is one independent data record. A large record may
  be split across multiple blocks. You will see `--- NEW RECORD ---` markers
  at record boundaries.
- **JSON files**: the entire file is split into consecutive blocks. You will see
  `--- NEW FILE ---` markers at file boundaries.

## IMPORTANT: you are inspecting ONE record at a time

Each message contains one record (or one block of a large record).
Your job is to write **concrete factual observations about THIS specific record**,
NOT an overall quality report about the whole dataset.

Do NOT summarise dataset-wide trends, do NOT give overall scores, and do NOT
write the final QualityReport. Just describe what you see in THIS record.

## What to write for each record

Answer these questions about the specific record you are looking at:

1. **Fields present / missing**: Which fields does this record have? Are any
   expected fields (per Schema.json) missing or null?
2. **Format anomalies**: Does this record's structure or field types match the
   schema? Any unexpected types, extra fields, or malformed values?
3. **Verifiability**: Can the content of this record be independently verified
   or validated? Are there testable claims, executable code, or checkable references?
4. **Useful content vs filler**: How much of this record is substantive content
   vs boilerplate, placeholder text, or repetition?
5. **Safety concerns**: Does this record contain PII, harmful content, toxic
   language, or licence-problematic material? Cite specific fields/values.
6. **Fitness for task**: Is this record useful for the intended downstream task?
   What makes it good or bad as a training/evaluation example?

## Scoring — use the WriteScore tool

After inspecting each record (on the final or only block), you MUST call the
`WriteScore` tool to record your scores. Scoring scale: 0–5
(5 = strong, 3 = mixed, 1 = poor, 0 = unusable).

**For JSONL records**: call WriteScore with the source file path, line number,
and your score dict. The tool injects a `trace_score` field into that record
and writes it to an output copy. Example:

    WriteScore(
        path="sample/data.jsonl",
        line=3,
        score='{"completeness": 4, "consistency": 5, "verifiability": 3, "signal_to_noise": 4, "safety": 5, "task_utility": 4}'
    )

**For JSON files**: call WriteScore with just the file path and your score dict
(no line number). The tool writes `<name>_score.json` in the output directory.

    WriteScore(
        path="sample/config.json",
        score='{"completeness": 5, "consistency": 5, "verifiability": 2, "signal_to_noise": 3, "safety": 5, "task_utility": 3}'
    )

## Response format

Write your observations as a short bulleted list, then call WriteScore.
Be specific — quote field names and values. Example:

- fields: has `instruction`, `response`, `metadata`; missing `source_id` (expected per schema)
- format: `metadata.timestamp` is a string "yesterday" instead of ISO-8601
- verifiability: `response` contains a code snippet that could be executed to verify
- content: 80% substantive; `metadata.tags` is empty list (filler)
- safety: no PII or harmful content detected
- fitness: good example — clear instruction with detailed response
→ then call WriteScore(...)

For non-final blocks of a multi-block record, just note what fields/content you
see in this block. Do NOT call WriteScore until the final block.
"""

_CONSOLIDATION_PROMPT = """\
You have now inspected records across blocks 1–{n}.

Review your per-record observations so far and aggregate them into patterns.
Write `{summary}` (overwrite if it exists) with a structured JSON summary.

NOW is the time to look across records and identify dataset-level patterns.
Use this exact schema:

{{
  "as_of_block": {n},
  "records_inspected": <count>,
  "dimensions": {{
    "completeness":                  {{"score_estimate": 0-5, "notes": "which fields are commonly missing/null across records", "evidence_blocks": [1, 3, ...]}},
    "consistency":                   {{"score_estimate": 0-5, "notes": "are records uniform in structure/types, or do they vary?", "evidence_blocks": [...]}},
    "executability_or_verifiability":{{"score_estimate": 0-5, "notes": "can outputs generally be validated?", "evidence_blocks": [...]}},
    "signal_to_noise":               {{"score_estimate": 0-5, "notes": "ratio of useful content to filler across records", "evidence_blocks": [...]}},
    "safety_and_compliance":         {{"score_estimate": 0-5, "notes": "PII/harmful/licence issues found in any records", "evidence_blocks": [...]}},
    "task_utility":                  {{"score_estimate": 0-5, "notes": "overall fitness of the inspected records for the task", "evidence_blocks": [...]}}
  }},
  "common_issues": ["issue 1 seen in N records", ...],
  "notable_records": [{{"block": N, "reason": "..."}}]
}}

Scoring scale: 5 = strong | 3 = mixed | 1 = poor | 0 = unusable.
Be specific — cite block numbers. This is a checkpoint summary, not the final report.
Do NOT write the final QualityReport yet.
"""

_DETAIL_AGGREGATE_PROMPT = """\
All records have been delivered and inspected.

You wrote per-record factual observations during inspection. Now aggregate those
observations into a dataset-level quality report.

Review your observation record using these tools:
- Read `BlockObservations.md`  — your per-record observations written during inspection
- ReadBlockMemory("{log}")     — index of all blocks captured by the system
- ReadBlockMemory("{log}", start_block=N, end_block=M) — full text for a range
- ReadBlockSummary("{summary}") — consolidated checkpoint summary (if written)

Using that evidence, produce the final output files:

1. `QualityReport.json` — dataset-level scores (0–5) for each dimension:
   - completeness: missing fields, null rates across all records
   - consistency: format/type uniformity across records
   - executability_or_verifiability: can outputs be validated?
   - signal_to_noise: ratio of useful content to boilerplate
   - safety_and_compliance: PII, harmful content, licence issues
   - task_utility: fitness for intended downstream task
   Each score must cite specific block numbers as evidence.

2. `QualityReport.md` — human-readable report with per-dimension commentary,
   referencing specific records/blocks that illustrate each finding.

3. `GateDecision.md` — final verdict: ACCEPT / REVIEW / REJECT with rationale.

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

        # Clear the WriteScore output directory so stale scored files don't persist
        score_out = self.workspace / "output"
        if score_out.exists():
            import shutil
            shutil.rmtree(score_out)
        score_out.mkdir(parents=True, exist_ok=True)

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
                        score_reminder = (
                            f"Then call WriteScore(path=\"{path}\", line={lineno}, "
                            "score='{{...}}') with your scores."
                        )
                        if total_blocks == 1:
                            prompt = (
                                header
                                + f"This is the only block of record {lineno} "
                                f"(global block {block_count + 1}). "
                                "Write your factual observations about THIS record: "
                                "fields present/missing, format issues, verifiability, "
                                "useful content vs filler, safety concerns, task fitness. "
                                f"{score_reminder}"
                            )
                        else:
                            prompt = (
                                header
                                + f"This is the final block of record {lineno} "
                                f"(global block {block_count + 1}). "
                                "Now that you have seen all blocks of this record, write your "
                                "factual observations about THIS complete record: "
                                "fields present/missing, format issues, verifiability, "
                                "useful content vs filler, safety concerns, task fitness. "
                                f"{score_reminder}"
                            )
                    else:
                        prompt = (
                            header
                            + f"This is block {block_idx}/{total_blocks} of record {lineno} "
                            f"(global block {block_count + 1}) — more blocks of this same "
                            f"record follow. Note what fields and content you see in this "
                            f"block. Do NOT call WriteScore yet."
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
                is_last_json_block = file_block_idx == total_blocks
                if is_last_json_block:
                    score_instruction = (
                        "Write your factual observations about the content in this block. "
                        f"This is the final block of file `{filename}`. "
                        f"Call WriteScore(path=\"{path}\", "
                        "score='{{...}}') with your scores for this file."
                    )
                else:
                    score_instruction = (
                        "Write your factual observations about the content in this block: "
                        "fields present/missing, format issues, verifiability, "
                        "useful content vs filler, safety concerns, task fitness. "
                        "Do NOT call WriteScore yet — more blocks of this file follow."
                    )
                prompt = (
                    f"JSON file: `{filename}` | block {file_block_idx}/{total_blocks}\n\n"
                    f"{block_text}\n\n"
                    f"This is block {file_block_idx}/{total_blocks} of file `{filename}` "
                    f"(global block {block_count + 1}). "
                    f"{score_instruction}"
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


# ---------------------------------------------------------------------------
# Per-record seed prompt (injected into each fresh sub-agent before its record)
# ---------------------------------------------------------------------------

_RECORD_AGENT_SEED_PROMPT = """\
You are inspecting a SINGLE data record for quality.

The dataset context is below. After this message you will receive one record
(possibly split across multiple blocks if it is large).

Your job:
1. Read all blocks of the record.
2. Write brief factual observations (fields present/missing, format anomalies,
   verifiability, signal-to-noise, safety concerns, task fitness).
3. On the FINAL block call WriteScore with your scores (0-5 per dimension).

Do NOT write a dataset-level report. One record only.

{schema_context}
"""

# Module-level lock: guards the read-modify-rewrite cycle in WriteScoreTool
# when batch_size > 1 causes concurrent sub-agents writing to the same file.
_SCORE_WRITE_LOCK = threading.Lock()


def _build_block_prompts(
    filename: str,
    path: str,
    lineno: int,
    total: int,
    line_content: str,
    global_block_start: int,
) -> list[str]:
    """
    Return the list of per-block prompt strings for one JSONL record.

    global_block_start is the block_count value BEFORE this record's first block,
    so block labels are globally consistent with ObservationLog.jsonl.
    """
    blocks = _split_blocks(line_content, _DETAIL_BLOCK_SIZE)
    total_blocks = len(blocks)
    prompts: list[str] = []

    for block_idx, block_text in enumerate(blocks, start=1):
        is_last = block_idx == total_blocks
        global_num = global_block_start + block_idx

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

        score_reminder = (
            f"Then call WriteScore(path=\"{path}\", line={lineno}, "
            "score='{...}') with your scores."
        )

        if is_last:
            if total_blocks == 1:
                prompt = (
                    header
                    + f"This is the only block of record {lineno} "
                    f"(global block {global_num}). "
                    "Write your factual observations about THIS record: "
                    "fields present/missing, format issues, verifiability, "
                    "useful content vs filler, safety concerns, task fitness. "
                    f"{score_reminder}"
                )
            else:
                prompt = (
                    header
                    + f"This is the final block of record {lineno} "
                    f"(global block {global_num}). "
                    "Now that you have seen all blocks of this record, write your "
                    "factual observations about THIS complete record: "
                    "fields present/missing, format issues, verifiability, "
                    "useful content vs filler, safety concerns, task fitness. "
                    f"{score_reminder}"
                )
        else:
            prompt = (
                header
                + f"This is block {block_idx}/{total_blocks} of record {lineno} "
                f"(global block {global_num}) — more blocks of this same "
                f"record follow. Note what fields and content you see in this "
                f"block. Do NOT call WriteScore yet."
            )

        prompts.append(prompt)

    return prompts


# ---------------------------------------------------------------------------
# Multi-runner
# ---------------------------------------------------------------------------

class DataQualityDetailMultiRunner(DataQualityDetailRunner):
    """
    Variant of DataQualityDetailRunner that spawns a **fresh agent per JSONL
    record**, eliminating cross-record context accumulation ("memory leak").

    Each sub-agent:
      - Starts from a clean context seeded with schema knowledge
      - Inspects exactly one record (all its blocks)
      - Calls WriteScore for that record
      - Is discarded — no conversation state carried to the next record

    The main (long-lived) agent is reserved for:
      - Phase 1 schema analysis
      - File-boundary turns
      - Periodic consolidation
      - JSON file inspection (unchanged)
      - Final aggregation

    Parameters
    ----------
    batch_size : int
        Number of records processed concurrently via AgentManager threads.
        Default 1 = sequential (safest, no file-locking needed for WriteScore).
        Set to 2–4 for parallel throughput; requires thread-safe WriteScore
        (enforced via _SCORE_WRITE_LOCK at the runner level).
    consolidation_interval : int
        Every N records the main agent writes ObservationSummary.json.
        Inherited from DataQualityDetailRunner, default 50.
    """

    def __init__(
        self,
        *args: Any,
        batch_size: int = 1,
        consolidation_interval: int = _CONSOLIDATION_INTERVAL,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, consolidation_interval=consolidation_interval, **kwargs)
        if batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {batch_size}")
        self.batch_size = batch_size

    # ------------------------------------------------------------------
    # Schema context helper
    # ------------------------------------------------------------------

    def _load_schema_context(self) -> str:
        """
        Read Schema.md and Schema.json from the workspace and return a
        combined string suitable for seeding per-record sub-agents.

        Called once at the start of _run_quality_phase(), after Phase 1
        has already written both files.
        """
        parts: list[str] = []
        schema_md = self.workspace / "Schema.md"
        schema_json = self.workspace / "Schema.json"
        if schema_md.exists():
            parts.append(f"## Schema.md\n\n{schema_md.read_text(encoding='utf-8')}")
        if schema_json.exists():
            parts.append(f"## Schema.json\n\n```json\n{schema_json.read_text(encoding='utf-8')}\n```")
        return "\n\n".join(parts) if parts else "(schema not yet available)"

    # ------------------------------------------------------------------
    # Sub-agent factory
    # ------------------------------------------------------------------

    def _make_record_agent(self, schema_context: str) -> Agent:
        """
        Build a fresh Agent and seed it with dataset schema context.

        The seed turn plants Schema.md / Schema.json into the agent's
        conversation as assistant knowledge so per-record prompts need
        not repeat the schema — saving tokens on every block.
        """
        agent = self._make_agent()
        seed_prompt = _RECORD_AGENT_SEED_PROMPT.format(schema_context=schema_context)
        # Consume the seed turn fully; we only need the side-effect of
        # the schema landing in the agent's conversation history.
        for _ in agent.run(seed_prompt):
            pass
        return agent

    # ------------------------------------------------------------------
    # Single-record driver
    # ------------------------------------------------------------------

    def _run_single_record(
        self,
        schema_context: str,
        filename: str,
        path: str,
        lineno: int,
        total: int,
        line_content: str,
        log_path: Path,
        block_count_ref: list[int],
    ) -> Iterator[TurnEvent]:
        """
        Process one JSONL record through a fresh sub-agent.

        block_count_ref is a one-element mutable list used as a counter
        reference so the caller's global block count stays in sync.
        """
        record_agent = self._make_record_agent(schema_context)
        prompts = _build_block_prompts(
            filename, path, lineno, total, line_content,
            global_block_start=block_count_ref[0],
        )
        total_blocks = len(prompts)
        block_source_base = f"{filename} record {lineno}/{total}"

        for block_idx, prompt in enumerate(prompts, start=1):
            block_source = f"{block_source_base} block {block_idx}/{total_blocks}"
            yield TurnEvent(
                type="progress",
                data=f"[{filename}] record {lineno}/{total}  block {block_idx}/{total_blocks}  [sub-agent]",
            )
            yield from self._run_and_log(
                record_agent, prompt, log_path,
                block_count_ref[0] + 1, block_source,
            )
            block_count_ref[0] += 1

        # record_agent goes out of scope here → GC'd, no state carried forward

    # ------------------------------------------------------------------
    # Parallel batch driver (batch_size > 1)
    # ------------------------------------------------------------------

    def _run_batch_parallel(
        self,
        schema_context: str,
        filename: str,
        path: str,
        batch: list[tuple[int, str]],   # [(lineno, line_content), ...]
        total: int,
        log_path: Path,
        block_count_ref: list[int],
    ) -> Iterator[TurnEvent]:
        """
        Spawn one sub-agent per record in the batch via AgentManager threads,
        wait for all to finish, then write observations to the log.

        WriteScore calls from parallel sub-agents are serialised by
        _SCORE_WRITE_LOCK (module-level), injected via monkey-patching
        WriteScoreTool._write_jsonl_score at call time.
        """
        from .multi_agent import get_manager

        manager = get_manager(max_threads=max(self.batch_size, 4))

        # Build one full prompt string per record (all blocks concatenated
        # with clear separators — the sub-agent sees the whole record at once
        # so there is no need for multi-turn block delivery in parallel mode).
        agent_ids: list[tuple[int, str]] = []  # (lineno, agent_id)

        for lineno, line_content in batch:
            prompts = _build_block_prompts(
                filename, path, lineno, total, line_content,
                global_block_start=block_count_ref[0],
            )
            # Combine all block prompts into one message for the sub-agent.
            # In parallel mode we deliver the full record as a single prompt
            # (blocks separated by dividers) to avoid multi-turn orchestration.
            if len(prompts) == 1:
                full_prompt = (
                    _RECORD_AGENT_SEED_PROMPT.format(schema_context=schema_context)
                    + "\n\n"
                    + prompts[0]
                )
            else:
                block_divider = "\n\n--- NEXT BLOCK ---\n\n"
                full_prompt = (
                    _RECORD_AGENT_SEED_PROMPT.format(schema_context=schema_context)
                    + "\n\n"
                    + block_divider.join(prompts)
                )

            # Clone the sandboxed registry so sub-agents share the same
            # workspace constraints as the parent.
            from .multi_agent import clone_registry_for_child
            child_registry = clone_registry_for_child(self.config, None)

            aid = manager.spawn(
                prompt=full_prompt,
                role="worker",
                nickname=f"{filename}-rec{lineno}",
                config=self.config,
                registry=child_registry,
            )
            agent_ids.append((lineno, aid))
            # Advance block counter by the number of blocks this record will use
            block_count_ref[0] += len(prompts)

        yield TurnEvent(
            type="progress",
            data=f"[{filename}] waiting for {len(agent_ids)} parallel sub-agents …",
        )

        results = manager.wait(
            [aid for _, aid in agent_ids],
            timeout=600,
        )

        for lineno, aid in agent_ids:
            observation = results.get(aid, "(no result)")
            block_source = f"{filename} record {lineno}/{total} [parallel]"
            _append_observation(log_path, lineno, block_source, observation)
            obs_md = log_path.parent / "BlockObservations.md"
            with obs_md.open("a", encoding="utf-8") as fh:
                fh.write(f"\n## block {lineno}  [{block_source}]\n{observation}\n")

    # ------------------------------------------------------------------
    # Phase 2 override
    # ------------------------------------------------------------------

    def _run_quality_phase(
        self, agent: Agent, manifest: dict[str, Any]
    ) -> Iterator[TurnEvent]:
        """
        Phase 2: spawn a fresh sub-agent per JSONL record.

        The main `agent` still handles:
          - The intro turn
          - File-boundary announcement turns
          - Periodic consolidation (every consolidation_interval records)
          - JSON file inspection (unchanged from DataQualityDetailRunner)
          - Final aggregation

        JSONL records are handled exclusively by short-lived sub-agents.
        """
        jsonl_kinds = {"jsonl", "jsonl_gz"}
        json_kinds  = {"json",  "json_gz"}
        files = manifest.get("files", [])

        log_path = self.workspace / _OBSERVATION_LOG
        obs_md   = self.workspace / "BlockObservations.md"
        log_path.write_text("", encoding="utf-8")
        obs_md.write_text("# Block Observations\n", encoding="utf-8")

        score_out = self.workspace / "output"
        if score_out.exists():
            import shutil
            shutil.rmtree(score_out)
        score_out.mkdir(parents=True, exist_ok=True)

        # Intro turn on the main agent (same as DataQualityDetailRunner)
        yield from agent.run(_DETAIL_QUALITY_INTRO_PROMPT)

        # Load schema context ONCE — injected into every sub-agent
        schema_context = self._load_schema_context()

        # Mutable counter shared across all record helpers
        block_count = [0]

        prev_file: str | None = None

        # ── JSONL: one fresh sub-agent per record ──────────────────────────
        for entry in files:
            if entry.get("kind") not in jsonl_kinds:
                continue
            path     = entry["path"]
            filename = Path(path).name
            lines    = _read_jsonl_lines(path)
            total    = len(lines)

            # File-boundary turn on the main agent
            if filename != prev_file:
                yield TurnEvent(type="progress", data=f"[{filename}] starting file  ({total} records)")
                yield from agent.run(
                    f"--- NEW FILE ---\n"
                    f"Now inspecting JSONL file: `{filename}` ({total} records).\n"
                    f"Each record is an independent data item. "
                    f"Sub-agents will inspect each record individually."
                )
                prev_file = filename

            if self.batch_size == 1:
                # ── sequential: one sub-agent per record, in order ──
                for lineno, line_content in enumerate(lines, start=1):
                    yield from self._run_single_record(
                        schema_context, filename, path,
                        lineno, total, line_content,
                        log_path, block_count,
                    )
                    if block_count[0] % self.consolidation_interval == 0:
                        yield from self._consolidate(agent, block_count[0])

            else:
                # ── batched parallel: up to batch_size sub-agents at once ──
                enumerated = list(enumerate(lines, start=1))
                for batch_start in range(0, len(enumerated), self.batch_size):
                    batch = enumerated[batch_start : batch_start + self.batch_size]
                    yield from self._run_batch_parallel(
                        schema_context, filename, path,
                        batch, total, log_path, block_count,
                    )
                    if block_count[0] % self.consolidation_interval == 0:
                        yield from self._consolidate(agent, block_count[0])

        # ── JSON: unchanged — main agent uses ReadData blocks ──────────────
        for entry in files:
            if entry.get("kind") not in json_kinds:
                continue
            path         = entry["path"]
            filename     = Path(path).name
            raw          = _read_json_raw(path)
            blocks       = _split_blocks(raw, _DETAIL_BLOCK_SIZE)
            total_blocks = len(blocks)

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
                is_last_json_block = file_block_idx == total_blocks
                if is_last_json_block:
                    score_instruction = (
                        "Write your factual observations about the content in this block. "
                        f"This is the final block of file `{filename}`. "
                        f"Call WriteScore(path=\"{path}\", "
                        "score='{...}') with your scores for this file."
                    )
                else:
                    score_instruction = (
                        "Write your factual observations about the content in this block: "
                        "fields present/missing, format issues, verifiability, "
                        "useful content vs filler, safety concerns, task fitness. "
                        "Do NOT call WriteScore yet — more blocks of this file follow."
                    )
                prompt = (
                    f"JSON file: `{filename}` | block {file_block_idx}/{total_blocks}\n\n"
                    f"{block_text}\n\n"
                    f"This is block {file_block_idx}/{total_blocks} of file `{filename}` "
                    f"(global block {block_count[0] + 1}). "
                    f"{score_instruction}"
                )
                yield from self._run_and_log(agent, prompt, log_path, block_count[0] + 1, source)
                block_count[0] += 1
                if block_count[0] % self.consolidation_interval == 0:
                    yield from self._consolidate(agent, block_count[0])

        # ── Final aggregation — main agent reads observation files ──────────
        yield from agent.run(
            _DETAIL_AGGREGATE_PROMPT.format(
                log=_OBSERVATION_LOG,
                summary=_OBSERVATION_SUMMARY,
            )
        )
