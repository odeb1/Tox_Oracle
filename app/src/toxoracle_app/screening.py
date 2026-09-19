"""Discovery + DILI v3 reporting, separate from the legacy toxicity comparison."""
from __future__ import annotations

from copy import deepcopy
import html
import json
import math

from .validation import (DEFAULT_CONTRACTS_DIR, ContractValidationError, _validate_schema,
                         validate_request, validate_response_against_request)

POLICY = "discovery_dili_triage_v1"
LIMITATIONS = [
    "Retrospective workflow demonstration; training and validation membership must be disclosed.",
    "Provisional screening and triage rules; binding predictions do not establish therapeutic efficacy.",
    "DILI estimates drug-level liver concern, not dose-specific exposure outcomes or freedom from harm.",
    "Nearest-training Tanimoto similarity is an applicability indicator, not confidence; no validated cutoff is applied.",
    "No conventional/preclinical toxicity comparator was supplied; no toxicity disagreement score is computed.",
]


def validate_discovery(request, discovery):
    validate_request(request)
    _validate_schema(discovery, DEFAULT_CONTRACTS_DIR / "discovery-v3.schema.json", "discovery v3")
    if discovery["request_id"] != request["request_id"]:
        raise ContractValidationError(["discovery request_id mismatch"])
    wanted = {r["compound_id"]: r for r in request["compounds"]}
    returned = discovery["results"]
    ids = [r["compound_id"] for r in returned]
    if len(ids) != len(set(ids)) or set(ids) != set(wanted):
        raise ContractValidationError(["discovery candidate coverage mismatch or duplicate IDs"])
    for row in returned:
        if any(row[k] != v for k, v in wanted[row["compound_id"]].items()):
            raise ContractValidationError(["discovery molecular identity mismatch"])
        values = row["binding_probability"]
        mean = sum(values)/len(values) if values else None
        if row["mean_binding_probability"] != mean:
            raise ContractValidationError(["binding summary does not match its source array"])
        if row["status"] == "ok" and (not row["structures"] or row["error"] is not None):
            raise ContractValidationError(["successful discovery must contain a structure and no error"])
        if row["status"] != "ok" and row["error"] is None:
            raise ContractValidationError(["failed discovery requires an error"])
    ranked = sorted((r for r in returned if r["status"] == "ok" and r["mean_binding_probability"] is not None),
                    key=lambda r: (-r["mean_binding_probability"], r["compound_id"]))
    ranks = {r["compound_id"]: i for i, r in enumerate(ranked, 1)}
    for row in returned:
        rank = ranks.get(row["compound_id"])
        if row["rank"] != rank or row["shortlisted"] != (rank is not None and rank <= 2):
            raise ContractValidationError(["discovery ranking violates the frozen top-two policy"])


def decision(discovery, toxicity):
    if discovery["status"] != "ok" or discovery["rank"] is None:
        return "discovery_incomplete", "Resolve the missing discovery evidence before selecting this candidate.", None
    if not discovery["shortlisted"]:
        return "not_shortlisted", "Retain discovery rank; review the DILI assessment alongside the other evidence.", None
    if toxicity["status"] != "ok" or toxicity["assessment"]["call"] == "unavailable":
        return "safety_assessment_incomplete", "Complete or review the DILI assessment before advancing the shortlist.", None
    if toxicity["assessment"]["call"] == "positive":
        return "hold_for_liver_validation", "Hold for targeted liver-safety validation; this is a provisional risk flag.", {
            "question": "Does this candidate produce concentration-dependent liver injury in a human-relevant system?",
            "assay": "Human-relevant hepatocyte concentration-response study",
            "readouts": ["Cell viability", "Liver-injury readouts"],
            "conditions": "Concentrations, duration, controls and replicates require experimental design; not inferred from DILI probability.",
        }
    return "continue_target_validation", "Continue target-binding validation alongside routine liver-safety testing; lower predicted concern is not evidence of safety.", {
        "question": "Is predicted ABL1 binding experimentally reproducible, and what liver-safety liabilities remain?",
        "assay": "ABL1 binding validation alongside routine liver-safety testing",
        "readouts": ["Target binding", "Liver-safety readouts"],
        "conditions": "Define assay-specific concentrations, controls and replicates before testing.",
    }


def combine_screening(request, discovery, toxicity):
    validate_discovery(request, discovery)
    validate_response_against_request(request, toxicity, expected_stream="toxicity")
    by_d = {r["compound_id"]: r for r in discovery["results"]}
    by_t = {r["compound_id"]: r for r in toxicity["results"]}
    results = []
    for compound in request["compounds"]:
        cid = compound["compound_id"]
        d, t = by_d[cid], by_t[cid]
        state, recommendation, experiment = decision(d, t)
        results.append(dict(compound, discovery_result=deepcopy(d), toxicity_result=deepcopy(t),
                            follow_up={"decision": state, "recommendation": recommendation,
                                       "experiment": experiment, "policy_status": "provisional"}))
    report = dict(schema_version="3.0", request_id=request["request_id"], target=discovery["target"],
                  policy_version=POLICY, policy_status="provisional", results=results,
                  discovery_shortlist=[r["compound_id"] for r in sorted(discovery["results"], key=lambda r: r["rank"] or math.inf) if r["shortlisted"]],
                  comparison={"status": "unavailable", "reason": "No preclinical/conventional toxicity comparator supplied", "disagreement": None},
                  limitations=list(LIMITATIONS))
    validate_screening_report(report)
    return report


