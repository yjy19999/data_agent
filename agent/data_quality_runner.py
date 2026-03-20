from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import Agent, TurnEvent
from .config import Config
from .data_inspector import build_input_manifest
from .sandbox import SandboxedRegistry
from .tools.profiles import get_profile, infer_profile


_QUALITY_SYSTEM_PROMPT = """\
You are a data quality inspection agent.

Your job is to inspect datasets and write concise, evidence-backed reports.

IMPORTANT RULES:
1. Work only inside the current working directory.
2. Prefer reading `InputManifest.json` first. Only read raw inputs when the manifest is insufficient.
3. Every score or conclusion must cite concrete evidence from the manifest or sampled content.
4. When you write JSON files, they must be valid JSON.
5. Focus on these six dimensions:
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

_SCHEMA_PROMPT = """\
Read `InputManifest.json` first.

Goal:
1. Confirm the detailed data format for each input file.
2. Decide whether each file is pure code, code sample, agent trajectory, QA, triple, webpage, or another family.
3. For JSON / JSONL inputs, infer the schema family and key fields.
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
         "kind": "json|jsonl|code|webpage|text|...",
         "schema_family": "agent_trajectory|code_sample|webpage|qa_pair|triple|generic_json|document|...",
         "confidence": 0.0,
         "key_fields": ["field"],
         "missing_or_uncertain_fields": ["field"],
         "notes": ["note"]
       }
     ]
   }
"""

_QUALITY_PROMPT = """\
Use `InputManifest.json`, `Schema.md`, and `Schema.json`.

Assess each file and the dataset overall against these six dimensions:
- completeness
- consistency
- executability_or_verifiability
- signal_to_noise
- safety_and_compliance
- task_utility

Scoring:
- 5 = strong
- 3 = mixed
- 1 = poor
- 0 = unusable / blocked

Write two files:

1. `QualityReport.json`
   Exact JSON shape:
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

_RESULTS_PROMPT = """\
Use `InputManifest.json`, `Schema.json`, and `QualityReport.json`.

Write `GateDecision.md` with:
- Final decision: ACCEPT / REVIEW / REJECT
- Short rationale
- Blocking issues
- Follow-up actions
- A compact checklist for downstream processing
"""


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
        self.scan_bytes = scan_bytes
        self.chunk_chars = chunk_chars
        self.preview_chars = preview_chars
        self.max_preview_chunks = max_preview_chunks
        self.max_json_records = max_json_records

    def _make_agent(self) -> Agent:
        profile_name = self.config.tool_profile
        if profile_name == "auto":
            profile_name = infer_profile(self.config.model)

        base_registry = get_profile(profile_name).build_registry()
        sandbox = SandboxedRegistry(self.workspace)
        for schema in base_registry.schemas():
            tool = base_registry.get(schema["function"]["name"])
            if tool:
                sandbox.register(tool)

        return Agent(
            config=Config(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                model=self.config.model,
                stream=self.config.stream,
                max_tool_iterations=self.config.max_tool_iterations,
                tool_profile=self.config.tool_profile,
                context_limit=self.config.context_limit,
                compression_threshold=self.config.compression_threshold,
                system_prompt=_QUALITY_SYSTEM_PROMPT,
            ),
            registry=sandbox,
            session_id=self.session_id,
        )

    def run(
        self,
        inputs: Sequence[str | Path],
        *,
        focus: str = _DEFAULT_FOCUS,
    ) -> DataQualityResult:
        result = DataQualityResult(inputs=[str(Path(item)) for item in inputs])
        try:
            for event in self.run_stream(inputs, focus=focus):
                if event.type == "result":
                    return event.data
        except Exception as exc:
            result.status = "error"
            result.error = str(exc)
        return result

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
        for event in agent.run(_QUALITY_PROMPT):
            yield event
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
