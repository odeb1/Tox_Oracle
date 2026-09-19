"""Validate shared identities and map poses without redefining standardisation.

No salt stripping, neutralisation or tautomer conversion occurs here. Symmetric
unmapped vendor poses are retained without arbitrarily assigning atom identities.
Contacts are distances in predicted poses, not inferred chemical bonds.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

from rdkit import Chem, rdBase

from .artifacts import artifact_key, write_json, write_text


IDENTITY_FIELDS = (
    "compound_id", "canonical_smiles", "atom_mapped_smiles",
    "structure_id", "standardization_version",
)


class StructureError(ValueError):
    def __init__(self, message: str, status: str = "invalid_input"):
        super().__init__(message)
        self.status = status


def molecule_key(molecule, keep_maps=False):
    copy = Chem.Mol(molecule)
    if not keep_maps:
        for atom in copy.GetAtoms():
            atom.SetAtomMapNum(0)
    return Chem.MolToSmiles(copy, canonical=True, isomericSmiles=True)


def parse_smiles(smiles):
    if not isinstance(smiles, str) or not smiles.strip():
        raise StructureError("SMILES must be a non-empty string")
    params = Chem.SmilesParserParams()
    params.removeHs = False
    params.parseName = False
    with rdBase.BlockLogs():
        molecule = Chem.MolFromSmiles(smiles, params)
    if molecule is None or not molecule.GetNumAtoms():
        raise StructureError("SMILES could not be parsed and sanitised")
    return molecule


def validate_compound(compound):
    if not isinstance(compound, dict):
        raise StructureError("compound must be a JSON object")
    missing = [field for field in IDENTITY_FIELDS if not isinstance(compound.get(field), str) or not compound[field].strip()]
    if missing:
        raise StructureError("missing required non-empty fields: " + ", ".join(missing))
    plain = parse_smiles(compound["canonical_smiles"])
    mapped = parse_smiles(compound["atom_mapped_smiles"])
    if molecule_key(plain) != molecule_key(mapped):
        raise StructureError("canonical_smiles and atom_mapped_smiles describe different structures or stereochemistry")
    maps = [atom.GetAtomMapNum() for atom in mapped.GetAtoms()]
    if any(number <= 0 for number in maps) or len(set(maps)) != len(maps):
        raise StructureError("Every shared atom must have a unique positive atom-map ID")
    if len(Chem.GetMolFrags(mapped)) != 1:
        raise StructureError("Multi-component inputs require a jointly standardised parent structure", "unsupported")
    if any(atom.GetAtomicNum() == 1 for atom in mapped.GetAtoms()):
        raise StructureError("Explicit hydrogen atoms in the shared graph are not supported by this pose mapper", "unsupported")
    return mapped


def validate_request(request):
    if request.get("schema_version") != "2.0":
        raise ValueError("schema_version must be 2.0")
    if not isinstance(request.get("request_id"), str) or not request["request_id"].strip():
        raise ValueError("request_id must be a non-empty string")
    if not isinstance(request.get("compounds"), list) or not request["compounds"]:
        raise ValueError("compounds must be a non-empty JSON array")
    # A duplicate batch cannot be joined unambiguously. Reject it before any API
    # call, including when the first occurrence of a duplicated ID is malformed.
    ids = [c.get("compound_id") for c in request["compounds"] if isinstance(c, dict) and isinstance(c.get("compound_id"), str)]
    if len(ids) != len(set(ids)):
        raise ValueError("compound_id must be unique within the batch")


def shared_graph_artifact(compound, molecule, directory):
    graph = {
        "structure_id": compound["structure_id"],
        "standardization_version": compound["standardization_version"],
        "atom_mapped_smiles": compound["atom_mapped_smiles"],
        "rdkit_version": rdBase.rdkitVersion,
        "atoms": [{"atom_map_id": a.GetAtomMapNum(), "element": a.GetSymbol(), "formal_charge": a.GetFormalCharge(), "isotope": a.GetIsotope()} for a in molecule.GetAtoms()],
        "bonds": [{"atom_map_ids": [b.GetBeginAtom().GetAtomMapNum(), b.GetEndAtom().GetAtomMapNum()], "bond_type": str(b.GetBondType()), "stereo": str(b.GetStereo())} for b in molecule.GetBonds()],
    }
    return write_json(directory, artifact_key(compound["compound_id"]) + "_atom_mapping.json", graph)


def map_pose(shared, pose):
    pose = Chem.RemoveHs(pose)
    if molecule_key(pose) != molecule_key(shared):
        raise StructureError("Vendor pose differs from the shared structure or stereochemistry")
    if not pose.GetNumConformers() or not pose.GetConformer().Is3D():
        raise StructureError("Vendor pose lacks a 3D conformer")
    if not all(math.isfinite(v) for row in pose.GetConformer().GetPositions() for v in row):
        raise StructureError("Vendor pose has non-finite coordinates")
    if molecule_key(pose, keep_maps=True) == molecule_key(shared, keep_maps=True):
        return pose, "preserved_vendor_atom_maps"
    # Enumerate two matches: the second is enough to establish ambiguity. Atom
    # order alone cannot identify symmetry-equivalent atoms across vendor output.
    matches = pose.GetSubstructMatches(shared, uniquify=False, useChirality=True, maxMatches=2)
    if len(matches) != 1:
        raise StructureError("Pose atom mapping is ambiguous; contacts and mapped pose are unavailable")
    for shared_index, pose_index in enumerate(matches[0]):
        pose.GetAtomWithIdx(pose_index).SetAtomMapNum(shared.GetAtomWithIdx(shared_index).GetAtomMapNum())
    return pose, "unique_stereochemical_graph_match"


def protein_atoms(protein, chain):
    atoms = []
    models = sum(line.startswith("MODEL ") for line in protein.splitlines())
    if models > 1:
        raise StructureError("Prepared protein must contain a single model")
    for line in protein.splitlines():
        if not line.startswith("ATOM  ") or line[21:22] != chain:
            continue
        if line[16:17] not in (" ", "A"):
            raise StructureError("Prepared protein contains unresolved alternate locations")
        element = line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]
        if element in ("H", "D"):
            continue
        try:
            coords = tuple(float(line[start:start + 8]) for start in (30, 38, 46))
            residue_number = int(line[22:26])
        except ValueError as error:
            raise StructureError("Invalid coordinates or residue number in prepared PDB") from error
        if not all(math.isfinite(v) for v in coords):
            raise StructureError("Non-finite coordinates in prepared PDB")
        atoms.append((coords, line[17:20].strip(), residue_number, line[26:27].strip()))
    if not atoms:
        raise StructureError("No protein heavy atoms for the selected chain")
    return atoms


def distance_contacts(pose, protein, target, artifact_ref, cutoff=4.0):
    if not math.isfinite(cutoff) or cutoff <= 0:
        raise ValueError("Contact cutoff must be finite and positive")
    receptor = protein_atoms(protein, target["chain"])
    result = []
    coordinates = pose.GetConformer()
    for atom in pose.GetAtoms():
        position = coordinates.GetAtomPosition(atom.GetIdx())
        minima = {}
        for other, name, number, insertion in receptor:
            squared = sum((a - b) ** 2 for a, b in zip(position, other))
            key = (name, number, insertion)
            if squared <= cutoff ** 2:
                minima[key] = min(minima.get(key, math.inf), math.sqrt(squared))
        for (name, number, insertion), distance in sorted(minima.items()):
            result.append({
                "atom_map_ids": [atom.GetAtomMapNum()],
                "target_id": target["target_id"],
                "target_role": target.get("target_role", "therapeutic_target"),
                "chain": target["chain"], "residue_name": name,
                "residue_number": number, "insertion_code": insertion,
                "interaction_type": "distance_contact", "distance_angstrom": round(distance, 4),
                "artifact_ref": artifact_ref,
            })
    return result


def export_poses(compound, shared, sdf, confidence, protein, target, directory, mapping_ref):
    supplier = Chem.ForwardSDMolSupplier(io.BytesIO(sdf.encode("utf-8")), removeHs=False)
    poses = list(supplier)
    if len(poses) != len(confidence):
        raise StructureError("Pose count differs from confidence count; pose-score association is unavailable")
    artifacts, interactions, warnings = [], [], []
    for rank, (pose, score) in enumerate(zip(poses, confidence), 1):
        try:
            if pose is None:
                raise StructureError("Vendor SDF could not be parsed")
            mapped, method = map_pose(shared, pose)
            name = artifact_key(compound["compound_id"]) + "_pose_{:03d}.sdf".format(rank)
            artifact = write_text(directory, name, Chem.MolToMolBlock(mapped) + "\n$$$$\n")
            artifact.update({
                "origin": "predicted", "atom_mapping_ref": mapping_ref,
                "mapping_method": method, "target_id": target["target_id"],
                "target_role": target.get("target_role", "therapeutic_target"),
                "conformer_id": "pose_{}".format(rank), "pose_confidence": score,
                "model_id": "nvidia_nim_diffdock",
            })
            artifacts.append(artifact)
            interactions.extend(distance_contacts(mapped, protein, target, artifact["artifact_id"]))
        except StructureError as error:
            warnings.append("Pose {}: {}".format(rank, error))
    return artifacts, interactions, warnings
