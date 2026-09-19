"""Prepare a proposed PPARgamma demo from a pinned public structure and local data.

Run with RDKit installed; see docs/runbooks/team-a-target-preparation.md.
This command prepares reviewable files and does not freeze the team's selection.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "discovery" / "src"))

from toxoracle_discovery.target_preparation import add_atom_maps, candidate_request, prepare_pdb


PDB_SOURCE = "https://files.rcsb.org/download/7AWC.pdb"
PDB_SHA256 = "f1678df596916a7da38842bd50002fbf61fc38a36e8adf43006940cb944f6b1f"
CANDIDATE_IDS = ["LT00140", "LT00134", "LT00168"]
BRL_SOURCE = "https://www.rcsb.org/ligand/BRL"
# CCD BRL specifies the S enantiomer. It is a separate structural control,
# not a replacement for the shared, stereo-unspecified rosiglitazone parent.
BRL_SMILES = "CN(CCOc1ccc(C[C@@H]2SC(=O)NC2=O)cc1)c3ccccn3"


def checksum(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pdb", type=Path, required=True)
    parser.add_argument("--candidate-table", type=Path, default=ROOT / "data/processed/dilirank2_model_ready.csv")
    parser.add_argument("--artifact-directory", type=Path, required=True)
    parser.add_argument("--config-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        from rdkit import Chem, rdBase

        if checksum(args.source_pdb) != "sha256:" + PDB_SHA256:
            raise ValueError("7AWC source checksum differs from the reviewed snapshot")
        if args.artifact_directory.exists() or args.config_directory.exists():
            raise ValueError("Use new artifact and config directories to preserve prior preparations")
        protein, reference, report = prepare_pdb(args.source_pdb.read_text(), "A", "BRL", "501")
        request, candidates = candidate_request(args.candidate_table, CANDIDATE_IDS, "pparg_7awc_candidates_v1")
        reference_smiles = Chem.MolToSmiles(Chem.MolFromSmiles(BRL_SMILES), isomericSmiles=True)
        control, unresolved = add_atom_maps({
            "compound_id": "RCSB_7AWC_BRL_A501",
            "canonical_smiles": reference_smiles,
            "structure_id": hashlib.sha256(reference_smiles.encode()).hexdigest(),
            "standardization_version": "rcsb_ccd_brl_v1",
        })
        if unresolved or Chem.MolFromSmiles(reference_smiles).GetNumHeavyAtoms() != report["reference_atom_count"]:
            raise ValueError("The structural reference must be stereo-specified and match the deposited atom count")

        args.artifact_directory.mkdir(parents=True)
        args.config_directory.mkdir(parents=True)
        receptor_path = args.artifact_directory / "7AWC_chain_A_prepared.pdb"
        reference_path = args.artifact_directory / "7AWC_BRL_A501_experimental.pdb"
        report_path = args.artifact_directory / "preparation-report.json"
        receptor_path.write_text(protein, encoding="utf-8")
        reference_path.write_text(reference, encoding="utf-8")
        report["prepared_at"] = datetime.now(timezone.utc).isoformat()
        report["rdkit_version"] = rdBase.rdkitVersion
        write_json(report_path, report)

        def relative(path):
            return os.path.relpath(path.resolve(), args.config_directory.resolve())

        manifest = {
            "selection_status": "proposed",
            "target_id": "human_pparg_7awc_A",
            "target_role": "therapeutic_target",
            "protein_name": "Peroxisome proliferator-activated receptor gamma ligand-binding domain",
            "species": "Homo sapiens",
            "uniprot_id": "P37231",
            "pdb_id": "7AWC",
            "chain": "A",
            "biological_action": "PPARgamma agonism; docking assesses pose plausibility only",
            "reference_ligand": "BRL (S-rosiglitazone), author chain A residue 501",
            "protein_pdb_path": relative(receptor_path),
            "protein_pdb_sha256": checksum(receptor_path),
            "preparation_version": "pparg_7awc_chain_a_altloc_a_v1",
            "cofactors_retained": [],
            "components_removed": [
                {"component_id": name, "residue_count": count}
                for name, count in report["removed_heterogen_residue_counts"].items()
            ],
            "preparation_notes": (
                "Select chain A ATOM records, retain blank/A alternate locations, clear the selected altloc flag, "
                "and preserve coordinates and residue numbering. Separate bound BRL as an experimental reference; "
                "remove GOL and HOH. No protonation, atom/loop repair, or minimisation. "
                "Missing residues A264-A269 and LEU A270 side-chain atoms remain unresolved."
            ),
            "source": {"url": PDB_SOURCE, "path": relative(args.source_pdb), "checksum": checksum(args.source_pdb)},
            "preparation_report": {"path": relative(report_path), "checksum": checksum(report_path)},
            "experimental_reference": {"path": relative(reference_path), "checksum": checksum(reference_path)},
            "candidate_request_path": "candidates.v2.json",
            "reference_control_request_path": "reference-control.v2.json",
            "selection_record_path": "selection.proposed.json",
        }
        selection = {
            "status": "proposed",
            "scientific_review": "pending_team_and_biologist_selection",
            "target_id": manifest["target_id"],
            "source_refs": ["https://www.rcsb.org/structure/7AWC", BRL_SOURCE, "https://pubmed.ncbi.nlm.nih.gov/31611383/"],
            "candidate_table": {"path": relative(args.candidate_table), "checksum": checksum(args.candidate_table)},
            "atom_mapping_policy": "One-based atom order from parsing each unchanged shared canonical_smiles; RDKit " + rdBase.rdkitVersion,
            "candidates": candidates,
            "reference_control": {
                "compound_id": control["compound_id"],
                "role": "experimental_binding_reference_for_redocking",
                "source_ref": BRL_SOURCE,
                "note": "S enantiomer; intentionally distinct from the stereo-unspecified LT00140 parent",
            },
            "negative_binding_control": {"status": "not_selected", "reason": "No source-validated non-binder nominated"},
            "discovery_priority_policy": "unranked; compare pose plausibility and reference recovery, not cross-compound confidence as affinity",
            "decisions_remaining": [
                "Confirm therapeutic target, chain, reference, candidate IDs, and control selection",
                "Review missing residues/atoms and protonation/water/cofactor preparation choices",
                "Agree handling of unspecified candidate stereochemistry before target-specific docking",
            ],
        }
        write_json(args.config_directory / "target.proposed.json", manifest)
        write_json(args.config_directory / "candidates.v2.json", request)
        write_json(args.config_directory / "reference-control.v2.json", {
            "schema_version": "2.0", "request_id": "pparg_7awc_reference_v1", "compounds": [control],
        })
        write_json(args.config_directory / "selection.proposed.json", selection)
        print(json.dumps({"status": "prepared_proposal", "config_directory": str(args.config_directory), "candidate_count": len(candidates), "reference_control_count": 1}))
        return 0
    except ImportError:
        print("error: RDKit is required; run this command in the project chemistry environment", file=sys.stderr)
    except (OSError, ValueError, KeyError) as error:
        print("error: " + str(error), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
