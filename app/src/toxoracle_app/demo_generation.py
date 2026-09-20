"""Read-only presentation of the recorded ABL1 generation experiment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .demo_data import ROOT, StudyError, read_json

EVIDENCE_PATH = "evaluation/reports/generation_workflow_v1.json"


def validate_generation_summary(report: dict, protocol: dict) -> None:
    """Reject inconsistent aggregate evidence instead of inventing missing results."""
    def count(values: dict, key: str) -> int:
        value = values[key]
        if type(value) is not int or value < 0:
            raise StudyError(f"Invalid recorded count: {key}")
        return value

    try:
        if report["protocol"] != protocol["protocol"]:
            raise StudyError("The generation record and protocol do not match.")
        date.fromisoformat(report["date_london"])
        generation = report["generation"]
        outcomes = report["generation_rejection_counts"]
        returned = count(generation, "returned_count")
        accepted = count(generation, "accepted_unique_count")
        selected = count(generation, "selected_count")
        valid = count(generation, "valid_structure_count")
        totals = {key: count(outcomes, key) for key in
                  ("selected", "not_selected", "duplicate", "rejected")}
        if (returned != sum(totals.values()) or selected != totals["selected"]
                or accepted != selected + totals["not_selected"]
                or not 0 < selected <= accepted <= valid <= returned
                or selected > count(protocol, "max_candidates")):
            raise StudyError("The recorded generation counts do not reconcile.")
        shortlist = min(selected, count(protocol, "shortlist_size"))
        if not 0 < shortlist or count(report, "held_shortlist_count") > shortlist:
            raise StudyError("The recorded shortlist counts do not reconcile.")
        calls = report["dili_calls"]
        if set(calls) - {"positive", "negative", "unavailable"}:
            raise StudyError("Unknown recorded DILI call.")
        if sum(count(calls, key) for key in calls) != selected:
            raise StudyError("DILI call counts do not cover the selected panel.")
        live = report["boltz_execution"]["live_run"]
        if count(live, "live") + count(live, "cached") != selected + 1:
            raise StudyError("Discovery counts must include the separate reference.")
        if count(report["fitting_membership"], "excluded") > selected:
            raise StudyError("Fitting membership exceeds the selected panel.")
        count(report, "generation_batches")
        count(report, "automatic_replacements")
        for key in ("live_elapsed_seconds", "replay_elapsed_seconds"):
            if type(report[key]) not in (int, float) or report[key] < 0:
                raise StudyError("Invalid recorded duration.")
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, StudyError):
            raise
        raise StudyError("The recorded generation summary is incomplete or invalid.") from error


@dataclass(frozen=True)
class GenerationDemo:
    report: dict[str, Any]
    protocol: dict[str, Any]
    target: dict[str, Any]
    request: dict[str, Any]
    supplied_request: dict[str, Any]

    @property
    def selected(self) -> int:
        return self.report["generation"]["selected_count"]

    @property
    def shortlisted(self) -> int:
        return min(self.selected, self.protocol["shortlist_size"])

    @property
    def recorded_date(self) -> str:
        return date.fromisoformat(self.report["date_london"]).strftime("%d %B %Y")


def load_generation_demo(root: Path = ROOT) -> GenerationDemo:
    report = read_json(root / EVIDENCE_PATH)
    protocol = read_json(root / "configs/design-v1.json")
    validate_generation_summary(report, protocol)
    return GenerationDemo(
        report=report, protocol=protocol,
        target=read_json(root / "discovery/configs/targets/abl1.json"),
        request=read_json(root / "demo/examples/abl1_design_request.json"),
        supplied_request=read_json(root / "demo/examples/abl1_supplied_design_request.json"),
    )
