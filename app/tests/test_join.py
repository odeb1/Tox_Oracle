import copy
import json
import unittest
from pathlib import Path

from toxoracle_app.join import combine_responses


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPOSITORY_ROOT / "contracts" / "examples"


def load_example(name: str) -> dict:
    with (EXAMPLES_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


class JoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = load_example("request.valid.json")
        self.discovery = load_example("discovery.not-run.json")
        self.toxicity = load_example("toxicity.not-run.json")

    def test_combine_preserves_identity_and_both_streams(self) -> None:
        combined = combine_responses(self.request, self.discovery, self.toxicity)

        self.assertEqual(combined["schema_version"], "2.0")
        self.assertEqual(combined["request_id"], "demo_run_01")
        self.assertEqual(len(combined["results"]), 1)
        result = combined["results"][0]
        self.assertEqual(result["compound_id"], "candidate_001")
        self.assertEqual(result["structure_id"], "example_structure_v1")
        self.assertEqual(result["identity_status"], "matched")
        self.assertEqual(result["discovery_result"]["compound_id"], "candidate_001")
        self.assertEqual(result["toxicity_result"]["compound_id"], "candidate_001")

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

        combined = combine_responses(request, discovery, toxicity)

        self.assertEqual(
            [result["compound_id"] for result in combined["results"]],
            ["candidate_001", "candidate_002"],
        )


if __name__ == "__main__":
    unittest.main()
