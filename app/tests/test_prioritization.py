import copy
import json
import unittest
from pathlib import Path

from toxoracle_app.prioritization import prioritize_candidate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPOSITORY_ROOT / "contracts" / "examples"
POLICY_PATH = REPOSITORY_ROOT / "configs" / "triage-v1.json"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def completed_inputs(
    *, discovery_priority: str = "promising", human_call: str = "positive"
) -> tuple[dict, dict, dict, dict]:
    discovery = copy.deepcopy(load_json(EXAMPLES_DIR / "discovery.not-run.json"))[
        "results"
    ][0]
    toxicity = copy.deepcopy(load_json(EXAMPLES_DIR / "toxicity.not-run.json"))[
        "results"
    ][0]
    policy = copy.deepcopy(load_json(POLICY_PATH))

    discovery["status"] = "ok"
    toxicity["status"] = "ok"
    discovery["supplementary_metrics"] = [
        {
            "name": "discovery_priority",
            "value": discovery_priority,
            "unit": None,
            "direction": None,
            "meaning": "Priority from the agreed discovery criterion",
            "source_ref": "discovery_rule_v1",
        }
    ]
    toxicity["assessment"]["call"] = human_call
    toxicity["assessment"]["applicability"] = {
        "method": "nearest_train_tanimoto",
        "value": 0.8,
    }
    policy["toxicity_reliability"]["credible_minimum"] = 0.4
    comparison = {
        "status": "available",
        "reason": "Call comparison is available.",
    }
    return discovery, toxicity, comparison, policy


class PrioritizationTests(unittest.TestCase):
    def test_promising_positive_credible_candidate_is_held_for_validation(self) -> None:
        discovery, toxicity, comparison, policy = completed_inputs()

        priority = prioritize_candidate(
            discovery, toxicity, comparison, policy
        )

        self.assertEqual(priority["original_priority"], "promising")
        self.assertEqual(priority["revised_priority"], "hold_for_safety_validation")
        self.assertEqual(priority["toxicity_reliability"], "credible")
        self.assertIsNotNone(priority["proposed_experiment"])

    def test_weak_positive_credible_candidate_is_deprioritized(self) -> None:
        discovery, toxicity, comparison, policy = completed_inputs(
            discovery_priority="weak"
        )

        priority = prioritize_candidate(discovery, toxicity, comparison, policy)

        self.assertEqual(priority["original_priority"], "weak")
        self.assertEqual(priority["revised_priority"], "deprioritize")

    def test_promising_negative_credible_candidate_continues(self) -> None:
        discovery, toxicity, comparison, policy = completed_inputs(
            human_call="negative"
        )

        priority = prioritize_candidate(discovery, toxicity, comparison, policy)

        self.assertEqual(priority["revised_priority"], "continue_evaluation")
        self.assertIn("does not establish safety", priority["recommendation"])
        self.assertIsNone(priority["proposed_experiment"])

    def test_unconfigured_applicability_threshold_requires_more_evidence(self) -> None:
        discovery, toxicity, comparison, policy = completed_inputs()
        policy["toxicity_reliability"]["credible_minimum"] = None

        priority = prioritize_candidate(discovery, toxicity, comparison, policy)

        self.assertEqual(priority["toxicity_reliability"], "unknown")
        self.assertEqual(priority["revised_priority"], "safety_evidence_required")
        self.assertIsNotNone(priority["proposed_experiment"])

    def test_out_of_domain_candidate_requires_more_evidence(self) -> None:
        discovery, toxicity, comparison, policy = completed_inputs()
        toxicity["assessment"]["applicability"]["value"] = 0.2

        priority = prioritize_candidate(discovery, toxicity, comparison, policy)

        self.assertEqual(priority["toxicity_reliability"], "outside_supported_space")
        self.assertEqual(priority["revised_priority"], "safety_evidence_required")

    def test_failed_toxicity_assessment_remains_incomplete(self) -> None:
        discovery, toxicity, comparison, policy = completed_inputs()
        toxicity["status"] = "failed"

        priority = prioritize_candidate(discovery, toxicity, comparison, policy)

        self.assertEqual(priority["status"], "unavailable")
        self.assertEqual(priority["revised_priority"], "assessment_incomplete")
        self.assertIn("toxicity=failed", priority["limitations"][0])

    def test_missing_discovery_priority_remains_unavailable(self) -> None:
        discovery, toxicity, comparison, policy = completed_inputs()
        discovery["supplementary_metrics"] = []

        priority = prioritize_candidate(discovery, toxicity, comparison, policy)

        self.assertEqual(priority["original_priority"], "unavailable")
        self.assertEqual(priority["status"], "unavailable")
        self.assertIn("Discovery priority is unavailable", priority["recommendation"])


if __name__ == "__main__":
    unittest.main()
