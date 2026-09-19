import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toxoracle_discovery.cli import _read_target, run_batch
from toxoracle_discovery.diffdock import DiffDockError, DiffDockNIMClient, DiffDockRequest, DockingEvidence


class DiffDockRequestTest(unittest.TestCase):
    def test_documented_defaults_are_serialised(self):
        request = DiffDockRequest(protein="ATOM example", ligand="CCO")

        self.assertEqual(
            request.to_payload(),
            {
                "protein": "ATOM example",
                "ligand": "CCO",
                "ligand_file_type": "smiles",
                "num_poses": 10,
                "time_divisions": 20,
                "steps": 18,
                "save_trajectory": False,
                "skip_gen_conformer": False,
                "is_staged": False,
            },
        )

    def test_unsupported_ligand_type_is_rejected(self):
        with self.assertRaises(ValueError):
            DiffDockRequest(protein="ATOM example", ligand="CCO", ligand_file_type="pdb")


class DiffDockClientTest(unittest.TestCase):
    def test_missing_api_key_fails_before_a_live_request(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}, clear=False):
            with self.assertRaises(DiffDockError):
                DiffDockNIMClient.from_environment()


class DockingEvidenceTest(unittest.TestCase):
    def test_response_keeps_confidence_as_pose_reliability_and_saves_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = DockingEvidence.from_response(
                "candidate_001",
                {
                    "pose_confidence": [0.1, 0.9],
                    "docked_ligand": "example sdf",
                    "visualizations_files": "example pdb",
                },
                Path(directory),
            )

            metrics = {metric["name"]: metric["value"] for metric in evidence.supplementary_metrics}
            self.assertEqual(metrics["diffdock_best_pose_confidence"], 0.9)
            self.assertEqual(metrics["diffdock_returned_pose_count"], 2)
            self.assertEqual(len(evidence.structure_artifacts), 2)
            self.assertEqual(len(evidence.service_artifacts), 1)
            self.assertTrue(all(Path(item["uri"]).exists() for item in evidence.structure_artifacts))
            self.assertTrue(Path(evidence.service_artifacts[0]["uri"]).exists())
            self.assertTrue(any("not binding affinity" in warning for warning in evidence.warnings))


class BatchRunnerTest(unittest.TestCase):
    def test_batch_preserves_valid_id_and_returns_invalid_input_record(self):
        def fake_transport(endpoint, headers, payload):
            self.assertIn("Bearer example-key", headers["Authorization"])
            self.assertEqual(payload["ligand"], "CCO")
            return {"pose_confidence": [0.3, 0.7]}

        client = DiffDockNIMClient("example-key", transport=fake_transport)
        request = {
            "schema_version": "2.0",
            "request_id": "test_run",
            "compounds": [
                {
                    "compound_id": "candidate_001",
                    "canonical_smiles": "CCO",
                    "atom_mapped_smiles": "[CH3:1][CH2:2][OH:3]",
                    "structure_id": "structure_001",
                    "standardization_version": "test_v1",
                },
                {"compound_id": "candidate_002", "canonical_smiles": ""},
            ],
        }
        target = {
            "target_id": "target_001",
            "pdb_id": "1ABC",
            "chain": "A",
            "preparation_version": "test_v1",
        }

        with tempfile.TemporaryDirectory() as directory:
            result = run_batch(request, target, "ATOM example", client, Path(directory))

        self.assertEqual(result["stream"], "discovery_evidence")
        self.assertEqual(result["results"][0]["compound_id"], "candidate_001")
        self.assertEqual(result["results"][0]["structure_id"], "structure_001")
        self.assertEqual(result["results"][0]["status"], "ok")
        self.assertEqual(
            result["results"][0]["provenance"]["service_endpoint"], client.endpoint
        )
        self.assertEqual(result["results"][1]["compound_id"], "candidate_002")
        self.assertEqual(result["results"][1]["status"], "invalid_input")

    def test_service_validation_failure_becomes_an_invalid_input_record(self):
        def fake_transport(endpoint, headers, payload):
            raise DiffDockError("DiffDock returned HTTP 422", kind="invalid_input")

        client = DiffDockNIMClient("example-key", transport=fake_transport)
        request = {
            "request_id": "test_invalid_smiles",
            "compounds": [
                {
                    "compound_id": "candidate_003",
                    "canonical_smiles": "not-a-smiles",
                    "atom_mapped_smiles": "[CH3:1]",
                    "structure_id": "structure_003",
                    "standardization_version": "test_v1",
                }
            ],
        }
        target = {
            "target_id": "target_001",
            "pdb_id": "1ABC",
            "chain": "A",
            "preparation_version": "test_v1",
        }

        with tempfile.TemporaryDirectory() as directory:
            result = run_batch(request, target, "ATOM example", client, Path(directory))

        self.assertEqual(result["results"][0]["status"], "invalid_input")
        self.assertEqual(result["results"][0]["error"]["type"], "invalid_input")


class TargetManifestTest(unittest.TestCase):
    def test_target_pdb_path_is_resolved_from_the_manifest_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "configs" / "targets"
            manifests.mkdir(parents=True)
            prepared = root / "prepared.pdb"
            prepared.write_text("ATOM example\n", encoding="utf-8")
            manifest = manifests / "target.json"
            manifest.write_text(
                json.dumps(
                    {
                        "target_id": "target_001",
                        "protein_name": "Example protein",
                        "species": "human",
                        "pdb_id": "1ABC",
                        "chain": "A",
                        "biological_action": "inhibit",
                        "reference_ligand": "reference_001",
                        "protein_pdb_path": "../../prepared.pdb",
                        "preparation_version": "test_v1",
                    }
                ),
                encoding="utf-8",
            )

            target, protein, checksum = _read_target(manifest)

        self.assertEqual(target["target_id"], "target_001")
        self.assertEqual(protein, "ATOM example\n")
        self.assertTrue(checksum.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
