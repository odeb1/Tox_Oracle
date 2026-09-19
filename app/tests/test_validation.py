import copy
import json
import unittest
from pathlib import Path

from toxoracle_app.validation import (
    ContractValidationError,
    validate_request,
    validate_response_against_request,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPOSITORY_ROOT / "contracts" / "examples"


def load_example(name: str) -> dict:
    with (EXAMPLES_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = load_example("request.valid.json")
        self.discovery = load_example("discovery.not-run.json")

    def test_valid_response_matches_request(self) -> None:
        validate_response_against_request(
            self.request, self.discovery, expected_stream="discovery"
        )

    def test_duplicate_request_compound_id_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.request)
        invalid["compounds"].append(copy.deepcopy(invalid["compounds"][0]))

        with self.assertRaisesRegex(ContractValidationError, "duplicate compound_id"):
            validate_request(invalid)

    def test_missing_response_candidate_is_rejected(self) -> None:
        request = copy.deepcopy(self.request)
        second = copy.deepcopy(request["compounds"][0])
        second["compound_id"] = "candidate_002"
        second["structure_id"] = "example_structure_v2"
        request["compounds"].append(second)

        with self.assertRaisesRegex(ContractValidationError, "missing compound_id"):
            validate_response_against_request(request, self.discovery)

    def test_extra_response_candidate_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.discovery)
        extra = copy.deepcopy(invalid["results"][0])
        extra["compound_id"] = "candidate_999"
        extra["structure_id"] = "unexpected_structure"
        invalid["results"].append(extra)

        with self.assertRaisesRegex(ContractValidationError, "unexpected compound_id"):
            validate_response_against_request(self.request, invalid)

    def test_structure_mismatch_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.discovery)
        invalid["results"][0]["structure_id"] = "different_structure"

        with self.assertRaisesRegex(ContractValidationError, "structure_id mismatch"):
            validate_response_against_request(self.request, invalid)

    def test_atom_mapping_mismatch_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.discovery)
        invalid["results"][0]["structural_evidence"][
            "atom_mapped_smiles"
        ] = "[CH3:9][CH2:8][OH:7]"

        with self.assertRaisesRegex(
            ContractValidationError, "atom_mapped_smiles mismatch"
        ):
            validate_response_against_request(self.request, invalid)

    def test_wrong_stream_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.discovery)
        invalid["stream"] = "toxicity"

        with self.assertRaisesRegex(ContractValidationError, "expected stream"):
            validate_response_against_request(
                self.request, invalid, expected_stream="discovery"
            )


if __name__ == "__main__":
    unittest.main()
