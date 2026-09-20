"""Bounded, offline Tanimoto-SVM comparison; grouped calibration, no test scoring."""
from __future__ import annotations

import argparse
import json
import platform
import warnings
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

from toxicity.src import bionemo_candidate as candidate
from toxicity.src import bionemo_diagnostics as diagnosis
from toxicity.src import bionemo_ensemble as ensemble
from toxicity.src import bionemo_experiment as experiment
from toxicity.src import research_common as comparison

C_VALUES = (.01, .1, 1., 10., 100.)
DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/morgan_svm_v1"
PROTOCOL = {
    "id": "morgan_svm_v1", "C_values": list(C_VALUES),
    "features": "unchanged chiral Morgan radius 2, 2048 binary bits; no scaling or feature selection",
    "kernel": "binary Tanimoto: intersection/union; both empty gives 1, one empty gives 0; float64 arithmetic prevents uint8 overflow",
    "svc": {"probability": False, "class_weight": None, "tol": .001, "max_iter": 100000, "shrinking": True},
    "calibration": "fixed sigmoid, ensemble=False; 3 scaffold/connectivity-grouped folds within EVERY fitting subset, including inner tuning fits; SVC internal probability CV disabled",
    "selection": "maximum arithmetic mean inner-fold probability AP; exact ties favor smaller C",
    "nested_cv": "3 outer training folds and 3 inner folds per outer fitting subset; StratifiedGroupKFold shuffle=True seed=42",
    "budget": "5 C values * 3 inner folds * 4 selection stages + 4 selected fits = 64 calibrated SVM fits (256 base SVC fits); no adaptive expansion",
    "rf": "fixed original RF recipe; calibration refitted within each matching outer fitting subset; original full-training RF used only for final validation",
    "validation": "only training-selected C; threshold maximizes balanced accuracy, sensitivity then lower threshold ties; RF retains its threshold",
    "test_external": "no test/external predictions, label arrays or selection; full-file integrity verification only",
    "convergence": "any ConvergenceWarning or nonzero fit_status aborts; no silent exclusions",
    "status": "exploratory after previous test inspection and repeated development analysis; no new ensemble or superiority claim",
}


def tanimoto(X, Y):
    X, Y = np.asarray(X, dtype=np.float64), np.asarray(Y, dtype=np.float64)
    if (X.ndim != 2 or Y.ndim != 2 or X.shape[1] != Y.shape[1] or X.shape[1] == 0
            or not np.isin(X, [0., 1.]).all() or not np.isin(Y, [0., 1.]).all()):
        raise ValueError("tanimoto_requires_aligned_binary_features")
    with threadpool_limits(limits=1):
        intersection = X @ Y.T
    union = X.sum(axis=1)[:, None] + Y.sum(axis=1)[None, :] - intersection
    return np.divide(intersection, union, out=np.ones_like(intersection), where=union != 0)


def fit_svm(train, c):
    if c not in C_VALUES:
        raise ValueError("unregistered_svm_C")
    folds = candidate.folds(train)
    base = SVC(C=c, kernel=tanimoto, **PROTOCOL["svc"])
    model = CalibratedClassifierCV(base, method="sigmoid", ensemble=False, cv=folds, n_jobs=1)
    try:
        with warnings.catch_warnings(), threadpool_limits(limits=1):
            warnings.simplefilter("error", ConvergenceWarning)
            model.fit(train["X"], train["y"])
    except ConvergenceWarning as exc:
        raise ValueError("svm_did_not_converge") from exc
    if model.calibrated_classifiers_[0].estimator.fit_status_ != 0:
        raise ValueError("svm_did_not_converge")
    return model, [candidate.fold_ids(train, a, b) for a, b in folds]


def select(train):
    folds = candidate.folds(train)
    scores, membership = [], []
    for c in C_VALUES:
        values = []
        for number, (fit, hold) in enumerate(folds):
            model, calibration = fit_svm(candidate.subset(train, fit), c)
            p = comparison.positive_probability(model, train["X"][hold])
            values.append(diagnosis.probability_metrics(train["y"][hold], p))
            if c == C_VALUES[0]:
                membership.append({**candidate.fold_ids(train, fit, hold), "calibration_folds": calibration})
            elif calibration != membership[number]["calibration_folds"]:
                raise ValueError("calibration_membership_changed_between_C_values")
        scores.append({"C": c, "folds": values,
                       "mean_average_precision": float(np.mean([v["average_precision"] for v in values]))})
    return {"selected_C": candidate.choose_c(scores), "scores": scores, "fold_membership": membership}


