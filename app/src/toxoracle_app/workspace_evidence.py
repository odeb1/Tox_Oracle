"""Local molecule previews and an integrity-checked recorded public study."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path

from .screen_cli import ROOT, load
from .screening import validate_discovery, validate_screening_report

REPLAY = ROOT / "demo/examples/abl1_recorded_workspace"


def molecule(smiles):
    from rdkit import Chem, rdBase
    from rdkit.Chem.Draw import rdMolDraw2D
    if not isinstance(smiles, str) or len(smiles) > 6000:
        raise ValueError("invalid_structure")
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
    if mol is None or not 1 <= mol.GetNumAtoms() <= 250:
        raise ValueError("invalid_structure")
    for atom in mol.GetAtoms(): atom.SetAtomMapNum(0)
    drawer = rdMolDraw2D.MolDraw2DSVG(360, 200)
    drawer.drawOptions().clearBackground = False
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    drawer.FinishDrawing()
    return "data:image/svg+xml;base64," + base64.b64encode(drawer.GetDrawingText().encode()).decode()


def preview(value):
    compounds = value.get("compounds") if isinstance(value, dict) else value
    if not isinstance(compounds, list) or not 2 <= len(compounds) <= 32:
        raise ValueError("candidate_count_invalid")
    rows, seen = [], set()
    for index, c in enumerate(compounds):
        cid = c.get("compound_id") if isinstance(c, dict) else None
        row = dict(row=index+1, compound_id=cid if isinstance(cid, str) and len(cid) <= 128 else "Missing ID")
        try:
            if not isinstance(cid, str) or not cid.strip() or len(cid) > 128:
                raise ValueError("missing_id")
            if cid in seen: raise ValueError("duplicate_id")
            seen.add(cid)
            row.update(image=molecule(c.get("canonical_smiles", c.get("smiles"))), status="valid")
        except (ValueError, TypeError):
            row.update(status="invalid", error="Check the ID and SMILES; IDs must be unique.")
        rows.append(row)
    return rows


def recorded_study(directory=REPLAY):
    manifest = load(directory / "evidence-manifest.json")
    data = {}
    for name in ("request.json", "discovery.json", "report.json"):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["sha256"][name]:
            raise ValueError("recorded_evidence_changed")
        data[name] = json.loads(raw)
    request, discovery, report = data["request.json"], data["discovery.json"], data["report.json"]
    validate_discovery(request, discovery)
    validate_screening_report(report)
    if (report["target"] != discovery["target"] or report["request_id"] != request["request_id"]
        or [r["discovery_result"] for r in report["results"]] != discovery["results"]):
        raise ValueError("recorded_evidence_mismatch")
    return dict(manifest=manifest, report=report, discovery=discovery,
                candidates=preview(request), mode="recorded", network_calls=False)
