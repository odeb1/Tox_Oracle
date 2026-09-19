import copy
import json
import unittest
from pathlib import Path

from toxoracle_app.join import combine_responses


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPOSITORY_ROOT / "contracts" / "examples"
POLICY_PATH = REPOSITORY_ROOT / "configs" / "triage-v1.json"


def load_example(name: str) -> dict:
    with (EXAMPLES_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


class JoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = load_example("request.valid.json")
        self.discovery = load_example("discovery.not-run.json")
        self.toxicity = load_example("toxicity.not-run.json")
        with POLICY_PATH.open(encoding="utf-8") as file:
            self.policy = json.load(file)

    def test_combine_preserves_identity_and_both_streams(self) -> None:
        combined = combine_responses(
            self.request, self.discovery, self.toxicity, self.policy
        )

        self.assertEqual(combined["schema_version"], "2.0")
        self.assertEqual(combined["request_id"], "demo_run_01")
        self.assertEqual(len(combined["results"]), 1)
        result = combined["results"][0]
        self.assertEqual(result["compound_id"], "candidate_001")
        self.assertEqual(result["structure_id"], "example_structure_v1")
        self.assertEqual(result["identity_status"], "matched")
        self.assertEqual(result["discovery_result"]["compound_id"], "candidate_001")
        self.assertEqual(result["toxicity_result"]["compound_id"], "candidate_001")
        self.assertEqual(result["comparison"]["comparison_mode"], "unavailable")
        self.assertEqual(result["comparison"]["status"], "unavailable")
        self.assertEqual(result["priority"]["status"], "unavailable")
        self.assertEqual(
            result["priority"]["revised_priority"], "assessment_incomplete"
        )

    def test_combine_uses_request_order(self) -> None:
        request = copy.deepcopy(self.request)
        discovery = copy.deepcopy(self.discovery)
        toxicity = copy.deepcopy(self.toxicity)

        second_compound = copy.deepcopy(request["compounds"][0])
        second_compound["compound_id"] = "candidate_002"
        second_compound["structure_id"] = "example_structure_v2"
        request["compounds"].append(second_compound)

        for response in (discovery, toxicity):
            second_result = copy.deepcopy(response["results"][0])
            second_result["compound_id"] = "candidate_002"
            second_result["structure_id"] = "example_structure_v2"
            response["results"] = [second_result, response["results"][0]]

        combined = combine_responses(request, discovery, toxicity, self.policy)

        self.assertEqual(
            [result["compound_id"] for result in combined["results"]],
            ["candidate_001", "candidate_002"],
        )

    def test_failure_cases_never_become_low_risk_results(self) -> None:
        request = load_example("request.failure-cases.json")
        discovery = load_example("discovery.failure-cases.json")
        toxicity = copy.deepcopy(self.toxicity)
        toxicity["request_id"] = request["request_id"]
        toxicity["results"] = []
        base_result = self.toxicity["results"][0]
        for compound in request["compounds"]:
            result = copy.deepcopy(base_result)
            result["compound_id"] = compound["compound_id"]
            result["structure_id"] = compound["structure_id"]
            result["structural_evidence"]["canonical_smiles"] = compound[
                "canonical_smiles"
            ]
            result["structural_evidence"]["atom_mapped_smiles"] = compound[
                "atom_mapped_smiles"
            ]
            result["structural_evidence"]["standardization_version"] = compound[
                "standardization_version"
            ]
            toxicity["results"].append(result)

        combined = combine_responses(request, discovery, toxicity, self.policy)

        self.assertEqual(len(combined["results"]), 3)
        for result in combined["results"]:
            self.assertEqual(result["comparison"]["status"], "unavailable")
            self.assertIsNone(result["comparison"]["conservative_risk_score"])
            self.assertEqual(result["priority"]["status"], "unavailable")
            self.assertEqual(
                result["priority"]["revised_priority"], "assessment_incomplete"
            )


if __name__ == "__main__":
    unittest.main()