def build(data, final_rf, rf_threshold):
    comparison.validate_development(data)
    train, valid = data["train"], data["validation"]
    oof = {arm: np.full(len(train["y"]), np.nan) for arm in ("rf", "svm")}
    outer = []
    for number, (fit, hold) in enumerate(candidate.folds(train), 1):
        print(f"Outer training fold {number}/3: five C values with nested grouped calibration", flush=True)
        fitting = candidate.subset(train, fit)
        selection = select(fitting)
        svm, svm_cal = fit_svm(fitting, selection["selected_C"])
        rf, rf_cal = ensemble.fit_rf(fitting, train["X"].shape[1])
        scores = {arm: comparison.positive_probability(model, train["X"][hold]) for arm, model in (("rf", rf), ("svm", svm))}
        for arm, p in scores.items():
            if not np.isnan(oof[arm][hold]).all():
                raise ValueError("duplicate_oof_assignment")
            oof[arm][hold] = p
        measures = {arm: diagnosis.probability_metrics(train["y"][hold], p) for arm, p in scores.items()}
        outer.append({**candidate.fold_ids(train, fit, hold), "inner_selection": selection,
                      "svm_calibration_folds": svm_cal, "rf_calibration_folds": rf_cal, "metrics": measures,
                      "delta_svm_minus_rf": {k: measures["svm"][k] - measures["rf"][k] for k in ("auroc", "average_precision", "brier")}})
    if any(not np.isfinite(p).all() for p in oof.values()):
        raise ValueError("incomplete_oof_coverage")
    print("Final C selection and grouped calibration inside all frozen training", flush=True)
    selection = select(train)
    model, calibration = fit_svm(train, selection["selected_C"])
    vp = {"svm": comparison.positive_probability(model, valid["X"]),
          "rf": comparison.positive_probability(final_rf, valid["X"])}
    threshold = experiment.choose_threshold(valid["y"], vp["svm"])
    report = {
        "protocol": PROTOCOL, "training_selection": selection, "final_calibration_folds": calibration,
        "counts": {part: {"n": len(d["y"]), "positive": int(d["y"].sum())} for part, d in data.items()},
        "nested_training_cv": {
            "folds": outer,
            "mean": {arm: {k: float(np.mean([r["metrics"][arm][k] for r in outer])) for k in outer[0]["metrics"][arm]} for arm in oof},
            "pooled_oof_metrics": {arm: diagnosis.probability_metrics(train["y"], p) for arm, p in oof.items()},
            "pooled_oof_reliability": {arm: experiment.reliability(train["y"], p) for arm, p in oof.items()},
            "predictions": [{"structure_id": sid, **{arm: float(p[i]) for arm, p in oof.items()}}
                            for i, sid in enumerate(train["structure_ids"])],
        },
        "validation": {arm: experiment.metrics(valid["y"], p, threshold if arm == "svm" else rf_threshold) for arm, p in vp.items()},
        "validation_reliability": {arm: experiment.reliability(valid["y"], p) for arm, p in vp.items()},
        "validation_predictions": [{"structure_id": sid, **{arm: float(p[i]) for arm, p in vp.items()}}
                                   for i, sid in enumerate(valid["structure_ids"])],
        "limitations": ["Exploratory after repeated development analysis and prior test inspection; not independent confirmation.",
                        "RF settings/calibration originally validation-selected, held fixed here.",
                        "Sigmoid calibration is training-only but does not establish clinical calibration.",
                        "Scaffold/connectivity splitting does not eliminate every analogue or tautomer relationship.",
                        "No test/external scoring, new ensemble, patient-incidence or proof-of-safety claim.",
                        "Original teammate RF remains preferred; scratch reproduction is not promoted."],
    }
    return model, report


