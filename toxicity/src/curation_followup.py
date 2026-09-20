"""Offline source-row review of training errors and external identity flags.

Never fits, predicts, relabels, changes preprocessing, or approves a cohort.
Raw spreadsheets are read-only; interpretations go into a fresh JSON report.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re

import numpy as np
import openpyxl

from toxicity.src import bionemo_experiment as experiment
from toxicity.src import ingest_dilirank as ingest

ROOT = experiment.ROOT
DEFAULT_OUTPUT = ROOT / "artifacts/runs/curation_followup_v1.json"
PINS = {
    "artifacts/runs/training_error_audit_with_svm_v1.json": "74357edede52dfc603fb11d030c7a043cef324565fd86d11d0baf8adeafb1156",
    "artifacts/external_audit/review65.json": "82d8511f930ebcc81d53b7bab72404f36c50a5926ff62fca0db18c667449888c",
    "data/processed/dilirank2_enriched.csv": "6f1521f69f503b3366c57ac897622a14c01b6515ed90d53d6a8edc8e222c05da",
}
RAW_SOURCE = ROOT / "artifacts/external_audit/followup_sources_v2/dilirank_2.0.xlsx"
RAW_SHA = "1ca1352ff727af68e68e250eae2ed775bca8492335140ac0afd2233248694993"
TAG = re.compile(r"\s+\[(?:INN(?:-Latin|-Spanish)?|USAN|JAN|VANDF|MI|MART\.|WHO-DD|USP|BAN|USAN:USP:INN:BAN:JAN)\]$", re.I)


def alias_key(name):
    """Diagnostic only: strip an explicit naming-authority tag, not salts/stereo."""
    return ingest.normalized_name(TAG.sub("", name))


def alias_index(source):
    result = defaultdict(list)
    for row in source:
        for name in [row["compound_name"]] + json.loads(row.get("synonyms") or "[]"):
            key = alias_key(name)
            if key:
                result[key].append((row["compound_id"], row["compound_name"], name))
    return result


def alias_hits(names, index):
    hits = set()
    for external_name in names:
        if external_name:
            for cid, name, source_name in index.get(alias_key(external_name), []):
                hits.add((cid, name, external_name, source_name))
    return [dict(compound_id=c, compound_name=n, external_alias=e, source_alias=s)
            for c, n, e, s in sorted(hits)]


def training_review(audit, train_rows, source, raw=None):
    train = {r["structure_id"]: r for r in train_rows}
    records = audit["records"]
    ids = [r["structure_id"] for r in records]
    if len(ids) != len(train) or set(ids) != set(train):
        raise ValueError("review_requires_exact_training_cohort")
    source_by_id = {r["compound_id"]: r for r in source}
    raw_by_id = {r["LTKBID"]: r for r in raw} if raw is not None else None
    output = []
    arms = set(records[0]["probabilities"])
    if not arms or "rf" not in arms:
        raise ValueError("missing_model_probabilities")
    for record in records:
        model_row = train[record["structure_id"]]
        label = int(model_row["dili_label"])
        p = record["probabilities"]
        if (set(p) != arms or any(not np.isfinite(v) or not 0 <= v <= 1 for v in p.values())
                or record["label"] != label):
            raise ValueError("review_probability_or_label_mismatch")
        source_ids = json.loads(model_row["source_compound_ids"])
        evidence = []
        nonambiguous = set()
        for cid in source_ids:
            enriched = source_by_id[cid]
            if raw_by_id is not None:
                original = raw_by_id[cid]
                for field in ingest.SOURCE_COLUMNS:
                    if str(enriched[field]) != str(original[field] if original[field] is not None else ""):
                        raise ValueError("raw_source_metadata_mismatch")
                if int(enriched["source_excel_row"]) != original["source_excel_row"]:
                    raise ValueError("raw_source_row_mismatch")
            else:
                # Validate against retained FDA columns, without claiming the
                # original workbook was independently inspected this run.
                category = ingest.category(enriched["vDILI-Concern"])
                original = {**enriched, "source_excel_row": int(enriched["source_excel_row"]),
                            "dili_category": category,
                            "dili_label": {"Most-DILI-concern": 1, "Less-DILI-concern": 1,
                                           "No-DILI-concern": 0, "Ambiguous-DILI-concern": None}[category]}
            if enriched["structure_id"] != model_row["structure_id"]:
                raise ValueError("source_structure_identity_mismatch")
            if original["dili_label"] is not None:
                nonambiguous.add(original["dili_label"])
            evidence.append({"compound_id": cid, "compound_name": original["CompoundName"],
                             "sheet": "version 2", "source_excel_row": original["source_excel_row"],
                             "range": f"A{original['source_excel_row']}:F{original['source_excel_row']}",
                             "source_category": original["dili_category"], "mapped_label": original["dili_label"],
                             "original_workbook_rechecked": raw_by_id is not None,
                             "source_comment": original["Comment"], "mapping_status": enriched["mapping_status"],
                             "pubchem_cid": enriched["pubchem_cid"], "structure_source": enriched["structure_source"]})
        if nonambiguous != {label}:
            raise ValueError("source_binary_label_disagreement")
        wrong = sorted(a for a, v in p.items() if int(v >= .5) != label)
        if wrong != sorted(record["wrong_at_diagnostic_05"]):
            raise ValueError("saved_error_classification_mismatch")
        nearest = record["nearest_outer_fitting_compound"]
        if nearest["structure_id"] == record["structure_id"] or nearest["structure_id"] not in train:
            raise ValueError("invalid_nearest_training_identity")
        output.append({**record, "source_evidence": evidence, "source_label_mapping_verified": True,
                       "all_models_wrong": len(wrong) == len(arms),
                       "any_source_comment_new": any(e["source_comment"] == "New" for e in evidence),
                       "nearest_label_differs": nearest["label"] != label,
                       "adjudication": "not_performed; model agreement does not authorize relabeling"})
    hard = [r for r in output if r["all_models_wrong"]]
    if {r["structure_id"] for r in hard} != {r["structure_id"] for r in audit["hard_case_review_queue"]}:
        raise ValueError("hard_case_queue_mismatch")
    strata = {}
    for label in (0, 1):
        rows = [r for r in output if r["label"] == label]
        failed = [r for r in rows if r["all_models_wrong"]]
        strata[str(label)] = {
            "total": len(rows), "consensus_errors": len(failed),
            "source_new_total": sum(r["any_source_comment_new"] for r in rows),
            "source_new_consensus_errors": sum(r["any_source_comment_new"] for r in failed),
            "nearest_different_label_total": sum(r["nearest_label_differs"] for r in rows),
            "nearest_different_label_consensus_errors": sum(r["nearest_label_differs"] for r in failed),
            "median_nearest_tanimoto_total": float(np.median([r["nearest_outer_fitting_compound"]["tanimoto"] for r in rows])),
            "median_nearest_tanimoto_consensus_errors": float(np.median([r["nearest_outer_fitting_compound"]["tanimoto"] for r in failed])) if failed else None,
        }
    return {"summary": {"training_records_verified": len(output), "hard_cases": len(hard),
                        "verification_basis": "original_workbook" if raw_by_id is not None else "pinned_enriched_snapshot_retained_FDA_columns",
                        "source_label_mapping_mismatches": 0, "strata": strata},
            "hard_cases": sorted(hard, key=lambda r: r["compound_name"].casefold())}


def external_review(records, source, synonyms):
    index = alias_index(source)
    rows = []
    for r in records:
        flags = []
        for field, flag in (("new_name_overlap_flags", "prior_name_overlap"),
                            ("tautomer_no_stereo_source_match_ids", "prior_tautomer_overlap"),
                            ("underlying_table_disagreement", "prior_label_disagreement")):
            if r[field]:
                flags.append(flag)
        hits = alias_hits([r["pubchem_title"] or ""] + synonyms.get(r["pubchem_cid"], []), index)
        if hits:
            flags.append("naming_authority_tag_alias_overlap")
        if any(r["pubchem_structure_source_overlap"].values()):
            flags.append("pubchem_structure_overlap")
        family = sorted({e["sheet"] for e in r["underlying_table_evidence"]})
        row = {**r, "followup_alias_overlap_flags": hits, "review_flags": flags,
               "in_prior_52_queue": not (r["new_name_overlap_flags"] or r["tautomer_no_stereo_source_match_ids"] or r["underlying_table_disagreement"]),
               "table_families": family, "source_annotations": sorted({e["annotation"] for e in r["underlying_table_evidence"]}),
               "identity_review_needed": r["pubchem_identity"] != "exact_parent_inchikey" or not r["pubchem_title"] or bool(hits),
               "endpoint_adjudicated": False, "approved_for_evaluation": False}
        rows.append(row)
    prior = [r for r in rows if r["in_prior_52_queue"]]
    remaining = [r for r in prior if not r["review_flags"]]
    def counts(selected):
        return {"n": len(selected), "labels": dict(Counter(str(r["label"]) for r in selected)),
                "identity": dict(Counter(r["pubchem_identity"] for r in selected)),
                "missing_titles": sum(not r["pubchem_title"] for r in selected),
                "table_family_combinations": dict(Counter(" + ".join(r["table_families"]) for r in selected)),
                "annotation_combinations": dict(Counter(" + ".join(r["source_annotations"]) for r in selected))}
    return {"summary": {"all_reviewed": len(rows), "previous_remainder": counts(prior),
                        "new_flagged_from_previous_remainder": sum(bool(r["review_flags"]) for r in prior),
                        "remaining_without_current_flags_not_approved": counts(remaining), "approved": 0},
            "records": rows}


def verify_external_cells(records, workbook):
    for r in records:
        evidence = [dict(r["original_combined_table"], sheet="supplementary table S2.1")] + r["underlying_table_evidence"]
        for e in evidence:
            cells = next(workbook[e["sheet"]].iter_rows(min_row=e["row"], max_row=e["row"], min_col=1, max_col=4, values_only=True))
            if (str(cells[0]) != str(r["pubchem_cid"])
                    or tuple(cells[1:]) != (e["smiles"], e["annotation"], e["label"])):
                raise ValueError("external_source_cell_mismatch")


def run(output=DEFAULT_OUTPUT):
    output = Path(output)
    if output.exists():
        raise ValueError("refusing_to_overwrite_curation_review")
    protected = {ROOT / path: sha for path, sha in PINS.items()}
    for path, sha in protected.items():
        if experiment.digest(path) != sha:
            raise ValueError("curation_input_checksum_mismatch")
    frozen, _, membership, data_sha, split_sha = experiment.load_frozen_inputs()
    train = [r for r in frozen if membership[r["structure_id"]]["partition"] == "train"]
    with (ROOT / "data/processed/dilirank2_enriched.csv").open() as handle:
        source = list(csv.DictReader(handle))
    raw = None
    if RAW_SOURCE.exists():
        if experiment.digest(RAW_SOURCE) != RAW_SHA:
            raise ValueError("original_FDA_workbook_checksum_mismatch")
        protected[RAW_SOURCE] = RAW_SHA
        raw = ingest.read_source(RAW_SOURCE)
    audit = json.loads((ROOT / "artifacts/runs/training_error_audit_with_svm_v1.json").read_text())
    external = json.loads((ROOT / "artifacts/external_audit/review65.json").read_text())
    if ((audit["data_sha256"], audit["split_sha256"]) != (data_sha, split_sha)
            or (external["frozen_data_sha256"], external["frozen_split_sha256"]) != (data_sha, split_sha)):
        raise ValueError("review_design_mismatch")
    cache = ROOT / "artifacts/external_audit/review65_sources"
    for record in external["source_downloads"]:
        path = cache / record["file"]
        if experiment.digest(path) != record["sha256"]:
            raise ValueError("external_source_checksum_mismatch")
        protected[path] = record["sha256"]
    workbook = openpyxl.load_workbook(cache / "ci5b00238_si_002.xlsx", read_only=True, data_only=True)
    try:
        verify_external_cells(external["records"], workbook)
    finally:
        workbook.close()
    synonyms = {r["CID"]: r.get("Synonym", []) for r in json.loads((cache / "pubchem_synonyms.json").read_text())["InformationList"]["Information"]}
    license_doc = json.loads((cache / "acs_2054931.json").read_text())
    result = {
        "schema": "curation_followup_v1", "data_sha256": data_sha, "split_sha256": split_sha,
        "source_sha256": experiment.digest(Path(__file__)),
        "inputs": {str(p.relative_to(ROOT)): sha for p, sha in protected.items()},
        "training_review": training_review(audit, train, source, raw),
        "external_review": external_review(external["records"], source, synonyms),
        "source_license": license_doc["license"],
        "limitations": ["Source consistency is not independent clinical adjudication of labels or compound identities.",
                        "Without the original FDA workbook, training verification uses retained FDA columns in the checksum-pinned enriched snapshot only.",
                        "New source comment means added to DILIrank2, not a drug approval date or measured exposure.",
                        "Training errors use fixed 0.5 and depend on calibration; source fields are review-only, never model features.",
                        "Naming-authority stripping is diagnostic, not a change to production identity/preprocessing or proof of molecular identity.",
                        "No changes to labels, exclusions, frozen groups, weights, thresholds, baseline or contracts.",
                        "External review is blind to external predictions; zero models fitted or scored.",
                        "Shared source labels, differing endpoints, missing names and unresolved forms limit external independence.",
                        "License metadata is not legal clearance; intended use and upstream rights still need review.",
                        "No compound safety, patient incidence or model-superiority claim."],
    }
    for path, sha in protected.items():
        if experiment.digest(path) != sha:
            raise ValueError("review_input_changed")
    experiment.load_frozen_inputs()  # Recheck original data/split, never rewrite them.
    experiment.save_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({k: result[k]["summary"] for k in ("training_review", "external_review")}, indent=2))


if __name__ == "__main__":
    main()
