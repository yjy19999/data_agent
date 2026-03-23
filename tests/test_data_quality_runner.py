from __future__ import annotations

import json
from pathlib import Path

from agent import Config, TurnEvent
from agent.data_quality_runner import DataQualityRunner


class _FakeAgent:
    def __init__(self, workspace: Path):
        self.workspace = workspace

    def run(self, prompt: str):
        if "GateDecision.md" in prompt:
            (self.workspace / "GateDecision.md").write_text("# REVIEW\n", encoding="utf-8")
        elif "QualityReport.json" in prompt:
            (self.workspace / "QualityReport.md").write_text("# Quality\n", encoding="utf-8")
            (self.workspace / "QualityReport.json").write_text(
                json.dumps(
                    {
                        "overall_decision": "review",
                        "overall_summary": "Needs manual review.",
                        "dataset_findings": ["small dataset"],
                        "recommended_actions": ["add more examples"],
                        "files": [
                            {
                                "path": "input/sample.json",
                                "scores": {
                                    "completeness": 3,
                                    "consistency": 4,
                                    "executability_or_verifiability": 2,
                                    "signal_to_noise": 4,
                                    "safety_and_compliance": 5,
                                    "task_utility": 3,
                                },
                                "tags": ["qa"],
                                "evidence": ["contains question and answer"],
                                "blocking_issues": [],
                                "usefulness": "medium",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        elif "Schema.json" in prompt:
            (self.workspace / "Schema.md").write_text("# Schema\n", encoding="utf-8")
            (self.workspace / "Schema.json").write_text(
                json.dumps(
                    {
                        "overall_mix": ["qa_pair"],
                        "files": [
                            {
                                "path": "input/sample.json",
                                "kind": "json",
                                "schema_family": "qa_pair",
                                "confidence": 0.8,
                                "key_fields": ["question", "answer"],
                                "missing_or_uncertain_fields": [],
                                "notes": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        yield TurnEvent(type="text", data="ok")
        yield TurnEvent(type="done")


def test_stage_inputs_copies_files_and_directories(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src_file = src_dir / "a.txt"
    src_file.write_text("hello", encoding="utf-8")

    runner = DataQualityRunner(workspace=tmp_path / "ws")
    staged = runner._stage_inputs([src_dir])

    assert staged
    assert all(path.exists() for path in staged)
    assert any(path.name == "a.txt" for path in staged)


def test_run_stream_emits_phases_and_result(tmp_path):
    src = tmp_path / "sample.json"
    src.write_text(json.dumps({"question": "q", "answer": "a"}), encoding="utf-8")

    runner = DataQualityRunner(
        workspace=tmp_path / "ws",
        config=Config(model="test", api_key="test", stream=False),
    )
    runner._make_agent = lambda: _FakeAgent(runner.workspace)

    events = list(runner.run_stream([src]))

    phase_names = [event.data for event in events if event.type == "phase"]
    assert phase_names == ["prepare_inputs", "schema_analysis", "quality_gate", "write_results"]

    result = next(event.data for event in events if event.type == "result")
    assert result.status == "review"
    assert "Schema.json" in result.schema_files
    assert "QualityReport.json" in result.report_files
    assert (runner.workspace / "InputManifest.json").exists()


def test_run_returns_error_when_report_is_missing(tmp_path):
    src = tmp_path / "sample.txt"
    src.write_text("plain text", encoding="utf-8")

    class MissingReportAgent:
        def run(self, prompt: str):
            yield TurnEvent(type="text", data="ok")
            yield TurnEvent(type="done")

    runner = DataQualityRunner(
        workspace=tmp_path / "ws",
        config=Config(model="test", api_key="test", stream=False),
    )
    runner._make_agent = lambda: MissingReportAgent()

    result = runner.run([src])

    assert result.status == "error"
    assert "QualityReport.json" in result.error
