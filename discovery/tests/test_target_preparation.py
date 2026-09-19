import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toxoracle_discovery.target_preparation import candidate_request, prepare_pdb


def atom(serial, name="CA", residue="ALA", chain="A", number=1, altloc=" ", x=1.0, record="ATOM"):
    return (
        f"{record:<6}{serial:5d} {name:^4}{altloc}{residue:>3} {chain}{number:4d}    "
        f"{x:8.3f}{2.0:8.3f}{3.0:8.3f}{0.5:6.2f}{20.0:6.2f}          C  "
    )


class ReceptorPreparationTest(unittest.TestCase):
    def setUp(self):
        self.lines = [
            atom(1, name="N"),
            atom(2, altloc="A"),
            atom(3, altloc="B", x=8.0),
            atom(4, chain="B"),
            atom(5, name="C1", residue="BRL", number=501, record="HETATM"),
            atom(6, name="O", residue="HOH", number=502, record="HETATM"),
            "REMARK 465     PHE A   264",
            "REMARK 470     LEU A 270    CG   CD1  CD2",
        ]

    def test_selects_chain_and_altloc_preserving_coordinates_and_experimental_reference(self):
        receptor, reference, report = prepare_pdb("\n".join(self.lines), "A", "BRL", "501")
        atoms = [line for line in receptor.splitlines() if line.startswith("ATOM")]
        self.assertEqual(len(atoms), 2)
        self.assertEqual(atoms[1][30:54], self.lines[1][30:54])
        self.assertEqual(atoms[1][16], " ")
        self.assertNotIn("HETATM", receptor)
        self.assertIn(self.lines[4], reference)
        self.assertNotIn("HOH", reference)
        self.assertEqual(report["discarded_alternate_atom_count"], 1)
        self.assertEqual(report["removed_heterogen_residue_counts"], {"BRL": 1, "HOH": 1})
        self.assertEqual(report["missing_residue_records"], [self.lines[6]])
        self.assertEqual(report["missing_atom_records"], [self.lines[7]])

    def test_rejects_absent_chain_or_reference_and_multiple_models(self):
        for source, chain, residue in [
            ("\n".join(self.lines), "Z", "501"),
            ("\n".join(self.lines), "A", "999"),
            ("MODEL        1\nMODEL        2\n" + "\n".join(self.lines), "A", "501"),
        ]:
            with self.subTest(chain=chain, residue=residue):
                with self.assertRaises(ValueError):
                    prepare_pdb(source, chain, "BRL", residue)

    def test_rejects_duplicate_or_nonfinite_coordinates(self):
        for extra in [atom(10, name="N"), atom(10, name="CB", x=float("nan"))]:
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    prepare_pdb("\n".join(self.lines + [extra]), "A", "BRL", "501")

    def test_does_not_silently_drop_atoms_available_only_in_another_altloc(self):
        with self.assertRaisesRegex(ValueError, "leave protein atoms missing"):
            prepare_pdb("\n".join(self.lines + [atom(10, name="CB", altloc="B")]), "A", "BRL", "501")


@unittest.skipUnless(importlib.util.find_spec("rdkit"), "RDKit required for candidate identity checks")
class CandidatePreparationTest(unittest.TestCase):
    def write_table(self, directory, rows):
        path = Path(directory) / "candidates.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def row(self, identifier="source_1"):
        return {
            "compound_id": identifier, "compound_name": "Example",
            "canonical_smiles": "CC(O)F", "structure_id": "unchanged_source_identity",
            "standardization_version": "source_policy_v1", "structure_source": "https://example.org/source",
            "pubchem_cid": "123", "dili_label": "1",
        }

    def test_preserves_shared_identity_maps_all_atoms_and_excludes_outcome_labels(self):
        from rdkit import Chem
        with tempfile.TemporaryDirectory() as directory:
            row = self.row()
            request, metadata = candidate_request(self.write_table(directory, [row]), [row["compound_id"]], "test")
        compound = request["compounds"][0]
        for field in ("compound_id", "canonical_smiles", "structure_id", "standardization_version"):
            self.assertEqual(compound[field], row[field])
        self.assertNotIn("dili_label", compound)
        molecule = Chem.MolFromSmiles(compound["atom_mapped_smiles"])
        self.assertEqual(sorted(atom.GetAtomMapNum() for atom in molecule.GetAtoms()), [1, 2, 3, 4])
        self.assertEqual(metadata[0]["unspecified_stereocenter_atom_map_ids"], [2])

    def test_rejects_missing_and_duplicate_candidate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_table(directory, [self.row()])
            for identifiers in (["absent"], ["source_1", "source_1"], []):
                with self.subTest(identifiers=identifiers):
                    with self.assertRaises(ValueError):
                        candidate_request(path, identifiers, "test")
            duplicate_path = self.write_table(directory, [self.row(), self.row()])
            with self.assertRaisesRegex(ValueError, "Multiple source rows"):
                candidate_request(duplicate_path, ["source_1"], "test")

    def test_unsupported_structures_keep_their_status_without_spending_a_service_call(self):
        from toxoracle_discovery.cli import run_batch
        from toxoracle_discovery.diffdock import DiffDockNIMClient

        def unexpected_call(*args):
            self.fail("Unsupported input must be rejected before calling NVIDIA")

        request = {"request_id": "unsupported", "compounds": [{
            "compound_id": "mixture", "canonical_smiles": "C.C",
            "atom_mapped_smiles": "[CH4:1].[CH4:2]", "structure_id": "mixture_id",
            "standardization_version": "test_v1",
        }]}
        target = {"target_id": "test", "pdb_id": "7AWC", "chain": "A", "preparation_version": "test_v1"}
        with tempfile.TemporaryDirectory() as directory:
            result = run_batch(request, target, "ATOM example", DiffDockNIMClient("fake", transport=unexpected_call), Path(directory))
        self.assertEqual(result["results"][0]["status"], "unsupported")
        self.assertEqual(result["results"][0]["error"]["type"], "unsupported")

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "Install tests/integration/requirements.txt for schema checks")
    def test_prepared_demo_requests_match_schema_and_original_dataset_identities(self):
        import jsonschema
        from rdkit import Chem
        from toxoracle_discovery.structures import validate_compound, validate_request

        root = Path(__file__).resolve().parents[2]
        config = root / "discovery/configs/targets/pparg-7awc"
        schema = json.loads((root / "contracts/request.schema.json").read_text())
        with (root / "data/processed/dilirank2_model_ready.csv").open(newline="") as handle:
            original = {row["compound_id"]: row for row in csv.DictReader(handle)}
        for filename in ("candidates.v2.json", "reference-control.v2.json"):
            request = json.loads((config / filename).read_text())
            jsonschema.Draft202012Validator(schema).validate(request)
            validate_request(request)
            for compound in request["compounds"]:
                validate_compound(compound)
                if filename == "candidates.v2.json":
                    for field in ("compound_id", "canonical_smiles", "structure_id", "standardization_version"):
                        self.assertEqual(compound[field], original[compound["compound_id"]][field])
                else:
                    stereo = Chem.FindMolChiralCenters(Chem.MolFromSmiles(compound["canonical_smiles"]))
                    self.assertEqual([label for _, label in stereo], ["S"])
        self.assertEqual(json.loads((config / "target.proposed.json").read_text())["selection_status"], "proposed")


if __name__ == "__main__":
    unittest.main()
