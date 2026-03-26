from __future__ import annotations

import gzip
import json
import shutil
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table

from .agent import Agent, TurnEvent
from .agent_factory import AgentFactory
from .config import Config
from .data_inspector import build_input_manifest
from .progress import ProgressPrinter
from .runner_registry import runner_registry


_QUALITY_SYSTEM_PROMPT = """\
You are a data quality inspection agent.

Your job is to inspect datasets and write concise, evidence-backed reports.

IMPORTANT RULES:
1. Work only inside the current working directory.
2. Prefer reading `InputManifest.json` first. Only read raw inputs when the manifest is insufficient.
3. Two tools are available for reading .json, .jsonl, .json.gz, and .jsonl.gz files:
   - ReadFormat: returns a bounded preview with value truncation — use for quick schema/shape inspection.
   - ReadData: returns full content via block navigation, no truncation — use for deep content reading.
   Never use Read or Bash/cat on those file types.
4. Every score or conclusion must cite concrete evidence from the manifest or sampled content.
5. When you write JSON files, they must be valid JSON.
6. Focus on these six dimensions:
   - completeness
   - consistency
   - executability_or_verifiability
   - signal_to_noise
   - safety_and_compliance
   - task_utility
"""

_DEFAULT_FOCUS = """\
Inspect the staged dataset for data quality.

Quality targets:
1. Completeness
2. Consistency
3. Executability / Verifiability
4. Signal-to-noise
5. Safety / Compliance
6. Task Utility
"""

# ---------------------------------------------------------------------------
# Rich progress printer for the quality runner
# ---------------------------------------------------------------------------

class _QualityProgressPrinter(ProgressPrinter):
    """Quality-runner progress printer: adds manifest summary and gate decision panel."""

    PHASES = {
        "prepare_inputs": "Staging Inputs",
        "schema_analysis": "Phase 1 — Schema Analysis",
        "quality_gate":    "Phase 2 — Quality Assessment",
        "write_results":   "Phase 3 — Gate Decision",
    }

    def handle(self, event: TurnEvent) -> None:
        if event.type == "manifest_ready":
            self._console.print(f"  [dim]manifest:[/] {event.data}")
        else:
            super().handle(event)

    def _print_result(self, r: "DataQualityResult") -> None:
        self._console.print()
        table = Table(show_header=False, box=None, padding=(0, 2), expand=False)
        table.add_column("key", style="bold", no_wrap=True)
        table.add_column("value")

        if r.status == "accept":
            table.add_row("Decision", "[bold green]ACCEPT[/]")
            border = "green"
        elif r.status == "review":
            table.add_row("Decision", "[bold yellow]REVIEW[/]")
            border = "yellow"
        else:
            table.add_row("Decision", f"[bold red]{r.status.upper()}[/]")
            border = "red"

        if r.overall_summary:
            table.add_row("Summary", r.overall_summary[:120])
        if r.schema_files:
            table.add_row("Schema",  ", ".join(f"[cyan]{f}[/]" for f in r.schema_files))
        if r.report_files:
            table.add_row("Reports", ", ".join(f"[cyan]{f}[/]" for f in r.report_files))

        self._console.print(Panel(
            table,
            title="[bold]Result[/]",
            border_style=border,
            padding=(1, 2),
        ))


# ---------------------------------------------------------------------------

runner_registry.register(
    "quality",
    profile="datacheck",
    system_prompt=_QUALITY_SYSTEM_PROMPT,
    description="Data quality inspection and reporting",
)

