"""Exploratory Morgan/XGBoost comparison. Offline, CPU-only, no test scoring.

Reuses frozen identities, grouping, RF recipe and evaluation helpers. Writes only
a new research run directory; never replaces RF weights or the v2 interface.
"""
from __future__ import annotations

import argparse
import itertools
import json
import platform
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier

from toxicity.src import bionemo_candidate as candidate
from toxicity.src import bionemo_diagnostics as diagnosis
from toxicity.src import bionemo_ensemble as ensemble
from toxicity.src import bionemo_experiment as experiment
from toxicity.src.research_common import (
    development_data as development_data,
    positive_probability as positive_probability,
    validate_development as validate_development,
    validate_locked_runtime,
)

# Keep the three historical helper imports above available to existing callers.
# Shared utilities live in research_common, not in this optional-model runner.

XGBOOST_VERSION = "3.0.5"
FIXED = dict(objective="binary:logistic", tree_method="hist", device="cpu",
             learning_rate=.05, min_child_weight=5, subsample=.8,
             colsample_bytree=.8, reg_alpha=0., scale_pos_weight=1.,
             max_bin=256, eval_metric="logloss", random_state=42, n_jobs=1)
GRID = tuple(dict(max_depth=depth, n_estimators=trees, reg_lambda=l2)
             for depth, trees, l2 in itertools.product((2, 4), (100, 300), (10., 1.)))
DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/morgan_xgboost_v1"
PROTOCOL = {
    "id": "morgan_xgboost_v1", "xgboost_version": XGBOOST_VERSION,
    "features": "unchanged dilirank_parent_v1; chiral Morgan radius 2, 2048 binary bits",
    "fixed_parameters": FIXED, "grid": list(GRID),
    "selection": "maximum arithmetic mean inner-fold sklearn average_precision_score; ties use first grid entry (shallower, fewer trees, stronger L2)",
    "nested_cv": "3 outer StratifiedGroupKFold; 3 inner folds within each outer fitting subset; all inside frozen training; shuffle=True seed=42",
    "rf_comparator": "fixed existing RF recipe, sigmoid calibration refitted within each outer fitting subset using 3 grouped folds; no RF retuning",
    "refit": "select XGBoost on 3 grouped folds of all frozen training, then fit there only",
    "early_stopping": "disabled; number of trees selected inside training CV",
    "feature_selection_scaling": "none",
    "xgboost_calibration": "none fitted; binary-logistic probabilities assessed with Brier and reliability, not assumed calibrated",
    "validation": "only final training-selected XGBoost; threshold maximizes balanced accuracy, sensitivity then lower threshold tie-break; RF retains stored threshold",
    "test": "no test features or label arrays extracted and no test predictions; full-file checksum/group-integrity verification only",
    "external_data": "not used",
    "status": "exploratory after repeated development analysis and prior test inspection; not confirmatory",
}


def make_model(config):
    # Optional dependency: importing helpers/tests does not require XGBoost.
    import xgboost
    if xgboost.__version__ != XGBOOST_VERSION:
        raise ValueError("xgboost_version_mismatch")
    if config not in GRID:
        raise ValueError("unregistered_xgboost_configuration")
    return xgboost.XGBClassifier(**FIXED, **config)


def choose(scores):
    return max(scores, key=lambda r: (r["mean_average_precision"], -r["grid_index"]))["config"]


def select(train):
    splits = candidate.folds(train)
    scores = []
    for number, config in enumerate(GRID):
        values = []
        for fit, hold in splits:
            model = make_model(config).fit(train["X"][fit], train["y"][fit])
            p = positive_probability(model, train["X"][hold])
            values.append(diagnosis.probability_metrics(train["y"][hold], p))
        scores.append({"grid_index": number, "config": config, "folds": values,
                       "mean_average_precision": float(np.mean([r["average_precision"] for r in values]))})
    return {"selected": choose(scores), "scores": scores,
            "fold_membership": [candidate.fold_ids(train, fit, hold) for fit, hold in splits]}


