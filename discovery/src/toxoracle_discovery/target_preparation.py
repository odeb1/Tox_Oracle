"""Prepare explicit receptor selections and preserve shared candidate identities.

This performs coordinate selection only: no protonation, missing-atom repair,
minimisation, salt stripping, or stereoisomer assignment is implied.
"""

from collections import Counter
import csv
import math
from pathlib import Path
import re


def _select_atoms(lines, chain, altloc):
    selected, seen = [], set()
    for line in lines:
        if line[21:22] != chain or line[16:17] not in (" ", altloc):
            continue
        try:
            coordinates = [float(line[start:start + 8]) for start in (30, 38, 46)]
            int(line[22:26])
        except ValueError as error:
            raise ValueError("Invalid PDB coordinates or residue number") from error
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("Non-finite PDB coordinates")
        key = (line[22:27], line[12:16])
        if key in seen:
            raise ValueError("Duplicate atom after alternate-location selection")
        seen.add(key)
        # The selected conformation is now unambiguous; keep coordinates,
        # residue numbering, occupancies, and atom serials unchanged.
        selected.append(line[:16] + " " + line[17:])
    return selected


def prepare_pdb(source, chain, reference_component, reference_residue, altloc="A"):
    """Select one protein chain and save its reference ligand separately.

    All HETATM records are excluded from the receptor. This intentionally narrow
    protocol is for the proposed cofactor-free PPARgamma case; it must not be
    applied to metal/cofactor-dependent targets without an explicit new policy.
    """
    if len(chain) != 1 or not chain.strip() or len(altloc) != 1 or not altloc.strip():
        raise ValueError("chain and altloc must each be one non-blank PDB character")
    lines = source.splitlines()
    if sum(line.startswith("MODEL ") for line in lines) > 1:
        raise ValueError("Select a single PDB model before preparation")
    protein_lines = [line for line in lines if line.startswith("ATOM  ")]
    receptor = _select_atoms(protein_lines, chain, altloc)
    if not receptor:
        raise ValueError("No protein atoms found in the requested chain")
    # Fail if the requested alternate conformation would omit an entire atom.
    expected = {(line[22:27], line[12:16]) for line in protein_lines if line[21:22] == chain}
    actual = {(line[22:27], line[12:16]) for line in receptor}
    if expected != actual:
        raise ValueError("Selected alternate location would leave protein atoms missing")

    heterogens = [line for line in lines if line.startswith("HETATM")]
    reference = _select_atoms([
        line for line in heterogens
        if line[17:20].strip() == reference_component and line[22:27].strip() == str(reference_residue)
    ], chain, altloc)
    if not reference:
        raise ValueError("Reference ligand was not found at the specified chain/residue")
    serials = {int(line[6:11]) for line in reference}
    connections = []
    for line in lines:
        if line.startswith("CONECT"):
            numbers = [int(line[start:start + 5]) for start in range(6, len(line), 5) if line[start:start + 5].strip()]
            if numbers and all(number in serials for number in numbers):
                connections.append(line)

    heterogen_residues = {(line[17:20].strip(), line[21:27]) for line in heterogens}
    removed = Counter(name for name, _ in heterogen_residues)
    missing_residues = [line.rstrip() for line in lines if re.match(
        r"^REMARK 465\s+(?:\d+\s+)?[A-Z]{3}\s+" + re.escape(chain) + r"\s+-?\d+", line
    )]
    missing_atoms = [line.rstrip() for line in lines if re.match(
        r"^REMARK 470\s+(?:\d+\s+)?[A-Z]{3}\s+" + re.escape(chain) + r"\s*-?\d+", line
    )]
    report = {
        "chain": chain,
        "alternate_location": altloc,
        "protein_atom_count": len(receptor),
        "protein_residue_count": len({line[22:27] for line in receptor}),
        "discarded_alternate_atom_count": sum(line[21:22] == chain for line in protein_lines) - len(receptor),
        "reference_atom_count": len(reference),
        "removed_heterogen_residue_counts": dict(sorted(removed.items())),
        "missing_residue_records": missing_residues,
        "missing_atom_records": missing_atoms,
        "coordinates_changed": False,
        "repairs_applied": [],
        "protonation_assignment": "not_performed",
        "minimisation": "not_performed",
    }
    return "\n".join(receptor + ["TER", "END"]) + "\n", "\n".join(reference + connections + ["END"]) + "\n", report


def add_atom_maps(compound):
    """Add maps without changing any of the caller's existing identity fields."""
    from rdkit import Chem
    from .structures import parse_smiles, validate_compound

    molecule = parse_smiles(compound["canonical_smiles"])
    for index, atom in enumerate(molecule.GetAtoms(), 1):
        atom.SetAtomMapNum(index)
    result = dict(compound)
    result["atom_mapped_smiles"] = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    validate_compound(result)
    unresolved = [index + 1 for index, label in Chem.FindMolChiralCenters(
        molecule, includeUnassigned=True, useLegacyImplementation=False
    ) if label == "?"]
    return result, unresolved


def candidate_request(table, compound_ids, request_id):
    """Select curated IDs; do not copy DILI labels into inference inputs."""
    if not compound_ids or len(compound_ids) != len(set(compound_ids)):
        raise ValueError("Candidate IDs must be non-empty and unique")
    rows = {}
    with Path(table).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            identifier = row.get("compound_id")
            if identifier in compound_ids:
                if identifier in rows:
                    raise ValueError("Multiple source rows found for candidate " + identifier)
                rows[identifier] = row
    missing = set(compound_ids) - set(rows)
    if missing:
        raise ValueError("Candidates missing from the source table: " + ", ".join(sorted(missing)))
    compounds, metadata = [], []
    for identifier in compound_ids:
        row = rows[identifier]
        identity = {key: row[key] for key in (
            "compound_id", "canonical_smiles", "structure_id", "standardization_version"
        )}
        compound, unresolved = add_atom_maps(identity)
        compounds.append(compound)
        metadata.append({
            "compound_id": identifier,
            "source_name": row["compound_name"],
            "structure_source": row["structure_source"],
            "source_pubchem_cid": row["pubchem_cid"],
            "unspecified_stereocenter_atom_map_ids": unresolved,
            "stereochemistry_policy": "Preserve the shared unspecified stereochemistry; do not invent an isomer",
            "evaluation_membership": "retrospective_illustration; present in model-ready source data; training split unknown",
        })
    return {"schema_version": "2.0", "request_id": request_id, "compounds": compounds}, metadata