_SCHEMA_PROMPT = """\
Read `InputManifest.json` first.

IMPORTANT — sampling rule:
- For any file ending in .json, .jsonl, .json.gz, or .jsonl.gz, use the ReadFormat tool
  to sample it. ReadFormat returns a bounded preview — ideal for quickly confirming schema
  shape and key fields without flooding the context window.
- Do NOT use Read or Bash/cat on those files.
- For all other file types (code, text, markdown, etc.) use the Read tool as normal.

Goal:
1. Confirm the detailed data format for each input file.
2. Decide whether each file is pure code, code sample, agent trajectory, QA, triple, webpage, or another family.
3. For JSON / JSONL inputs, infer the schema family and key fields from the ReadFormat sample.
4. Note any ambiguity, truncation risk, or places that require deeper inspection.

Write two files:

1. `Schema.md`
   - Overall dataset mix
   - Per-file format / schema family
   - Key fields and missing/uncertain fields
   - Risks or ambiguity

2. `Schema.json`
   Exact JSON shape:
   {
     "overall_mix": ["family"],
     "files": [
       {
         "path": "input/...",
         "kind": "json|jsonl|json.gz|jsonl.gz|code|webpage|text|...",
         "schema_family": "agent_trajectory|code_sample|webpage|qa_pair|triple|generic_json|document|...",
         "confidence": 0.0,
         "key_fields": ["field"],
         "missing_or_uncertain_fields": ["field"],
         "notes": ["note"]
       }
     ]
   }
"""

# Sent once at the start of Phase 2.  No reading instructions — the runner
# drives JSONL coverage in Python; the agent just notes quality observations.
_QUALITY_INTRO_PROMPT = """\
You are now in Phase 2: Quality Assessment.
Use `InputManifest.json`, `Schema.md`, and `Schema.json` for context.

You will receive JSONL file content line-by-line directly in the conversation.
For JSON / JSON.GZ files you will receive explicit instructions to read blocks via ReadData.
Do NOT use ReadFormat, Read, or Bash/cat on any .json/.jsonl/.json.gz/.jsonl.gz file.

As content arrives, assess each record against these six dimensions and note your findings.
Do NOT write the final report yet — just accumulate observations.

Dimensions:
- completeness
- consistency
- executability_or_verifiability
- signal_to_noise
- safety_and_compliance
- task_utility

Scoring scale (used in the final report):
  5 = strong  |  3 = mixed  |  1 = poor  |  0 = unusable / blocked
"""

# Sent after all content turns to produce the output files.
_QUALITY_AGGREGATE_PROMPT = """\
All content has now been delivered. Write the final quality report.

1. `QualityReport.json`  — exact JSON shape:
   {
     "overall_decision": "accept|review|reject",
     "overall_summary": "short summary",
     "dataset_findings": ["finding"],
     "recommended_actions": ["action"],
     "files": [
       {
         "path": "input/...",
         "scores": {
           "completeness": 0,
           "consistency": 0,
           "executability_or_verifiability": 0,
           "signal_to_noise": 0,
           "safety_and_compliance": 0,
           "task_utility": 0
         },
         "tags": ["tag"],
         "evidence": ["fact"],
         "blocking_issues": ["issue"],
         "usefulness": "high|medium|low"
       }
     ]
   }

2. `QualityReport.md`
   - Final gate decision
   - Top blockers
   - Best samples / worst samples
   - What to keep, review, or reject
"""

_JSONL_BATCH_SIZE = 10       # lines per agent turn
_JSONL_LINE_PREVIEW = 2_000  # chars shown inline; longer lines get a ReadData hint

_RESULTS_PROMPT = """\
Use `InputManifest.json`, `Schema.json`, and `QualityReport.json`.

Write `GateDecision.md` with:
- Final decision: ACCEPT / REVIEW / REJECT
- Short rationale
- Blocking issues
- Follow-up actions
- A compact checklist for downstream processing
"""


