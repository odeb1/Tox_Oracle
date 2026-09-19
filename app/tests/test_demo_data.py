"""Scientific identity and import/export regressions for the presentation layer."""

import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from toxoracle_app.demo_data import (
    ROOT, StudyError, artifact_bytes, candidate_rows, export_csv, export_html,
    json_document, load_baseline, load_case_directory, load_case_zip,
)
from toxoracle_app.validation import ContractValidationError


def case_documents():
    """Synthetic test-only case, never included in the scientific demo library."""
    request = json.loads((ROOT / "contracts/examples/request.valid.json").read_text())
    discovery = json.loads((ROOT / "contracts/examples/discovery.not-run.json").read_text())
    toxicity = json.loads((ROOT / "contracts/examples/toxicity.not-run.json").read_text())
    policy = json.loads((ROOT / "configs/triage-v1.json").read_text())
    policy["toxicity_reliability"]["credible_minimum"] = .4
    for envelope in (discovery, toxicity):
        for result in envelope["results"]:
            result["status"] = "ok"
            result["assessment"].update(risk_score=.7, score_kind="uncalibrated_score", call="positive", threshold=.5)
            result["assessment"]["applicability"].update(value=.8)
    for result in discovery["results"]:
        result["supplementary_metrics"] = [{"name": "discovery_priority", "value": "promising",
            "unit": None, "direction": None, "meaning": "TEST ONLY", "source_ref": "test_fixture"}]
    manifest = {
        "schema_version": "1.0", "case_id": "unit-test-only", "status": "ready",
        "execution_mode": "live", "result_class": "real", "training_membership": "unknown",
        "request_file": "request.json", "discovery_response_file": "discovery-response.json",
        "toxicity_response_file": "toxicity-response.json", "tool_versions": {"test": "1"},
        "provenance_refs": ["test_fixture"], "limitations": ["Synthetic test-only input."],
    }
    return {"manifest.json": manifest, "request.json": request,
            "discovery-response.json": discovery, "toxicity-response.json": toxicity, "policy.json": policy}


def case_zip(documents, extra=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in documents.items():
            archive.writestr("study/" + name, json.dumps(content))
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


class DemoDataTests(unittest.TestCase):
    def test_bundled_study_preserves_actual_scores_and_molecular_identity(self):
        study = load_baseline()
        source = json.loads((ROOT / "demo/examples/dili_response.json").read_text())
        self.assertEqual(study.toxicity, source)
        self.assertEqual(study.name("LT00507"), "Amoxicillin")
        self.assertIsNone(study.combined)
        self.assertEqual(len(candidate_rows(study)), 3)

    def test_complete_case_replays_as_cached_and_uses_existing_decision_policy(self):
        study = load_case_zip(case_zip(case_documents()))
        self.assertEqual(study.metadata["execution_mode"], "cached")
        self.assertEqual(study.metadata["original_execution_mode"], "live")
        self.assertEqual(study.combined["results"][0]["priority"]["revised_priority"], "hold_for_safety_validation")
        self.assertIn("Cached replay", export_html(study))
        self.assertEqual(len(study.metadata["input_checksums"]["request.json"]), 64)

    def test_mismatched_compound_cannot_be_imported(self):
        documents = case_documents()
        documents["toxicity-response.json"]["results"][0]["structure_id"] = "wrong_structure"
        with self.assertRaises(ContractValidationError):
            load_case_zip(case_zip(documents))

    def test_fixtures_and_pending_cases_are_rejected(self):
        for field, value in (("result_class", "interface_fixture"), ("status", "pending")):
            documents = case_documents()
            documents["manifest.json"][field] = value
            with self.subTest(field=field), self.assertRaises(StudyError):
                load_case_zip(case_zip(documents))

    def test_archive_path_traversal_and_missing_inputs_are_rejected(self):
        with self.assertRaises(StudyError):
            load_case_zip(case_zip(case_documents(), {"../outside.json": "{}"}))
        documents = case_documents()
        del documents["toxicity-response.json"]
        with self.assertRaisesRegex(StudyError, "Missing case file"):
            load_case_zip(case_zip(documents))

    def test_artifacts_are_contained_and_checksummed(self):
        study = load_case_zip(case_zip(case_documents(), {"study/pose.sdf": "pose data"}))
        checksum = "sha256:" + hashlib.sha256(b"pose data").hexdigest()
        self.assertEqual(artifact_bytes(study, "pose.sdf", checksum), b"pose data")
        with self.assertRaisesRegex(StudyError, "checksum"):
            artifact_bytes(study, "pose.sdf", "sha256:bad")
        with self.assertRaises(StudyError):
            artifact_bytes(study, "../../.env")

    def test_directory_import_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "case"
            folder.mkdir()
            for name, value in case_documents().items():
                (folder / name).write_text(json.dumps(value))
            study = load_case_directory(folder)
            self.assertIsNotNone(study.combined)
            (root / "outside.txt").write_text("outside")
            (folder / "escape.txt").symlink_to(root / "outside.txt")
            with self.assertRaises(StudyError):
                artifact_bytes(study, "escape.txt")

    def test_failed_assessment_is_never_shown_as_a_zero_score(self):
        study = load_baseline()
        study.toxicity = copy.deepcopy(study.toxicity)
        study.toxicity["results"][0]["status"] = "failed"
        row = candidate_rows(study)[0]
        self.assertIsNone(row["DILI score"])
        self.assertEqual(row["Assessment"], "unavailable")

    def test_exports_escape_html_and_spreadsheet_formulas(self):
        study = load_baseline()
        study.title = "<script>alert(1)</script>"
        study.names[study.results[0]["compound_id"]] = "=HYPERLINK(\"example\")"
        self.assertNotIn("<script>", export_html(study))
        self.assertIn("'=HYPERLINK", export_csv(study))

    def test_nonfinite_json_is_rejected(self):
        with self.assertRaises(StudyError):
            json_document(b'{"score": NaN}')


if __name__ == "__main__":
    unittest.main()
