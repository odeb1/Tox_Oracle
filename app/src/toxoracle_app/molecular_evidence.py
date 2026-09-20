"""Shared local molecule and attribution rendering for both dashboards."""
from __future__ import annotations
from typing import Any

def unique_features(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One bar per feature, retaining every environment for ambiguous hashed bits."""
    groups: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        source = fragment["source_ref"]
        if source not in groups:
            groups[source] = {"source": source, "contribution": fragment["contribution"],
                              "fragments": [], "atom_map_ids": set(), "ambiguous": False}
        group = groups[source]
        group["fragments"].append(fragment["fragment_id"])
        group["atom_map_ids"].update(fragment["atom_map_ids"])
        group["ambiguous"] |= fragment["mapping_ambiguous"]
        # Inconsistent supplied contributions cannot be presented as one feature score.
        if group["contribution"] != fragment["contribution"]:
            group["contribution"] = None
    return sorted(groups.values(), key=lambda g: abs(g["contribution"] or 0), reverse=True)


def molecule_svg(mapped_smiles: str, atom_ids: list[int] | None = None,
                 *, positive: bool = True, labels: bool = False) -> str:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(mapped_smiles)
    if mol is None:
        raise ValueError("The supplied molecular structure cannot be drawn.")
    requested = set(atom_ids or [])
    available = {a.GetAtomMapNum() for a in mol.GetAtoms()}
    if not requested.issubset(available):
        raise ValueError("The selected evidence references atom maps absent from this molecule.")
    indices = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomMapNum() in requested]
    for atom in mol.GetAtoms():
        if labels:
            atom.SetProp("atomNote", str(atom.GetAtomMapNum()))
        atom.SetAtomMapNum(0)
    drawer = rdMolDraw2D.MolDraw2DSVG(760, 380)
    options = drawer.drawOptions()
    options.clearBackground = False
    options.padding = .12
    options.bondLineWidth = 2
    options.addStereoAnnotation = True
    color = (.93, .68, .60) if positive else (.64, .76, .90)
    bonds = [b.GetIdx() for b in mol.GetBonds()
             if b.GetBeginAtomIdx() in indices and b.GetEndAtomIdx() in indices]
    rdMolDraw2D.PrepareAndDrawMolecule(
        drawer, mol, highlightAtoms=indices, highlightBonds=bonds,
        highlightAtomColors={i: color for i in indices},
        highlightBondColors={i: color for i in bonds},
    )
    drawer.FinishDrawing()
    return drawer.GetDrawingText()