def _read_jsonl_lines(path: str | Path) -> list[str]:
    """Read every non-empty line from a jsonl or jsonl.gz file."""
    p = Path(path)
    open_fn = gzip.open if p.suffix == ".gz" else open
    lines: list[str] = []
    with open_fn(p, "rt", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            stripped = raw.strip()
            if stripped:
                lines.append(stripped)
    return lines


@dataclass
class DataQualityResult:
    inputs: list[str]
    status: str = ""
    staged_inputs: list[str] = field(default_factory=list)
    manifest_file: str = "InputManifest.json"
    schema_files: list[str] = field(default_factory=list)
    report_files: list[str] = field(default_factory=list)
    overall_summary: str = ""
    error: str = ""
    conversation_log: list[dict[str, Any]] = field(default_factory=list)


class DataQualityRunner:
    """Preprocess inputs and run a data-quality inspection workflow."""

    def __init__(
        self,
        workspace: str | Path,
        config: Config | None = None,
        *,
        session_id: str | None = None,
        logs_dir: str | Path | None = None,
        memory_log_dir: str | Path | None = None,
        agent_factory: AgentFactory | None = None,
        scan_bytes: int = 200_000,
        chunk_chars: int = 4_000,
        preview_chars: int = 800,
        max_preview_chunks: int = 8,
        max_json_records: int = 50,
    ):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.config = config or Config()
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.logs_dir = Path(logs_dir) if logs_dir else None
        self.memory_log_dir = Path(memory_log_dir) if memory_log_dir else None
        self.agent_factory = agent_factory
        self.scan_bytes = scan_bytes
        self.chunk_chars = chunk_chars
        self.preview_chars = preview_chars
        self.max_preview_chunks = max_preview_chunks
        self.max_json_records = max_json_records

    def _make_agent(self) -> Agent:
        """Create a sandboxed Agent, delegating to agent_factory if set."""
        if self.agent_factory is not None:
            return self.agent_factory.build(
                workspace=self.workspace,
                session_id=self.session_id,
                logs_dir=self.logs_dir,
                memory_log_dir=self.memory_log_dir,
            )

        # Default: look up profile + system prompt from the runner registry
        return runner_registry.make_factory("quality", self.config).build(
            workspace=self.workspace,
            session_id=self.session_id,
            logs_dir=self.logs_dir,
            memory_log_dir=self.memory_log_dir,
        )

    def run(
        self,
        inputs: Sequence[str | Path],
        *,
        focus: str = _DEFAULT_FOCUS,
        verbose: bool = True,
    ) -> DataQualityResult:
        printer = _QualityProgressPrinter() if verbose else None
        result = DataQualityResult(inputs=[str(Path(item)) for item in inputs])
        try:
            for event in self.run_stream(inputs, focus=focus):
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

    def _run_quality_phase(
        self, agent: "Agent", manifest: dict[str, Any]
    ) -> Iterator[TurnEvent]:
        """
        Phase 2 driver.

        JSONL/JSONL.GZ — Python reads every line and delivers content to the agent
        in batches of _JSONL_BATCH_SIZE.  Lines longer than _JSONL_LINE_PREVIEW chars
        are shown truncated with a hint to use ReadData for the full content.

        JSON/JSON.GZ — agent uses ReadData block navigation (no change).
        """
        jsonl_kinds = {"jsonl", "jsonl_gz"}
        json_kinds = {"json", "json_gz"}
        files = manifest.get("files", [])

        # --- intro turn (dimensions, scoring, no reading instructions) ---
        yield from agent.run(_QUALITY_INTRO_PROMPT)

        # --- JSONL: code-enforced line-by-line coverage ---
        for entry in files:
            if entry.get("kind") not in jsonl_kinds:
                continue
            path = entry["path"]
            filename = Path(path).name
            lines = _read_jsonl_lines(path)
            total = len(lines)

            for batch_start in range(0, total, _JSONL_BATCH_SIZE):
                batch = lines[batch_start : batch_start + _JSONL_BATCH_SIZE]
                batch_end = batch_start + len(batch)
                parts = [
                    f"JSONL file: {filename}  "
                    f"(lines {batch_start + 1}–{batch_end} of {total})\n"
                ]
                for i, line_content in enumerate(batch):
                    lineno = batch_start + i + 1
                    if len(line_content) > _JSONL_LINE_PREVIEW:
                        preview = line_content[:_JSONL_LINE_PREVIEW]
                        remaining = len(line_content) - _JSONL_LINE_PREVIEW
                        hint = (
                            f" … [{remaining:,} more chars — "
                            f"use ReadData line={lineno} block=N for full content]"
                        )
                    else:
                        preview = line_content
                        hint = ""
                    parts.append(f"Line {lineno}: {preview}{hint}")

                batch_prompt = (
                    "\n".join(parts)
                    + "\n\nNote quality observations for each line above. "
                    "Do NOT write the final report yet."
                )
                yield from agent.run(batch_prompt)

        # --- JSON: agent uses ReadData blocks ---
        for entry in files:
            if entry.get("kind") not in json_kinds:
                continue
            path = entry["path"]
            filename = Path(path).name
            json_prompt = (
                f"Now assess JSON file: {filename}\n"
                "Use ReadData (no args) to get the block index, then read: "
                "block 1, the last block, and at least 3 middle blocks "
                "(read all blocks if there are 5 or fewer). "
                "Note quality observations. Do NOT write the final report yet."
            )
            yield from agent.run(json_prompt)

        # --- final aggregation ---
        yield from agent.run(_QUALITY_AGGREGATE_PROMPT)

    def run_stream(
        self,
        inputs: Sequence[str | Path],
        *,
        focus: str = _DEFAULT_FOCUS,
    ) -> Iterator[TurnEvent]:
        agent = self._make_agent()
        result = DataQualityResult(inputs=[str(Path(item)) for item in inputs])

        yield TurnEvent(type="phase", data="prepare_inputs")
        staged_inputs = self._stage_inputs(inputs)
        result.staged_inputs = [str(path.relative_to(self.workspace)) for path in staged_inputs]
        manifest = build_input_manifest(
            staged_inputs,
            scan_bytes=self.scan_bytes,
            chunk_chars=self.chunk_chars,
            preview_chars=self.preview_chars,
            max_preview_chunks=self.max_preview_chunks,
            max_json_records=self.max_json_records,
        )
        self._write_json(self.workspace / result.manifest_file, manifest)
        yield TurnEvent(type="manifest_ready", data=manifest["summary"])

        yield TurnEvent(type="phase", data="schema_analysis")
        for event in agent.run(f"{focus.strip()}\n\n{_SCHEMA_PROMPT}"):
            yield event
        result.schema_files = self._existing_files("Schema.md", "Schema.json")

        yield TurnEvent(type="phase", data="quality_gate")
        yield from self._run_quality_phase(agent, manifest)
        result.report_files = self._existing_files("QualityReport.json", "QualityReport.md")

        yield TurnEvent(type="phase", data="write_results")
        for event in agent.run(_RESULTS_PROMPT):
            yield event
        result.report_files = self._existing_files(
            "QualityReport.json",
            "QualityReport.md",
            "GateDecision.md",
        )

        report = self._load_quality_report()
        if report:
            result.status = str(report.get("overall_decision", "review"))
            result.overall_summary = str(report.get("overall_summary", ""))
        else:
            result.status = "error"
            result.error = "QualityReport.json missing or invalid"

        yield TurnEvent(type="result", data=result)

    def _stage_inputs(self, inputs: Sequence[str | Path]) -> list[Path]:
        staged_root = self.workspace / "input"
        if staged_root.exists():
            shutil.rmtree(staged_root)
        staged_root.mkdir(parents=True, exist_ok=True)

        staged_files: list[Path] = []
        for item in inputs:
            source = Path(item).expanduser().resolve()
            if not source.exists():
                raise FileNotFoundError(f"input path not found: {source}")
            destination = self._unique_destination(staged_root, source.name)
            if source.is_dir():
                shutil.copytree(source, destination)
                staged_files.extend(sorted(path for path in destination.rglob("*") if path.is_file()))
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                staged_files.append(destination)
        return staged_files

    def _unique_destination(self, root: Path, name: str) -> Path:
        candidate = root / name
        stem = Path(name).stem
        suffix = Path(name).suffix
        counter = 2
        while candidate.exists():
            candidate = root / f"{stem}_{counter}{suffix}"
            counter += 1
        return candidate

    def _load_quality_report(self) -> dict[str, Any] | None:
        report_path = self.workspace / "QualityReport.json"
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _existing_files(self, *names: str) -> list[str]:
        return [name for name in names if (self.workspace / name).exists()]

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