def build(data, final_rf, rf_threshold):
    validate_development(data)
    train, valid = data["train"], data["validation"]
    records = []
    oof = {arm: np.full(len(train["y"]), np.nan) for arm in ("rf", "xgboost")}
    for number, (fit, hold) in enumerate(candidate.folds(train), 1):
        print(f"Outer training fold {number}/3: eight XGBoost configurations", flush=True)
        fitting = candidate.subset(train, fit)
        selected = select(fitting)
        xgb = make_model(selected["selected"]).fit(fitting["X"], fitting["y"])
        rf, calibration = ensemble.fit_rf(fitting, train["X"].shape[1])
        probabilities = {"rf": positive_probability(rf, train["X"][hold]),
                         "xgboost": positive_probability(xgb, train["X"][hold])}
        for arm, p in probabilities.items():
            if not np.isnan(oof[arm][hold]).all():
                raise ValueError("duplicate_oof_assignment")
            oof[arm][hold] = p
        metrics = {arm: diagnosis.probability_metrics(train["y"][hold], p) for arm, p in probabilities.items()}
        records.append({**candidate.fold_ids(train, fit, hold), "inner_selection": selected,
                        "rf_calibration_folds": calibration, "metrics": metrics,
                        "paired_delta_xgboost_minus_rf": {k: metrics["xgboost"][k] - metrics["rf"][k]
                                                          for k in ("auroc", "average_precision", "brier")}})
    if any(not np.isfinite(p).all() for p in oof.values()):
        raise ValueError("incomplete_oof_coverage")
    print("Final XGBoost selection inside all frozen training compounds", flush=True)
    selection = select(train)
    model = make_model(selection["selected"]).fit(train["X"], train["y"])
    # First predictions using the pre-existing full-training RF occur only here.
    vp = {"xgboost": positive_probability(model, valid["X"]),
          "rf": positive_probability(final_rf, valid["X"])}
    threshold = experiment.choose_threshold(valid["y"], vp["xgboost"])
    report = {
        "protocol": PROTOCOL, "training_selection": selection,
        "counts": {part: {"n": len(d["y"]), "positive": int(d["y"].sum())} for part, d in data.items()},
        "nested_training_cv": {
            "folds": records,
            "mean": {arm: {key: float(np.mean([r["metrics"][arm][key] for r in records]))
                           for key in records[0]["metrics"][arm]} for arm in oof},
            "pooled_oof_metrics": {arm: diagnosis.probability_metrics(train["y"], p) for arm, p in oof.items()},
            "pooled_oof_reliability": {arm: experiment.reliability(train["y"], p) for arm, p in oof.items()},
            "predictions": [{"structure_id": sid, **{arm: float(p[i]) for arm, p in oof.items()}}
                            for i, sid in enumerate(train["structure_ids"])],
        },
        "validation": {arm: experiment.metrics(valid["y"], p, threshold if arm == "xgboost" else rf_threshold)
                       for arm, p in vp.items()},
        "validation_reliability": {arm: experiment.reliability(valid["y"], p) for arm, p in vp.items()},
        "validation_predictions": [{"structure_id": sid, **{arm: float(p[i]) for arm, p in vp.items()}}
                                   for i, sid in enumerate(valid["structure_ids"])],
        "limitations": [
            "Exploratory: repeated development-data analysis and prior test inspection; not independent confirmation.",
            "RF hyperparameters/calibration choice originally used validation; fixed here, not retuned.",
            "XGBoost probabilities are uncalibrated; Brier/reliability assess rather than guarantee calibration.",
            "Scaffold/connectivity grouping does not exclude all analogue or tautomer relationships.",
            "Fold deltas and pooled OOF metrics are descriptive, not a significance test or improvement claim.",
            "No test or external predictions. No pretrained representation or BioNeMo dependency used for features.",
            "Drug-level DILI concern, not patient incidence or proof of safety.",
            "Original teammate RF artifact still preferred; verified scratch reproduction is not promoted.",
        ],
    }
    return model, report


