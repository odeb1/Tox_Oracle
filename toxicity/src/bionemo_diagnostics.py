"""Offline, exploratory train/validation diagnosis; never score the test partition.

This is not the original prespecified experiment or a deployment/training command.
It writes only a new diagnostic report, not weights, embeddings or baseline files.
"""
from __future__ import annotations

import argparse
import json
import platform
import warnings
from importlib.metadata import version
from pathlib import Path

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from toxicity.src import bionemo_experiment as experiment

# Declared before examining this diagnostic's results; do not expand based on test scores.
C_VALUES = (1.0, 0.1, 0.01, 0.001, 0.0001)
DEFAULT_CACHE = experiment.ROOT / "artifacts/embeddings/megamolbart_dilirank2.json"
DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/megamolbart_train_validation_diagnosis.json"


def development_data(rows, membership, matrix):
    """Extract only development labels. Test labels are never converted or inspected."""
    result = {}
    for part in ("train", "validation"):
        idx = [i for i, row in enumerate(rows) if membership[row["structure_id"]]["partition"] == part]
        result[part] = {
            "X": matrix[idx].copy(),
            "y": np.asarray([int(rows[i]["dili_label"]) for i in idx]),
            "groups": np.asarray([membership[rows[i]["structure_id"]]["group"] for i in idx]),
            "structure_ids": [rows[i]["structure_id"] for i in idx],
        }
    if set(result["train"]["groups"]) & set(result["validation"]["groups"]):
        raise ValueError("development_group_overlap")
    return result


def make_model(c):
    return Pipeline([
        ("scale", StandardScaler()),
        ("logistic", LogisticRegression(C=c, max_iter=5000, random_state=42)),
    ])


def fit_checked(model, X, y):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(X, y)
    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
        raise ValueError("logistic_did_not_converge")
    return model


def probability_metrics(y, probability):
    return {
        "auroc": float(roc_auc_score(y, probability)),
        "average_precision": float(average_precision_score(y, probability)),
        "brier": float(brier_score_loss(y, probability)),
        "log_loss": float(log_loss(y, probability, labels=[0, 1])),
        "fraction_probability_below_005_or_above_095": float(
            np.mean((probability < 0.05) | (probability > 0.95))),
    }


def diagnose(development):
    train, valid = development["train"], development["validation"]
    X, y = train["X"], train["y"]
    folds = list(StratifiedGroupKFold(3, shuffle=True, random_state=42).split(X, y, train["groups"]))
    fold_manifest = []
    for fit_idx, hold_idx in folds:
        if set(train["groups"][fit_idx]) & set(train["groups"][hold_idx]):
            raise ValueError("cv_group_overlap")
        if any(len(np.unique(y[idx])) != 2 for idx in (fit_idx, hold_idx)):
            raise ValueError("cv_fold_requires_both_classes")
        fold_manifest.append({"fit_ids": [train["structure_ids"][i] for i in fit_idx],
                              "holdout_ids": [train["structure_ids"][i] for i in hold_idx]})

    scale = StandardScaler().fit(X)
    scaled_train = scale.transform(X)
    scaled_validation = scale.transform(valid["X"])
    singular = np.linalg.svd(scaled_train, compute_uv=False)
    energy = singular ** 2
    energy_fraction = energy / energy.sum()
    raw_std = X.std(axis=0)
    shift = np.abs(scaled_validation.mean(axis=0))
    feature_diagnostics = {
        "training_n": len(y), "dimension": X.shape[1],
        "constant_training_dimensions": int(np.sum(raw_std == 0)),
        "training_std_min_median_max": [float(f(raw_std)) for f in (np.min, np.median, np.max)],
        "training_scaled_rank": int(np.linalg.matrix_rank(scaled_train)),
        "training_spectral_participation_rank": float(1 / np.sum(energy_fraction ** 2)),
        "training_components_for_95_percent_variance": int(np.searchsorted(np.cumsum(energy_fraction), 0.95) + 1),
        "validation_abs_mean_shift_in_training_sd_median_max": [float(np.median(shift)), float(shift.max())],
        "validation_fraction_cells_abs_training_z_above_5": float(np.mean(np.abs(scaled_validation) > 5)),
        "interpretation": "Descriptive only. No PCA, feature removal or validation-fitted scaling applied.",
    }
    candidates = []
    for c in C_VALUES:
        fold_scores = []
        for fit_idx, hold_idx in folds:
            model = fit_checked(make_model(c), X[fit_idx], y[fit_idx])
            fold_scores.append(probability_metrics(y[hold_idx], model.predict_proba(X[hold_idx])[:, 1]))
        model = fit_checked(make_model(c), X, y)
        p_train = model.predict_proba(X)[:, 1]
        p_valid = model.predict_proba(valid["X"])[:, 1]
        threshold = experiment.choose_threshold(valid["y"], p_valid)
        candidates.append({
            "C": c,
            "training_resubstitution": probability_metrics(y, p_train),
            "training_group_cv": {"folds": fold_scores,
                "mean": {key: float(np.mean([score[key] for score in fold_scores])) for key in fold_scores[0]}},
            "validation": {**experiment.metrics(valid["y"], p_valid, threshold),
                           **probability_metrics(valid["y"], p_valid)},
            "validation_reliability": experiment.reliability(valid["y"], p_valid),
            "coefficient_l2_norm": float(np.linalg.norm(model.named_steps["logistic"].coef_)),
            "solver_iterations": int(model.named_steps["logistic"].n_iter_[0]),
        })
    prevalence = float(y.mean())
    return {
        "feature_diagnostics": feature_diagnostics,
        "training_group_cv_fold_manifest": fold_manifest,
        "training_prevalence_constant_reference_validation": probability_metrics(
            valid["y"], np.full(len(valid["y"]), prevalence)),
        "candidates": candidates,
    }


