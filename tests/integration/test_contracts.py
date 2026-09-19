import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPOSITORY_ROOT / "contracts"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


class ContractSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.request_schema = load_json(CONTRACTS_DIR / "request.schema.json")
        cls.response_schema = load_json(CONTRACTS_DIR / "response.schema.json")
        cls.request_validator = Draft202012Validator(cls.request_schema)
        cls.response_validator = Draft202012Validator(cls.response_schema)
        cls.request = load_json(EXAMPLES_DIR / "request.valid.json")
        cls.discovery_response = load_json(
            EXAMPLES_DIR / "discovery.not-run.json"
        )
        cls.toxicity_response = load_json(EXAMPLES_DIR / "toxicity.not-run.json")

    def test_schemas_are_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.request_schema)
        Draft202012Validator.check_schema(self.response_schema)

    def test_valid_request_fixture(self) -> None:
        self.request_validator.validate(self.request)

    def test_not_run_response_fixtures(self) -> None:
        self.response_validator.validate(self.discovery_response)
        self.response_validator.validate(self.toxicity_response)

    def test_response_identities_match_the_request(self) -> None:
        requested = {
            compound["compound_id"]: compound
            for compound in self.request["compounds"]
        }

        for response in (self.discovery_response, self.toxicity_response):
            self.assertEqual(response["request_id"], self.request["request_id"])
            self.assertEqual(
                {result["compound_id"] for result in response["results"]},
                set(requested),
            )
            for result in response["results"]:
                compound = requested[result["compound_id"]]
                evidence = result["structural_evidence"]
                self.assertEqual(result["structure_id"], compound["structure_id"])
                self.assertEqual(
                    evidence["canonical_smiles"], compound["canonical_smiles"]
                )
                self.assertEqual(
                    evidence["atom_mapped_smiles"],
                    compound["atom_mapped_smiles"],
                )
                self.assertEqual(
                    evidence["standardization_version"],
                    compound["standardization_version"],
                )

    def test_request_rejects_unknown_fields(self) -> None:
        invalid = copy.deepcopy(self.request)
        invalid["unexpected"] = True

        with self.assertRaises(ValidationError):
            self.request_validator.validate(invalid)

    def test_request_rejects_empty_compound_list(self) -> None:
        invalid = copy.deepcopy(self.request)
        invalid["compounds"] = []

        with self.assertRaises(ValidationError):
            self.request_validator.validate(invalid)

    def test_response_rejects_out_of_range_risk_score(self) -> None:
        invalid = copy.deepcopy(self.toxicity_response)
        result = invalid["results"][0]
        result["status"] = "ok"
        result["assessment"]["risk_score"] = 1.1
        result["assessment"]["score_kind"] = "uncalibrated_score"
        result["assessment"]["call"] = "positive"

        with self.assertRaises(ValidationError):
            self.response_validator.validate(invalid)

    def test_not_run_response_cannot_report_a_positive_call(self) -> None:
        invalid = copy.deepcopy(self.toxicity_response)
        invalid["results"][0]["assessment"]["call"] = "positive"

        with self.assertRaises(ValidationError):
            self.response_validator.validate(invalid)

    def test_failed_response_requires_an_error(self) -> None:
        invalid = copy.deepcopy(self.toxicity_response)
        invalid["results"][0]["status"] = "failed"

        with self.assertRaises(ValidationError):
            self.response_validator.validate(invalid)

    def test_calibrated_probability_requires_assessed_calibration(self) -> None:
        invalid = copy.deepcopy(self.toxicity_response)
        result = invalid["results"][0]
        result["status"] = "ok"
        result["assessment"]["risk_score"] = 0.75
        result["assessment"]["score_kind"] = "calibrated_probability"
        result["assessment"]["call"] = "positive"

        with self.assertRaises(ValidationError):
            self.response_validator.validate(invalid)


if __name__ == "__main__":
    unittest.main()
