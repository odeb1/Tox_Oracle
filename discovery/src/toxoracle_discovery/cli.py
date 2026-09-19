"""Batch command for the Team A DiffDock adapter.

This command intentionally produces discovery evidence, not a fabricated
conventional-toxicity assessment.  Team A must select and configure that
comparator before this output is wrapped in the shared assessment envelope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from .diffdock import DiffDockError, DiffDockNIMClient, DiffDockRequest, DockingEvidence


REQUIRED_COMPOUND_FIELDS = (
    "compound_id",
    "canonical_smiles",
    "atom_mapped_smiles",
    "structure_id",
    "standardization_version",
)
REQUIRED_TARGET_FIELDS = (
    "target_id",
    "protein_name",
    "species",
    "pdb_id",
    "chain",
    "biological_action",
    "reference_ligand",
    "protein_pdb_path",
    "preparation_version",
)


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Could not read {}: {}".format(path, error)) from error
    if not isinstance(value, dict):
        raise ValueError("{} must contain one JSON object".format(path))
    return value


def _read_target(path: Path) -> Tuple[Mapping[str, Any], str, str]:
    target = _load_json(path)
    absent = [field for field in REQUIRED_TARGET_FIELDS if not isinstance(target.get(field), str) or not target[field].strip()]
    if absent:
        raise ValueError("Target manifest is missing required non-empty fields: {}".format(", ".join(absent)))
    protein_path = Path(str(target["protein_pdb_path"]))
    if not protein_path.is_absolute():
        protein_path = path.parent / protein_path
    try:
        protein = protein_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("Could not read target PDB {}: {}".format(protein_path, error)) from error
    checksum = hashlib.sha256(protein.encode("utf-8")).hexdigest()
    configured_checksum = target.get("protein_pdb_sha256")
    if configured_checksum and configured_checksum != "sha256:" + checksum:
        raise ValueError("Target PDB checksum does not match protein_pdb_sha256 in the manifest")
    return target, protein, "sha256:" + checksum


def _compound_error(compound: Any, message: str) -> Dict[str, Any]:
    compound_id = compound.get("compound_id") if isinstance(compound, dict) else None
    return {
        "compound_id": compound_id,
        "status": "invalid_input",
        "supplementary_metrics": [],
        "structural_evidence": {"structure_artifacts": [], "interactions": []},
        "provenance": {"method_id": "nvidia_nim_diffdock"},
        "warnings": ["No discovery conclusion can be made for invalid input."],
        "error": {"type": "invalid_input", "message": message},
    }


def _validate_compound(compound: Any, seen_ids: set) -> Tuple[bool, str]:
    if not isinstance(compound, dict):
        return False, "compound must be a JSON object"
    absent = [
        field
        for field in REQUIRED_COMPOUND_FIELDS
        if not isinstance(compound.get(field), str) or not compound[field].strip()
    ]
    if absent:
        return False, "missing required non-empty fields: {}".format(", ".join(absent))
    compound_id = compound["compound_id"]
    if compound_id in seen_ids:
        return False, "compound_id must be unique within the batch"
    seen_ids.add(compound_id)
    return True, ""


def run_batch(
    request: Mapping[str, Any],
    target: Mapping[str, Any],
    protein: str,
    client: DiffDockNIMClient,
    artifact_directory: Path,
) -> Dict[str, Any]:
    # RDKit is only required for structure identity validation. Keep the
    # transport and offline adapter usable in minimal environments where the
    # optional chemistry dependency is not installed.
    try:
        from .structures import shared_graph_artifact, validate_compound
    except ImportError:
        # Minimal/offline installations can still exercise the HTTP adapter;
        # the chemistry validation layer will be enabled when RDKit is present.
        shared_graph_artifact = validate_compound = None
    compounds = request.get("compounds")
    if not isinstance(compounds, list):
        raise ValueError("request compounds must be a JSON array")
    if not isinstance(request.get("request_id"), str) or not request["request_id"].strip():
        raise ValueError("request_id must be a non-empty string")

    results: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for compound in compounds:
        is_valid, problem = _validate_compound(compound, seen_ids)
        if not is_valid:
            results.append(_compound_error(compound, problem))
            continue
        assert isinstance(compound, dict)
        graph_artifact = None
        try:
            # Validate the shared molecular identity before sending a request to
            # DiffDock. This prevents vendor output from becoming the implicit
            # source of truth for atom identity and avoids spending GPU calls on
            # malformed or mismatched structures.
            if validate_compound is not None:
                molecule = validate_compound(compound)
                graph_artifact = shared_graph_artifact(compound, molecule, artifact_directory / compound["compound_id"])
            response = client.dock(
                DiffDockRequest(protein=protein, ligand=compound["canonical_smiles"], ligand_file_type="smiles")
            )
            evidence = DockingEvidence.from_response(
                compound["compound_id"], response, artifact_directory / compound["compound_id"]
            )
        except DiffDockError as error:
            status = "invalid_input" if error.kind == "invalid_input" else "failed"
            evidence = DockingEvidence.failed(
                compound["compound_id"], str(error), status=status, error_type=error.kind
            )
        except ValueError as error:
            evidence = DockingEvidence.failed(compound["compound_id"], str(error))
        record = evidence.to_dict()
        # The graph is an input-derived artifact and remains available even
        # when the remote call fails after validation.
        if graph_artifact is not None and evidence.status == "ok":
            record["structural_evidence"]["structure_artifacts"].insert(0, graph_artifact)
        elif graph_artifact is not None:
            record.setdefault("structural_evidence", {}).setdefault("structure_artifacts", []).insert(0, graph_artifact)
        record["structure_id"] = compound["structure_id"]
        record["provenance"]["service_endpoint"] = client.endpoint
        record["provenance"]["service_request"] = {
            "ligand_file_type": "smiles",
            "num_poses": 10,
            "time_divisions": 20,
            "steps": 18,
            "save_trajectory": False,
            "skip_gen_conformer": False,
            "is_staged": False,
        }
        record["target"] = {
            "target_id": target["target_id"],
            "pdb_id": target["pdb_id"],
            "chain": target["chain"],
        }
        results.append(record)

    return {
        "schema_version": request.get("schema_version", "2.0"),
        "request_id": request["request_id"],
        "stream": "discovery_evidence",
        "target": {
            "target_id": target["target_id"],
            "pdb_id": target["pdb_id"],
            "chain": target["chain"],
            "preparation_version": target["preparation_version"],
        },
        "results": results,
        "warnings": [
            "This is discovery evidence only. It is not the Team A conventional-toxicity "
            "assessment envelope until a comparator is selected and connected."
        ],
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Team A DiffDock discovery evidence")
    parser.add_argument("--request", required=True, type=Path, help="v2 compound request JSON")
    parser.add_argument("--target", required=True, type=Path, help="prepared target manifest JSON")
    parser.add_argument("--output", required=True, type=Path, help="output evidence JSON")
    parser.add_argument(
        "--artifact-directory",
        type=Path,
        default=Path("artifacts/runs/diffdock"),
        help="ignored directory for raw pose artifacts",
    )
    args = parser.parse_args(argv)

    try:
        request = _load_json(args.request)
        target, protein, checksum = _read_target(args.target)
        client = DiffDockNIMClient.from_environment()
        result = run_batch(request, target, protein, client, args.artifact_directory)
        result["target"]["protein_pdb_sha256"] = checksum
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (DiffDockError, ValueError, OSError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
