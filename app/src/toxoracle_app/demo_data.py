"""Read-only presentation adapters for existing, validated scientific outputs.

No inference, credentials, external requests or triage rules live in this module.
Full cases use the same contracts and comparison engine as the command-line demo.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from .join import combine_responses
from .report import render_combined_report
from .validation import validate_response_against_request

ROOT = Path(__file__).resolve().parents[3]
MAX_BYTES = 20 * 1024 * 1024


class StudyError(ValueError):
    """A study could not be loaded without changing or mislabelling evidence."""


def json_document(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_BYTES:
        raise StudyError("The study exceeds the 20 MB limit.")
    try:
        def invalid_constant(value: str) -> None:
            raise ValueError(f"Non-finite JSON value: {value}")
        value = json.loads(data, parse_constant=invalid_constant)
    except (ValueError, UnicodeDecodeError) as error:
        raise StudyError(f"Invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise StudyError("Each JSON document must contain an object.")
    return value


def read_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_BYTES:
        raise StudyError("The study exceeds the 20 MB limit.")
    return json_document(path.read_bytes())


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise StudyError("Study files must use relative paths within the case folder.")
    return str(path)


@dataclass
class Study:
    title: str
    request: dict[str, Any]
    toxicity: dict[str, Any]
    metadata: dict[str, Any]
    discovery: dict[str, Any] | None = None
    combined: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    names: dict[str, str] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    source_dir: Path | None = None
    files: dict[str, bytes] = field(default_factory=dict)

    def name(self, compound_id: str) -> str:
        return self.names.get(compound_id, compound_id)

    @property
    def results(self) -> list[dict[str, Any]]:
        by_id = {r["compound_id"]: r for r in self.toxicity["results"]}
        return [by_id[c["compound_id"]] for c in self.request["compounds"]]

    def joined(self, compound_id: str) -> dict[str, Any] | None:
        return next((r for r in (self.combined or {}).get("results", [])
                     if r["compound_id"] == compound_id), None)


def load_baseline(root: Path = ROOT) -> Study:
    folder = root / "demo/examples"
    request = read_json(folder / "dili_request.json")
    toxicity = read_json(folder / "dili_response.json")
    validate_response_against_request(request, toxicity, expected_stream="toxicity")
    names, references = {}, {}
    identities = {c["compound_id"]: c["structure_id"] for c in request["compounds"]}
    with (root / "data/processed/dilirank2_model_ready.csv").open() as file:
        for row in csv.DictReader(file):
            if identities.get(row["compound_id"]) == row["structure_id"]:
                names[row["compound_id"]] = row["compound_name"]
                references[row["compound_id"]] = row["original_dili_category"]
    return Study(
        title="Human liver-toxicity study", request=request, toxicity=toxicity,
        names=names, references=references, source_dir=folder,
        metadata={
            "case_id": "public_dili_baseline", "execution_mode": "cached",
            "result_class": "real", "training_membership": "held_out",
            "provenance_refs": ["demo/examples/dili_response.json",
                                "evaluation/reports/baseline_test.json"],
            "limitations": [
                "Three public held-out examples selected after evaluation for illustration; use the full test set to assess model performance.",
                "Drug-level DILI concern is not patient incidence, dose-response or clinical safety.",
                "This saved study contains the human DILI stream. Load a complete case to explore discovery-to-toxicity priority changes.",
            ],
        },
    )


def _build_case(files: dict[str, bytes], *, source_dir: Path | None = None) -> Study:
    if "manifest.json" not in files:
        raise StudyError("A complete case needs manifest.json.")
    manifest = json_document(files["manifest.json"])
    validator = Draft202012Validator(read_json(ROOT / "demo/case.schema.json"))
    errors = list(validator.iter_errors(manifest))
    if errors:
        raise StudyError("Invalid case manifest: " + errors[0].message)
    if manifest["status"] != "ready" or manifest["result_class"] != "real":
        raise StudyError("Choose a ready case containing real results. Interface fixtures are not scientific demo results.")

    def document(name: str) -> dict[str, Any]:
        key = safe_relative(name)
        if key not in files:
            raise StudyError(f"Missing case file: {key}")
        return json_document(files[key])

    request = document(manifest["request_file"])
    discovery = document(manifest["discovery_response_file"])
    toxicity = document(manifest["toxicity_response_file"])
    policy = document("policy.json") if "policy.json" in files else read_json(ROOT / "configs/triage-v1.json")
    combined = combine_responses(request, discovery, toxicity, policy)
    display = document("display.json") if "display.json" in files else {}
    names = display.get("compound_names", {})
    if not isinstance(names, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in names.items()):
        raise StudyError("display.json compound_names must map IDs to names.")
    title = display.get("title", manifest["case_id"].replace("_", " "))
    if not isinstance(title, str):
        raise StudyError("The study title must be text.")
    metadata = dict(manifest)
    # A saved result is always replayed as cached, even when it originally ran live.
    metadata["original_execution_mode"] = manifest["execution_mode"]
    metadata["execution_mode"] = "cached"
    metadata["input_checksums"] = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in files.items() if name.endswith(".json")
    }
    return Study(title=title, request=request, toxicity=toxicity, discovery=discovery,
                 combined=combined, policy=policy, names=names, metadata=metadata,
                 source_dir=source_dir, files=files)


def load_case_zip(data: bytes) -> Study:
    if len(data) > MAX_BYTES:
        raise StudyError("The study exceeds the 20 MB limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [item for item in archive.infolist() if not item.is_dir()]
            if len(entries) > 100 or sum(item.file_size for item in entries) > MAX_BYTES:
                raise StudyError("Use at most 100 files and 20 MB uncompressed per case.")
            names = [safe_relative(item.filename) for item in entries]
            if len(names) != len(set(names)):
                raise StudyError("The case contains duplicate file names.")
            manifests = [name for name in names if PurePosixPath(name).name == "manifest.json"]
            if len(manifests) != 1:
                raise StudyError("Include exactly one manifest.json in the ZIP.")
            base = PurePosixPath(manifests[0]).parent
            files = {}
            for item, name in zip(entries, names):
                path = PurePosixPath(name)
                if path.is_relative_to(base):
                    files[str(path.relative_to(base))] = archive.read(item)
            return _build_case(files)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise StudyError("Use an unencrypted ZIP containing a complete case.") from error


def load_case_directory(folder: Path) -> Study:
    folder = folder.resolve()
    manifest = read_json(folder / "manifest.json")
    names = ["manifest.json"] + [manifest.get(key, "") for key in
                                  ("request_file", "discovery_response_file", "toxicity_response_file")]
    names += [name for name in ("policy.json", "display.json") if (folder / name).is_file()]
    files = {}
    for name in names:
        key = safe_relative(name)
        path = (folder / key).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise StudyError(f"Missing file or path outside the case folder: {key}")
        if path.stat().st_size > MAX_BYTES:
            raise StudyError("The study exceeds the 20 MB limit.")
        files[key] = path.read_bytes()
    return _build_case(files, source_dir=folder)


def artifact_bytes(study: Study, uri: str, checksum: str | None = None) -> bytes:
    key = safe_relative(uri)
    if key in study.files:
        content = study.files[key]
    elif study.source_dir is not None:
        root = study.source_dir.resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise StudyError("This artifact is not included in the study folder.")
        content = path.read_bytes()
    else:
        raise StudyError("This artifact is not included in the study bundle.")
    if checksum and checksum.startswith("sha256:"):
        if hashlib.sha256(content).hexdigest() != checksum.removeprefix("sha256:"):
            raise StudyError("The artifact checksum does not match its scientific record.")
    return content


def candidate_rows(study: Study) -> list[dict[str, Any]]:
    rows = []
    for result in study.results:
        assessment = result["assessment"]
        complete = result["status"] == "ok"
        joined = study.joined(result["compound_id"])
        row = {
            "Candidate": study.name(result["compound_id"]),
            "Compound ID": result["compound_id"],
            "DILI score": assessment["risk_score"] if complete else None,
            "Assessment": assessment["call"] if complete else "unavailable",
            "Status": result["status"],
            "Training similarity": assessment["applicability"]["value"] if complete else None,
            "Training membership": result["provenance"]["training_membership"],
        }
        if joined:
            row["Discovery priority"] = joined["priority"]["original_priority"]
            row["Revised priority"] = joined["priority"]["revised_priority"]
        rows.append(row)
    return rows


def export_csv(study: Study) -> str:
    rows = candidate_rows(study)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    # Prevent spreadsheet formula execution in display names from imported studies.
    for row in rows:
        writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                         for k, v in row.items()})
    return output.getvalue()


def export_html(study: Study) -> str:
    if study.combined:
        report = render_combined_report(study.combined)
        banner = '<aside style="padding:16px;background:#eef4ed">Cached replay · ' + escape(study.title) + '</aside>'
        return report.replace("<body>", "<body>" + banner, 1)
    rows = candidate_rows(study)
    headings = "".join(f"<th>{escape(k)}</th>" for k in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{escape(str(v)) if v is not None else 'Unavailable'}</td>" for v in row.values()) + "</tr>" for row in rows)
    notes = "".join(f"<li>{escape(note)}</li>" for note in study.metadata["limitations"])
    evidence = escape(json.dumps(study.toxicity, indent=2, allow_nan=False))
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>ToxOracle study</title>
    <style>body{{font:16px system-ui;max-width:1100px;margin:48px auto;color:#173c36;padding:24px}}th,td{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}table{{border-collapse:collapse;width:100%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}h1{{font-size:36px}}</style>
    <body><p>TOXORACLE · CACHED SCIENTIFIC RESULTS</p><h1>{escape(study.title)}</h1>
    <table><thead><tr>{headings}</tr></thead><tbody>{body}</tbody></table><h2>Study context</h2><ul>{notes}</ul>
    <details><summary>Complete source evidence</summary><pre>{evidence}</pre></details></body></html>'''
