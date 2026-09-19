import copy
import json
import unittest
from pathlib import Path

from toxoracle_app.discovery_bridge import normalize_discovery_evidence
from toxoracle_app.validation import ContractValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUEST_PATH = REPOSITORY_ROOT / "contracts" / "examples" / "request.valid.json"


def load_request() -> dict:
    with REQUEST_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def discovery_evidence() -> dict:
    return {
        "schema_version": "2.0",
        "request_id": "demo_run_01",
        "stream": "discovery_evidence",
        "target": {"target_id": "target_001", "pdb_id": "1ABC", "chain": "A"},
        "results": [
            {
                "compound_id": "candidate_001",
                "structure_id": "example_structure_v1",
                "status": "ok",
                "supplementary_metrics": [
                    {
                        "name": "diffdock_best_pose_confidence",
                        "value": 0.8,
                        "unit": "unitless",
                        "direction": "higher_is_more_confident",
                        "meaning": "Highest confidence among returned poses",
                        "source_ref": "diffdock_model_reference",
                    }
                ],
                "structural_evidence": {
                    "structure_artifacts": [
                        {
                            "artifact_id": "candidate_atom_mapping",
                            "format": "json",
                            "uri": "artifacts/candidate_atom_mapping.json",
                            "checksum": "sha256:graph",
                        },
                        {
                            "artifact_id": "candidate_pose_001",
                            "format": "sdf",
                            "uri": "artifacts/candidate_pose_001.sdf",
                            "checksum": "sha256:pose",
                            "origin": "predicted",
                            "atom_mapping_ref": "unverified_vendor_output",
                            "model_id": "nvidia_nim_diffdock",
                            "target_id": "target_001",
                            "conformer_id": "pose_1",
                        },
                    ],
                    "interactions": [
                        {
                            "atom_map_ids": [2],
                            "target_id": "target_001",
                            "chain": "A",
                            "residue_name": "ASP",
                            "residue_number": 42,
                            "insertion_code": "",
                            "interaction_type": "distance_contact",
                            "distance_angstrom": 3.2,
                            "artifact_ref": "candidate_pose_001",
                        }
                    ],
                },
                "service_artifacts": [],
                "provenance": {"method_id": "nvidia_nim_diffdock"},
                "warnings": [
                    "Pose confidence is pose reliability, not affinity or toxicity."
                ],
                "error": None,
            }
        ],
        "warnings": ["Discovery evidence only."],
    }


class DiscoveryBridgeTests(unittest.TestCase):
    def test_normalizes_identity_metrics_artifacts_and_contacts(self) -> None:
        normalized = normalize_discovery_evidence(
            load_request(), discovery_evidence()
        )

        self.assertEqual(normalized["stream"], "normalized_discovery_evidence")
        result = normalized["results"][0]
        self.assertEqual(result["compound_id"], "candidate_001")
        self.assertEqual(result["structure_id"], "example_structure_v1")
        self.assertNotIn("assessment", result)
        self.assertEqual(
            result["provenance"]["evidence_role"], "therapeutic_discovery_only"
        )
        evidence = result["structural_evidence"]
        self.assertEqual(evidence["canonical_smiles"], "CCO")
        self.assertEqual(
            evidence["structure_artifacts"][0]["origin"], "generated"
        )
        self.assertEqual(
            evidence["structure_artifacts"][0]["atom_mapping_ref"],
            "example_structure_v1",
        )
        self.assertEqual(evidence["interactions"][0]["chain_id"], "A")
        self.assertEqual(evidence["interactions"][0]["residue_id"], "ASP:42")
        self.assertEqual(
            result["supplementary_metrics"][0]["name"],
            "diffdock_best_pose_confidence",
        )

    def test_structure_mismatch_is_rejected(self) -> None:
        evidence = discovery_evidence()
        evidence["results"][0]["structure_id"] = "different_structure"

        with self.assertRaisesRegex(ContractValidationError, "structure_id mismatch"):
            normalize_discovery_evidence(load_request(), evidence)

    def test_missing_candidate_is_rejected(self) -> None:
        evidence = discovery_evidence()
        evidence["results"] = []

        with self.assertRaisesRegex(ContractValidationError, "missing compound IDs"):
            normalize_discovery_evidence(load_request(), evidence)

    def test_error_type_is_normalized_to_error_code(self) -> None:
        evidence = discovery_evidence()
        result = evidence["results"][0]
        result["status"] = "failed"
        result["error"] = {
            "type": "diffdock_request_failed",
            "message": "service unavailable",
        }

        normalized = normalize_discovery_evidence(load_request(), evidence)

        self.assertEqual(
            normalized["results"][0]["error"],
            {
                "code": "diffdock_request_failed",
                "message": "service unavailable",
            },
        )

    def test_unmapped_artifact_is_excluded_with_warning(self) -> None:
        evidence = discovery_evidence()
        artifact = evidence["results"][0]["structural_evidence"][
            "structure_artifacts"
        ][1]
        artifact.pop("atom_mapping_ref")

        normalized = normalize_discovery_evidence(load_request(), evidence)

        result = normalized["results"][0]
        self.assertEqual(len(result["structural_evidence"]["structure_artifacts"]), 1)
        self.assertTrue(
            any("excluded" in warning for warning in result["warnings"])
        )

    def test_wrong_stream_is_rejected(self) -> None:
        evidence = discovery_evidence()
        evidence["stream"] = "discovery"

        with self.assertRaisesRegex(ContractValidationError, "stream must be"):
            normalize_discovery_evidence(load_request(), evidence)

    def test_malformed_evidence_collection_is_rejected(self) -> None:
        evidence = discovery_evidence()
        evidence["results"][0]["supplementary_metrics"] = None

        with self.assertRaisesRegex(ContractValidationError, "must be an array"):
            normalize_discovery_evidence(load_request(), evidence)

    def test_normalization_does_not_mutate_source_evidence(self) -> None:
        evidence = discovery_evidence()
        original = copy.deepcopy(evidence)

        normalize_discovery_evidence(load_request(), evidence)

        self.assertEqual(evidence, original)


if __name__ == "__main__":
    unittest.main()
