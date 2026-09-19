import json
import unittest
from pathlib import Path

from toxoracle_app.join import combine_responses
from toxoracle_app.report import render_combined_report


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPOSITORY_ROOT / "contracts" / "examples"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.combined = combine_responses(
            load_json(EXAMPLES_DIR / "request.valid.json"),
            load_json(EXAMPLES_DIR / "discovery.not-run.json"),
            load_json(EXAMPLES_DIR / "toxicity.not-run.json"),
            load_json(REPOSITORY_ROOT / "configs" / "triage-v1.json"),
        )

    def test_report_contains_summary_and_unavailable_reason(self) -> None:
        report = render_combined_report(self.combined)

        self.assertIn("ToxOracle combined report", report)
        self.assertIn("candidate_001", report)
        self.assertIn("assessment_incomplete", report)
        self.assertIn("discovery=not_run", report)
        self.assertIn("Interface fixture only", report)

    def test_report_escapes_untrusted_text(self) -> None:
        self.combined["results"][0]["priority"][
            "recommendation"
        ] = "<script>alert('unsafe')</script>"

        report = render_combined_report(self.combined)

        self.assertNotIn("<script>alert", report)
        self.assertIn("&lt;script&gt;", report)

    def test_unsafe_artifact_uri_is_not_rendered_as_a_link(self) -> None:
        evidence = self.combined["results"][0]["discovery_result"][
            "structural_evidence"
        ]
        evidence["structure_artifacts"].append(
            {
                "artifact_id": "unsafe_artifact",
                "format": "sdf",
                "uri": "javascript:alert(1)",
                "checksum": "sha256:example",
                "origin": "predicted",
                "atom_mapping_ref": "example_structure_v1",
            }
        )

        report = render_combined_report(self.combined)

        self.assertNotIn('href="javascript:', report)
        self.assertIn("javascript:alert(1)", report)


if __name__ == "__main__":
    unittest.main()