def run(cache_path=DEFAULT_CACHE, output=DEFAULT_OUTPUT):
    output = Path(output)
    if output.exists():
        raise ValueError("refusing_to_overwrite_existing_report")
    rows, _, membership, data_hash, split_hash = experiment.load_frozen_inputs()
    cache = json.loads(Path(cache_path).read_text())
    matrix = experiment.validate_cache(cache, rows, data_hash, split_hash)
    development = development_data(rows, membership, matrix)
    # Full-cohort structures/vectors are used only for cache integrity, not diagnostics.
    del rows, membership, matrix
    result = diagnose(development)
    report = {
        "diagnostic_id": "megamolbart_train_validation_regularization_v1",
        "status": "exploratory_diagnosis_only",
        "test_partition": "not scored; labels not used; no test predictions generated",
        "protocol": {"C_values": list(C_VALUES), "penalty": "L2", "scaler": "training-only StandardScaler",
                     "cv": "3-fold StratifiedGroupKFold within frozen training only, seed 42; scaler refit per fold",
                     "threshold": "validation balanced accuracy, sensitivity then lower threshold tie-break",
                     "selection": "Report every candidate; no deployment or final model selection"},
        "data_sha256": data_hash, "split_manifest_sha256": split_hash,
        "cache_sha256": experiment.digest(cache_path), "script_sha256": experiment.digest(Path(__file__)),
        "representation": {k: cache[k] for k in ("model_id", "model_version", "embedding_dimension")},
        "runtime": {"python": platform.python_version(), **{name: version(name) for name in
                    ("numpy", "scipy", "scikit-learn", "rdkit")}},
        "counts": {part: {"n": len(d["y"]), "positive": int(d["y"].sum())} for part, d in development.items()},
        **result,
        "limitations": [
            "Initiated after the original test result was inspected; this is exploratory, not confirmatory.",
            "Validation is reused across candidates and threshold selection; these are not unbiased held-out estimates.",
            "No claim of improvement over RF, patient incidence, clinical calibration or safety.",
            "Exact representation pretraining overlap remains unknown.",
        ],
    }
    experiment.save_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args.cache, args.output)
    print(json.dumps({"output": str(args.output), "feature_diagnostics": report["feature_diagnostics"],
                      "candidates": report["candidates"]}, indent=2))


if __name__ == "__main__":
    main()
