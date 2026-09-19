import json
import shutil
import tempfile
import unittest
from pathlib import Path

from demo.run_case import DemoCaseError, run_case


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPOSITORY_ROOT / "contracts" / "examples"
POLICY_PATH = REPOSITORY_ROOT / "configs" / "triage-v1.json"


class DemoCaseRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.case_dir = self.root / "case-01"
        self.output_dir = self.root / "outputs"
        self.case_dir.mkdir()

        files = {
            "request.json": "request.valid.json",
            "discovery-response.json": "discovery.not-run.json",
            "toxicity-response.json": "toxicity.not-run.json",
        }
        for destination, source in files.items():
            shutil.copyfile(EXAMPLES_DIR / source, self.case_dir / destination)

        self.manifest = {
            "schema_version": "1.0",
            "case_id": "case-01",
            "status": "ready",
            "execution_mode": "cached",
            "result_class": "interface_fixture",
            "training_membership": "not_applicable",
            "request_file": "request.json",
            "discovery_response_file": "discovery-response.json",
            "toxicity_response_file": "toxicity-response.json",
            "tool_versions": {},
            "provenance_refs": [],
            "limitations": ["Automated dry-run fixture; not a scientific result."],
        }
        self._write_manifest()

    def _write_manifest(self) -> None:
        with (self.case_dir / "manifest.json").open("w", encoding="utf-8") as file:
            json.dump(self.manifest, file)

    def test_interface_fixture_is_rejected_by_default(self) -> None:
        with self.assertRaisesRegex(DemoCaseError, "not permitted"):
            run_case(self.case_dir, POLICY_PATH, self.output_dir)

    def test_explicit_dry_run_writes_reports_and_checksums(self) -> None:
        outputs = run_case(
            self.case_dir,
            POLICY_PATH,
            self.output_dir,
            allow_interface_fixture=True,
        )

        self.assertTrue(outputs["json"].is_file())
        self.assertTrue(outputs["html"].is_file())
        self.assertTrue(outputs["metadata"].is_file())
        with outputs["metadata"].open(encoding="utf-8") as file:
            metadata = json.load(file)
        self.assertEqual(metadata["result_class"], "interface_fixture")
        self.assertEqual(len(metadata["inputs"]["request"]["sha256"]), 64)
        self.assertEqual(
            len(metadata["outputs"]["combined_report_html"]["sha256"]), 64
        )

    def test_case_file_cannot_escape_case_directory(self) -> None:
        outside = self.root / "outside.json"
        shutil.copyfile(EXAMPLES_DIR / "request.valid.json", outside)
        self.manifest["request_file"] = "../outside.json"
        self._write_manifest()

        with self.assertRaisesRegex(DemoCaseError, "escapes the case directory"):
            run_case(
                self.case_dir,
                POLICY_PATH,
                self.output_dir,
                allow_interface_fixture=True,
            )

    def test_real_case_requires_versions_and_provenance(self) -> None:
        self.manifest["result_class"] = "real"
        self._write_manifest()

        with self.assertRaises(DemoCaseError):
            run_case(self.case_dir, POLICY_PATH, self.output_dir)


if __name__ == "__main__":
    unittest.main()
