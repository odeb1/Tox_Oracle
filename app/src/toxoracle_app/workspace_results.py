"""Read-only adapters for the unified current-run dashboard. No provider calls."""
import base64

from .molecular_evidence import molecule_svg, unique_features
from .screen_cli import ROOT, load


def candidate_evidence(report, compound_id, source=None, labels=False):
    row = next((r for r in report["results"] if r["compound_id"] == compound_id), None)
    if row is None:
        raise ValueError("unknown_candidate")
    evidence = row["toxicity_result"]["structural_evidence"]
    groups = unique_features(evidence["fragments"])
    selected = next((g for g in groups if g["source"] == source), None)
    if source is not None and selected is None:
        raise ValueError("unknown_feature")
    for group in groups:
        group["atom_map_ids"] = sorted(group["atom_map_ids"])
    smiles = evidence["atom_mapped_smiles"]
    image = None
    if smiles:
        svg = molecule_svg(smiles, selected["atom_map_ids"] if selected else [],
                           positive=(selected["contribution"] or 0) >= 0 if selected else True,
                           labels=labels is True)
        image = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    return dict(features=groups, image=image, selected=source,
                attribution_status=evidence["attribution_status"])


def model_context(report):
    evaluation = load(ROOT / "evaluation/reports/baseline_test.json")
    selection = load(ROOT / "evaluation/reports/baseline_selection.json")
    matching = all(r["toxicity_result"]["provenance"]["method_id"] == "toxoracle_dili_rf_v1"
                   and r["toxicity_result"]["provenance"]["data_version"] == evaluation["data_sha256"]
                   for r in report["results"])
    return dict(evaluation=evaluation, matching_method_and_data=matching,
                selection={k: selection[k] for k in ("fingerprint", "split_kind", "counts")})