def run(output_dir=DEFAULT_OUTPUT, rf_path=ensemble.RF_PATH):
    output_dir, rf_path = Path(output_dir), Path(rf_path)
    if output_dir.exists():
        raise ValueError("refusing_to_overwrite_svm_directory")
    lock = Path(__file__).resolve().parents[1] / "requirements-model.lock"
    comparison.validate_locked_runtime(lock, version_lookup=version)
    if experiment.digest(rf_path) != ensemble.RF_SHA256:
        raise ValueError("unverified_rf_artifact_refuse_pickle_load")
    rows, _, membership, data_sha, split_sha = experiment.load_frozen_inputs()
    data = comparison.development_data(rows, membership)
    original = joblib.load(rf_path)  # Only exact hash-verified locally reproduced RF.
    if (original["data_sha256"] != data_sha or not original["calibrated"]
            or original["rf"].get_params() != RandomForestClassifier(**ensemble.RF_PARAMS).get_params()):
        raise ValueError("rf_identity_or_configuration_mismatch")
    for part in data:
        if [original["rows"][i]["structure_id"] for i in original[part + "_indices"]] != data[part]["structure_ids"]:
            raise ValueError("rf_partition_identity_mismatch")
    idx = {part: [i for i, r in enumerate(rows) if membership[r["structure_id"]]["partition"] == part] for part in data}
    applicability = experiment.applicability(rows, idx["train"], idx["validation"])
    protected = {p: experiment.digest(p) for p in (experiment.DATA, experiment.SPLIT, rf_path, lock,
                 experiment.BASELINE_REPORT, experiment.ROOT / "evaluation/reports/baseline_selection.json")}
    baseline = experiment.ROOT / "artifacts/models/dili_baseline.joblib"
    baseline_sha = experiment.digest(baseline) if baseline.exists() else None
    provenance = {
        "data_sha256": data_sha, "split_sha256": split_sha, "rf_reproduction_sha256": ensemble.RF_SHA256,
        "dependency_lock_sha256": experiment.digest(lock),
        "source_sha256": {n: experiment.digest(Path(__file__).with_name(n)) for n in
                          ("morgan_svm.py", "research_common.py", "bionemo_ensemble.py", "bionemo_candidate.py",
                           "bionemo_diagnostics.py", "bionemo_experiment.py", "baseline.py", "ingest_dilirank.py")},
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    **{n: version(n) for n in ("numpy", "scipy", "scikit-learn", "rdkit", "joblib", "threadpoolctl")}},
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    experiment.save_json(output_dir / "protocol.json", {**PROTOCOL, "provenance": provenance})
    protocol_sha = experiment.digest(output_dir / "protocol.json")
    del rows, membership
    model, report = build(data, original["predictor"], original["threshold"])
    report.update(provenance)
    report["protocol_sha256"] = protocol_sha
    report["validation_applicability"] = {"method": "nearest training Morgan Tanimoto; no validated cutoff", "records": applicability}
    path = output_dir / "svm.joblib"
    joblib.dump({"model": model, "threshold": report["validation"]["svm"]["threshold"], "metadata": report}, path)
    restored = joblib.load(path)  # Only the artifact just produced here.
    np.testing.assert_array_equal(comparison.positive_probability(restored["model"], data["validation"]["X"]),
                                  [r["svm"] for r in report["validation_predictions"]])
    for p, expected in protected.items():
        if experiment.digest(p) != expected:
            raise ValueError("protected_input_or_artifact_changed")
    if (experiment.digest(baseline) if baseline.exists() else None) != baseline_sha:
        raise ValueError("baseline_changed_or_promoted")
    if experiment.digest(output_dir / "protocol.json") != protocol_sha:
        raise ValueError("protocol_changed_during_run")
    report["artifact"] = {"filename": path.name, "sha256": experiment.digest(path), "validation_roundtrip_exact": True, "promoted": False}
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
    report = run(args.output_dir, args.rf)
    print(json.dumps({"selected_C": report["training_selection"]["selected_C"],
                      "nested_training_cv": report["nested_training_cv"]["mean"], "validation": report["validation"]}, indent=2))


if __name__ == "__main__":
    # Serialize the callable kernel under its importable module, not __main__.
    from toxicity.src.morgan_svm import main as run_cli
    run_cli()
