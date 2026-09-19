import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from toxoracle_app.join import combine_responses
from toxoracle_app.validation import (
    ContractValidationError,
    validate_combined_report,
    validate_policy,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPOSITORY_ROOT / "contracts" / "examples"
POLICY_PATH = REPOSITORY_ROOT / "configs" / "triage-v1.json"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


class OutputValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_json(POLICY_PATH)
        self.combined = combine_responses(
            load_json(EXAMPLES_DIR / "request.valid.json"),
            load_json(EXAMPLES_DIR / "discovery.not-run.json"),
            load_json(EXAMPLES_DIR / "toxicity.not-run.json"),
            self.policy,
        )

    def test_policy_and_combined_schemas_are_valid(self) -> None:
        Draft202012Validator.check_schema(
            load_json(REPOSITORY_ROOT / "configs" / "triage.schema.json")
        )
        Draft202012Validator.check_schema(
            load_json(
                REPOSITORY_ROOT / "contracts" / "combined-report.schema.json"
            )
        )

    def test_current_provisional_policy_is_valid(self) -> None:
        validate_policy(self.policy)

    def test_approved_policy_requires_a_reliability_threshold(self) -> None:
        invalid = copy.deepcopy(self.policy)
        invalid["status"] = "approved"

        with self.assertRaises(ContractValidationError):
            validate_policy(invalid)

    def test_priority_categories_cannot_overlap(self) -> None:
        invalid = copy.deepcopy(self.policy)
        invalid["weak_values"].append("PROMISING")

        with self.assertRaisesRegex(ContractValidationError, "overlap"):
            validate_policy(invalid)

    def test_generated_combined_report_is_valid(self) -> None:
        validate_combined_report(self.combined)

    def test_unavailable_comparison_cannot_contain_a_numeric_result(self) -> None:
        invalid = copy.deepcopy(self.combined)
        invalid["results"][0]["comparison"]["signed_disagreement"] = 0.5

        with self.assertRaises(ContractValidationError):
            validate_combined_report(invalid)

    def test_call_only_comparison_cannot_claim_a_conservative_probability(self) -> None:
        invalid = copy.deepcopy(self.combined)
        comparison = invalid["results"][0]["comparison"]
        comparison["comparison_mode"] = "cross_endpoint_calls"
        comparison["status"] = "available"
        comparison["call_disagreement"] = 1
        comparison["hidden_liability_flag"] = 1
        comparison["conservative_risk_score"] = 0.8

        with self.assertRaises(ContractValidationError):
            validate_combined_report(invalid)


if __name__ == "__main__":
    unittest.main()