def validate_screening_report(report):
    _validate_schema(report, DEFAULT_CONTRACTS_DIR / "screening-report-v3.schema.json", "screening report v3")
    identity_keys = ("compound_id", "structure_id", "canonical_smiles", "atom_mapped_smiles", "standardization_version")
    request = dict(schema_version="2.0", request_id=report["request_id"],
                   compounds=[{k: r[k] for k in identity_keys} for r in report["results"]])
    d = dict(schema_version="3.0", stream="discovery", request_id=report["request_id"],
             target=report["target"], ranking_rule="mean_binder_desc_top2_v1",
             results=[r["discovery_result"] for r in report["results"]])
    t = dict(schema_version="2.0", stream="toxicity", request_id=report["request_id"],
             results=[r["toxicity_result"] for r in report["results"]])
    validate_discovery(request, d)
    validate_response_against_request(request, t, expected_stream="toxicity")
    expected = [r["compound_id"] for r in sorted(d["results"], key=lambda r: r["rank"] or math.inf) if r["shortlisted"]]
    if report["discovery_shortlist"] != expected:
        raise ContractValidationError(["report shortlist does not match discovery"])
    for row in report["results"]:
        state, recommendation, experiment = decision(row["discovery_result"], row["toxicity_result"])
        if row["follow_up"] != dict(decision=state, recommendation=recommendation, experiment=experiment, policy_status="provisional"):
            raise ContractValidationError(["report follow-up violates policy"])


def membership_label(toxicity):
    label = toxicity["provenance"]["training_membership"]
    if any("used for model selection and thresholding" in warning for warning in toxicity["warnings"]):
        label += "; used for model selection and thresholding, not unseen evaluation"
    return label


def summary(report):
    lines = ["ToxOracle: discovery screening + human DILI", "Policy: provisional; retrospective demonstration",
             "Discovery-only shortlist: " + (", ".join(report["discovery_shortlist"]) or "unavailable")]
    for row in sorted(report["results"], key=lambda r: r["discovery_result"]["rank"] or math.inf):
        t = row["toxicity_result"]
        lines.append(f"{row['compound_id']}: rank={row['discovery_result']['rank']}; "
                     f"DILI={t['assessment']['call']}; follow-up={row['follow_up']['decision']}; "
                     f"training membership={membership_label(t)}")
    lines.extend(report["limitations"])
    return "\n".join(lines) + "\n"


def render(report):
    """Self-contained escaped HTML; raw vendor artifacts are never embedded as markup."""
    validate_screening_report(report)
    esc = lambda x: html.escape(str(x))
    rows, details = [], []
    for r in sorted(report["results"], key=lambda r: r["discovery_result"]["rank"] or math.inf):
        d, t = r["discovery_result"], r["toxicity_result"]
        a = t["assessment"]
        def display_number(value):
            return "unavailable" if value is None else f"{value:.4f}"
        values = [r["compound_id"], d["rank"], display_number(d["mean_binding_probability"]),
                  "shortlisted" if d["shortlisted"] else "unranked" if d["rank"] is None else "not shortlisted",
                  display_number(a["risk_score"]), a["call"], display_number(a["applicability"]["value"]),
                  membership_label(t), r["follow_up"]["decision"]]
        rows.append("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in values) + "</tr>")
        details.append(f"<details><summary>{esc(r['compound_id'])}: evidence and recommendation</summary>"
                       f"<p>{esc(r['follow_up']['recommendation'])}</p><pre>{esc(json.dumps(r,indent=2))}</pre></details>")
    headings = ["Candidate", "Discovery rank", "Predicted binder likelihood", "Before DILI",
                "DILI score", "DILI call", "Training similarity (not confidence)", "Training membership", "After DILI"]
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>ToxOracle screening</title><style>body{font:16px system-ui;margin:2rem;color:#18302b;background:#f7faf8}'
            'table{border-collapse:collapse;width:100%}td,th{padding:.65rem;border:1px solid #b9ccc6;text-align:left}'
            'th{background:#dcebe4}pre{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:1rem 0}'
            '.table{overflow-x:auto}</style><h1>Discovery screening + human DILI</h1>'
            '<p>Retrospective demonstration · Provisional decision policy</p>'
            f'<p>Target: {esc(report["target"]["target_id"])}</p>'
            '<div class="table"><table><thead><tr>' + ''.join(f'<th>{esc(h)}</th>' for h in headings) +
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>' +
            '<ul>' + ''.join(f'<li>{esc(s)}</li>' for s in report['limitations']) + '</ul>' + ''.join(details) + '</html>')
