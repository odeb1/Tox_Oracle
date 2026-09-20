"""Read-only analysis of aligned nested-CV training predictions; no model fitting.

Fixed 0.5 calls are diagnostic only, never deployment thresholds or label changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from toxicity.src import bionemo_experiment as experiment
from toxicity.src import morgan_svm as svm

DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/training_error_audit_v1.json"
SOURCES = {
    "xgboost": ("morgan_xgboost_v1", {"rf": "rf", "xgboost": "xgboost"}),
    "mlp": ("bionemo_mlp_v2", {"morgan": "morgan_mlp", "embedding": "bionemo_mlp"}),
    "blend": ("bionemo_ensemble_v1", {"embedding": "bionemo_lr", "selected_blend": "rf_bionemo_blend"}),
}


def extract_oof(report, train_ids, membership):
    """Reject duplicates, partial cohorts, foreign IDs or incompatible group folds."""
    nested = report["nested_training_cv"]
    folds = nested["folds"]
    held = []
    signature = []
    for f in folds:
        fit, hold = f["fit_ids"], f["holdout_ids"]
        if (len(set(fit)) != len(fit) or len(set(hold)) != len(hold)
                or set(fit) & set(hold) or set(fit) | set(hold) != train_ids):
            raise ValueError("invalid_oof_fold_coverage")
        if {membership[s]["group"] for s in fit} & {membership[s]["group"] for s in hold}:
            raise ValueError("oof_group_leakage")
        held.extend(hold)
        signature.append(tuple(sorted(hold)))
    if len(held) != len(train_ids) or set(held) != train_ids:
        raise ValueError("invalid_oof_holdout_coverage")
    rows = nested.get("predictions")
    if rows is None:
        rows = [r for f in folds for r in f["predictions"]]
        for f in folds:
            if {r["structure_id"] for r in f["predictions"]} != set(f["holdout_ids"]):
                raise ValueError("misaligned_fold_predictions")
    ids = [r["structure_id"] for r in rows]
    if len(ids) != len(train_ids) or set(ids) != train_ids:
        raise ValueError("invalid_oof_prediction_coverage")
    return {r["structure_id"]: r for r in rows}, tuple(sorted(signature))


def summarize(y, predictions):
    y = np.asarray(y)
    if set(y) != {0, 1} or "rf" not in predictions:
        raise ValueError("audit_requires_binary_labels_and_rf")
    for p in predictions.values():
        if p.shape != y.shape or not np.isfinite(p).all() or not ((p >= 0) & (p <= 1)).all():
            raise ValueError("invalid_audit_probabilities")
    wrong = {arm: (p >= .5) != y for arm, p in predictions.items()}
    comparisons = {}
    rf_wrong = wrong["rf"]
    for arm, p in predictions.items():
        if arm == "rf":
            continue
        residual_a, residual_b = y - predictions["rf"], y - p
        correlation = float(np.corrcoef(residual_a, residual_b)[0, 1]) if residual_a.std() > 0 and residual_b.std() > 0 else None
        comparisons[arm] = {
            "both_wrong": int(np.sum(rf_wrong & wrong[arm])),
            "rf_wrong_other_correct": int(np.sum(rf_wrong & ~wrong[arm])),
            "rf_correct_other_wrong": int(np.sum(~rf_wrong & wrong[arm])),
            "both_correct": int(np.sum(~rf_wrong & ~wrong[arm])),
            "residual_pearson_correlation": correlation,
            "per_class": {str(label): {
                "rf_wrong_other_correct": int(np.sum((y == label) & rf_wrong & ~wrong[arm])),
                "rf_correct_other_wrong": int(np.sum((y == label) & ~rf_wrong & wrong[arm])),
            } for label in (0, 1)},
        }
    all_wrong = np.logical_and.reduce(list(wrong.values()))
    return {
        "n": len(y), "positives": int(y.sum()), "diagnostic_threshold": .5,
        "pooled_oof_metrics_at_diagnostic_threshold": {a: experiment.metrics(y, p, .5) for a, p in predictions.items()},
        "comparisons_to_rf": comparisons,
        "all_models_wrong": int(all_wrong.sum()), "all_models_wrong_positive": int(np.sum(all_wrong & (y == 1))),
        "all_models_wrong_negative": int(np.sum(all_wrong & (y == 0))),
    }


def run(output=DEFAULT_OUTPUT, svm_report=None):
    output = Path(output)
    if output.exists():
        raise ValueError("refusing_to_overwrite_error_audit")
    rows, _, membership, data_sha, split_sha = experiment.load_frozen_inputs()
    train = [r for r in rows if membership[r["structure_id"]]["partition"] == "train"]
    ids = [r["structure_id"] for r in train]
    y = np.asarray([int(r["dili_label"]) for r in train])
    files = [(experiment.ROOT / "artifacts/runs" / name / "report.json", mapping)
             for name, mapping in SOURCES.values()]
    if svm_report is not None:
        files.append((Path(svm_report), {"svm": "svm"}))
    predictions, provenance, reference_signature, reference_folds = {}, [], None, None
    for path, mapping in files:
        report = json.loads(path.read_text())
        if report["data_sha256"] != data_sha or report["split_sha256"] != split_sha:
            raise ValueError("error_audit_source_design_mismatch")
        oof, signature = extract_oof(report, set(ids), membership)
        if reference_signature is None:
            reference_signature = signature
            reference_folds = report["nested_training_cv"]["folds"]
        elif signature != reference_signature:
            raise ValueError("different_oof_folds")
        for column, arm in mapping.items():
            predictions[arm] = np.asarray([oof[s][column] for s in ids], dtype=float)
        if not np.allclose([oof[s]["rf"] for s in ids], predictions["rf"], atol=1e-12, rtol=0):
            raise ValueError("rf_comparator_predictions_disagree")
        provenance.append({"path": str(path.relative_to(experiment.ROOT)) if path.is_relative_to(experiment.ROOT) else str(path),
                           "sha256": experiment.digest(path), "columns": mapping})
    summary = summarize(y, predictions)
    # For OOF queries, nearest neighbours must come from that fold's fitting set,
    # not the full training cohort (which would include the query itself).
    X = np.asarray([experiment.fingerprint(r["canonical_smiles"]) for r in train])
    position = {s: i for i, s in enumerate(ids)}
    nearest = {}
    for fold in reference_folds:
        fit = [position[s] for s in fold["fit_ids"]]
        hold = [position[s] for s in fold["holdout_ids"]]
        similarities = svm.tanimoto(X[hold], X[fit])
        for row_number, i in enumerate(hold):
            j = fit[int(np.argmax(similarities[row_number]))]
            nearest[ids[i]] = {"structure_id": ids[j], "compound_name": train[j]["compound_name"],
                               "tanimoto": float(similarities[row_number].max()), "label": int(y[j])}
    records = []
    for i, row in enumerate(train):
        wrong = [a for a, p in predictions.items() if int(p[i] >= .5) != y[i]]
        records.append({"structure_id": ids[i], "compound_id": row["compound_id"], "compound_name": row["compound_name"],
                        "group": membership[ids[i]]["group"], "label": int(y[i]), "wrong_at_diagnostic_05": wrong,
                        "probabilities": {a: float(p[i]) for a, p in predictions.items()},
                        "mean_squared_probability_error": float(np.mean([(p[i] - y[i])**2 for p in predictions.values()])),
                        "nearest_outer_fitting_compound": nearest[ids[i]]})
    hard = sorted([r for r in records if len(r["wrong_at_diagnostic_05"]) == len(predictions)],
                  key=lambda r: (-r["mean_squared_probability_error"], r["structure_id"]))
    report = {
        "schema": "training_oof_error_audit_v1", "data_sha256": data_sha, "split_sha256": split_sha,
        "source_sha256": experiment.digest(Path(__file__)), "sources": provenance, "summary": summary,
        "hard_case_review_queue": hard, "records": records,
        "limitations": ["Only nested out-of-fold training predictions; no validation/test labels or predictions used by this audit.",
                        "Fixed 0.5 threshold is diagnostic, not any model's validation-selected operating threshold.",
                        "Pooled OOF metrics are not arithmetic mean fold metrics or fresh test evidence.",
                        "Correlated predictors and unequal calibration affect error counts and residual correlations.",
                        "Complementary errors do not prove a trainable blend can identify corrections on unseen compounds.",
                        "Consensus mistakes flag model/data review, not incorrect ground truth; no relabeling or exclusions.",
                        "Post-hoc analysis of repeatedly used development data; no new ensemble fitted or superiority claim.",
                        "Nearest comparator comes only from each outer fitting fold; similarity is not confidence.",
                        "Compound-level concern, not patient incidence or proof of safety."],
    }
    experiment.save_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--svm-report", type=Path)
    args = parser.parse_args()
    report = run(args.output, args.svm_report)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