def run(output_dir=DEFAULT_OUTPUT, rf_path=ensemble.RF_PATH):
    output_dir, rf_path = Path(output_dir), Path(rf_path)
    if output_dir.exists():
        raise ValueError("refusing_to_overwrite_research_directory")
    make_model(GRID[0])  # Fail fast on a missing/wrong optional dependency, without fitting.
    lock = Path(__file__).resolve().parents[1] / "requirements-model.lock"
    validate_locked_runtime(lock, version_lookup=version)
    if experiment.digest(rf_path) != ensemble.RF_SHA256:
        raise ValueError("unverified_rf_artifact_refuse_pickle_load")
    rows, _, membership, data_sha, split_sha = experiment.load_frozen_inputs()
    development = development_data(rows, membership)
    original = joblib.load(rf_path)  # Only exact locally verified artifact, after hash check.
    if (original["data_sha256"] != data_sha or not original["calibrated"]
            or original["rf"].get_params() != RandomForestClassifier(**ensemble.RF_PARAMS).get_params()):
        raise ValueError("rf_identity_or_configuration_mismatch")
    for part in development:
        ids = [original["rows"][i]["structure_id"] for i in original[part + "_indices"]]
        if ids != development[part]["structure_ids"]:
            raise ValueError("rf_partition_identity_mismatch")
    idx = {part: [i for i, r in enumerate(rows) if membership[r["structure_id"]]["partition"] == part]
           for part in development}
    applicability = experiment.applicability(rows, idx["train"], idx["validation"])
    protected = {path: experiment.digest(path) for path in (experiment.DATA, experiment.SPLIT, rf_path,
                 experiment.BASELINE_REPORT, experiment.ROOT / "evaluation/reports/baseline_selection.json", lock)}
    baseline_path = experiment.ROOT / "artifacts/models/dili_baseline.joblib"
    baseline_digest = experiment.digest(baseline_path) if baseline_path.exists() else None
    provenance = {
        "data_sha256": data_sha, "split_sha256": split_sha, "rf_reproduction_sha256": ensemble.RF_SHA256,
        "source_sha256": {name: experiment.digest(Path(__file__).with_name(name)) for name in
                          ("morgan_xgboost.py", "research_common.py", "bionemo_ensemble.py", "bionemo_candidate.py", "bionemo_diagnostics.py",
                           "bionemo_experiment.py", "baseline.py", "ingest_dilirank.py")},
        "dependency_lock_sha256": experiment.digest(Path(__file__).resolve().parents[1] / "requirements-xgboost.lock"),
        "baseline_dependency_lock_sha256": experiment.digest(lock),
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    **{name: version(name) for name in ("xgboost", "scikit-learn", "numpy", "scipy", "rdkit", "joblib")}},
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    experiment.save_json(output_dir / "protocol.json", {**PROTOCOL, "provenance": provenance})
    protocol_sha = experiment.digest(output_dir / "protocol.json")
    del rows, membership
    model, report = build(development, original["predictor"], original["threshold"])
    report.update(provenance)
    report["protocol_sha256"] = protocol_sha
    report["validation_applicability"] = {"method": "nearest training Morgan radius-2 2048-bit Tanimoto; no validated cutoff", "records": applicability}
    path = output_dir / "xgboost.ubj"
    model.save_model(path)
    restored = make_model(report["training_selection"]["selected"])
    restored.load_model(path)
    np.testing.assert_array_equal(positive_probability(restored, development["validation"]["X"]),
                                  [r["xgboost"] for r in report["validation_predictions"]])
    assert experiment.digest(output_dir / "protocol.json") == protocol_sha
    for protected_path, expected in protected.items():
        if experiment.digest(protected_path) != expected:
            raise ValueError("protected_baseline_input_or_artifact_changed")
    if (experiment.digest(baseline_path) if baseline_path.exists() else None) != baseline_digest:
        raise ValueError("baseline_artifact_changed_or_promoted")
    report["artifact"] = {"filename": path.name, "sha256": experiment.digest(path),
                          "validation_roundtrip_exact": True, "promoted": False,
                          "threshold_location": "report.json:validation.xgboost.threshold"}
    experiment.save_json(output_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rf", type=Path, default=ensemble.RF_PATH)
    parser.add_argument("--print-protocol", action="store_true")
    args = parser.parse_args()
    if args.print_protocol:
        print(json.dumps(PROTOCOL, indent=2))
        return
    result = run(args.output_dir, args.rf)
    print(json.dumps({"selected": result["training_selection"]["selected"],
                      "nested_training_cv": result["nested_training_cv"]["mean"],
                      "validation": result["validation"]}, indent=2))


if __name__ == "__main__":
    main()
