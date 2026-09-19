import copy
import json
import unittest
from pathlib import Path

from toxoracle_app.comparison import compare_assessments


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPOSITORY_ROOT / "contracts" / "examples"


def load_example(name: str) -> dict:
    with (EXAMPLES_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def completed_pair(
    *, same_target: bool, calibrated: bool, calls_available: bool = True
) -> tuple[dict, dict]:
    discovery = copy.deepcopy(load_example("discovery.not-run.json")["results"][0])
    toxicity = copy.deepcopy(load_example("toxicity.not-run.json")["results"][0])
    discovery["status"] = "ok"
    toxicity["status"] = "ok"

    conventional = discovery["assessment"]
    human = toxicity["assessment"]
    if same_target:
        for field in (
            "endpoint_id",
            "positive_definition",
            "negative_definition",
            "context",
        ):
            conventional[field] = copy.deepcopy(human[field])

    conventional["risk_score"] = 0.25
    human["risk_score"] = 0.80
    score_kind = "calibrated_probability" if calibrated else "uncalibrated_score"
    calibration_status = "assessed" if calibrated else "not_assessed"
    for assessment in (conventional, human):
        assessment["score_kind"] = score_kind
        assessment["calibration"]["status"] = calibration_status

    if calls_available:
        conventional["call"] = "negative"
        human["call"] = "positive"
    else:
        conventional["call"] = "unavailable"
        human["call"] = "unavailable"

    return discovery, toxicity


class ComparisonTests(unittest.TestCase):
    def test_same_endpoint_calibrated_probabilities_allow_numeric_comparison(
        self,
    ) -> None:
        discovery, toxicity = completed_pair(same_target=True, calibrated=True)

        comparison = compare_assessments(discovery, toxicity)

        self.assertEqual(comparison["comparison_mode"], "same_endpoint_probability")
        self.assertEqual(comparison["status"], "available")
        self.assertAlmostEqual(comparison["signed_disagreement"], 0.55)
        self.assertAlmostEqual(comparison["absolute_disagreement"], 0.55)
        self.assertAlmostEqual(comparison["conservative_risk_score"], 0.80)
        self.assertEqual(comparison["call_disagreement"], 1)
        self.assertEqual(comparison["hidden_liability_flag"], 1)

    def test_same_endpoint_uncalibrated_scores_allow_calls_only(self) -> None:
        discovery, toxicity = completed_pair(same_target=True, calibrated=False)

        comparison = compare_assessments(discovery, toxicity)

        self.assertEqual(comparison["comparison_mode"], "same_endpoint_calls")
        self.assertEqual(comparison["status"], "available")
        self.assertIsNone(comparison["signed_disagreement"])
        self.assertIsNone(comparison["absolute_disagreement"])
        self.assertIsNone(comparison["conservative_risk_score"])
        self.assertEqual(comparison["call_disagreement"], 1)
        self.assertEqual(comparison["hidden_liability_flag"], 1)

    def test_different_endpoints_allow_cross_endpoint_calls_only(self) -> None:
        discovery, toxicity = completed_pair(same_target=False, calibrated=True)

        comparison = compare_assessments(discovery, toxicity)

        self.assertEqual(comparison["comparison_mode"], "cross_endpoint_calls")
        self.assertEqual(comparison["status"], "available")
        self.assertIsNone(comparison["signed_disagreement"])
        self.assertEqual(comparison["call_disagreement"], 1)
        self.assertEqual(comparison["hidden_liability_flag"], 1)

    def test_numeric_comparison_does_not_require_calls(self) -> None:
        discovery, toxicity = completed_pair(
            same_target=True, calibrated=True, calls_available=False
        )

        comparison = compare_assessments(discovery, toxicity)

        self.assertEqual(comparison["comparison_mode"], "same_endpoint_probability")
        self.assertAlmostEqual(comparison["signed_disagreement"], 0.55)
        self.assertIsNone(comparison["call_disagreement"])
        self.assertIsNone(comparison["hidden_liability_flag"])

    def test_missing_calls_and_ineligible_scores_are_unavailable(self) -> None:
        discovery, toxicity = completed_pair(
            same_target=True, calibrated=False, calls_available=False
        )

        comparison = compare_assessments(discovery, toxicity)

        self.assertEqual(comparison["comparison_mode"], "unavailable")
        self.assertEqual(comparison["status"], "unavailable")
        self.assertIsNone(comparison["signed_disagreement"])
        self.assertIsNone(comparison["call_disagreement"])

    def test_not_run_assessment_is_unavailable(self) -> None:
        discovery = load_example("discovery.not-run.json")["results"][0]
        toxicity = load_example("toxicity.not-run.json")["results"][0]

        comparison = compare_assessments(discovery, toxicity)

        self.assertEqual(comparison["comparison_mode"], "unavailable")
        self.assertEqual(comparison["status"], "unavailable")
        self.assertIn("discovery=not_run", comparison["reason"])
        self.assertIn("toxicity=not_run", comparison["reason"])


if __name__ == "__main__":
    unittest.main()
