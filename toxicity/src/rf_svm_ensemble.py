"""Bounded RF/Tanimoto-SVM late fusion using existing nested ensemble helpers.

Offline CPU research only. Never scores test/external data or promotes weights.
"""
from __future__ import annotations

import argparse
import json
import platform
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from toxicity.src import bionemo_candidate as candidate
from toxicity.src import bionemo_diagnostics as diagnosis
from toxicity.src import bionemo_ensemble as ensemble
from toxicity.src import bionemo_experiment as experiment
from toxicity.src import morgan_svm as svm
from toxicity.src import research_common as comparison

DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/rf_svm_ensemble_v3"
N_BOOTSTRAP = 2000
METRICS = {"auroc": roc_auc_score, "average_precision": average_precision_score, "brier": brier_score_loss}
PROTOCOL = {
    "id": "rf_svm_ensemble_v3", "rf_weight_grid": list(ensemble.WEIGHTS), "svm_C_grid": list(svm.C_VALUES),
    "verification_revision": "V1 exact reload failed at 1.11e-16; v2 probability tolerance passed but one threshold-boundary class flipped. V3 sequential joblib RF fitting/calibration and probability prediction provides deterministic summation; restore exact reload/classes checks. No metric-driven design changes.",
    "blend": "w * calibrated RF probability + (1-w) * calibrated Tanimoto SVM probability",
    "selection": "existing ensemble.choose: maximum arithmetic mean inner-fold AP jointly over C and w; exact ties higher RF weight then smaller C; pure RF is (1,None)",
    "features": "unchanged chiral Morgan radius 2, 2048 binary bits, dilirank_parent_v1",
    "folds": "same 3 outer training and 3 inner StratifiedGroupKFold folds, shuffle=True seed=42; no test/external fitting or predictions",
    "calibration": "both arms fixed sigmoid ensemble=False with 3 grouped folds inside EVERY fitting subset; SVC probability=False; no blend recalibration",
    "rf_parameters": ensemble.RF_PARAMS, "svm_parameters": svm.PROTOCOL["svc"],
    "svm_kernel": svm.PROTOCOL["kernel"],
    "controls": "RF fixed recipe; standalone SVM C selected by inner AP (weight=0); identical outer holdouts",
    "budget": "4 selection stages * 3 inner folds: 12 RF and 60 SVM calibrated fits; 3 outer RF, up to 6 outer SVM and 1 final SVM; no adaptive expansion",
    "final_rf": "verified scratch reproduction only used on validation after all model/weight choices; never used for CV",
    "threshold": "only final training-selected blend uses validation for balanced accuracy, sensitivity then lower-threshold ties; pure RF retains original threshold",
    "uncertainty": {"replicates": N_BOOTSTRAP, "base_seed": 42, "fold_seeds": [43, 44, 45], "level": .95,
                    "method": "paired percentile cluster bootstrap: resample whole scaffold/connectivity groups with replacement within each outer holdout; same sampled rows for every arm; no refitting",
                    "single_class_draws": "discard jointly for all metrics and both comparisons; report attempted and valid counts; do not redraw",
                    "mean_interval": "arithmetic mean of paired fold differences for replicate indices valid in all folds; folds not treated as independent training experiments",
                    "scope": "conditional on fitted models, chosen folds and observed groups; excludes fitting/selection variability, shared-training dependence and repeated-search uncertainty; not confirmatory"},
    "status": "exploratory follow-up after inspecting previous CV/validation/test results; no model superiority, clinical incidence or safety claim",
}


def probabilities(model, X):
    # RandomForest's parallel tree accumulation can vary by an ulp, enough to
    # cross a validation-selected threshold exactly equal to a probability.
    # The sequential backend changes execution only, never estimator parameters.
    with joblib.parallel_backend("sequential"):
        return comparison.positive_probability(model, X)


def fit_rf(train):
    with joblib.parallel_backend("sequential"):
        return ensemble.fit_rf(train, train["X"].shape[1])


def select(train):
    configurations = [(1., None)] + [(w, c) for w in ensemble.WEIGHTS if w != 1 for c in svm.C_VALUES]
    scores = {(w, c): [] for w, c in configurations}
    records = []
    for fit, hold in candidate.folds(train):
        fitting = candidate.subset(train, fit)
        rf, rf_cal = fit_rf(fitting)
        rp = probabilities(rf, train["X"][hold])
        svm_probabilities, calibration = {}, None
        for c in svm.C_VALUES:
            model, cal = svm.fit_svm(fitting, c)
            if calibration is not None and cal != calibration:
                raise ValueError("svm_calibration_folds_changed")
            calibration = cal
            svm_probabilities[c] = probabilities(model, train["X"][hold])
        for w, c in configurations:
            p = ensemble.blend(rp, svm_probabilities.get(c), w)
            scores[w, c].append(diagnosis.probability_metrics(train["y"][hold], p))
        records.append({**candidate.fold_ids(train, fit, hold), "rf_calibration_folds": rf_cal,
                        "svm_calibration_folds": calibration})
    values = [{"rf_weight": w, "C": c, "folds": measures,
               "mean_average_precision": float(np.mean([m["average_precision"] for m in measures]))}
              for (w, c), measures in scores.items()]
    return {"selected": ensemble.choose(values), "svm_control": ensemble.choose([r for r in values if r["rf_weight"] == 0]),
            "scores": values, "fold_membership": records}


def cluster_indices(groups, rng):
    groups = np.asarray(groups)
    unique = np.unique(groups)
    members = [np.flatnonzero(groups == g) for g in unique]
    return np.concatenate([members[i] for i in rng.integers(0, len(unique), size=len(unique))])


def metric_vector(y, p):
    return np.array([function(y, p) for function in METRICS.values()])


def interval_summary(point, samples):
    valid = samples[np.isfinite(samples).all(axis=1)]
    if not len(valid):
        return {"valid_replicates": 0, "metrics": {k: {"difference": float(point[i]), "percentile_95": None}
                                                 for i, k in enumerate(METRICS)}}
    bounds = np.quantile(valid, [.025, .975], axis=0)
    return {"valid_replicates": len(valid), "metrics": {k: {"difference": float(point[i]), "percentile_95": bounds[:, i].tolist()}
                                                       for i, k in enumerate(METRICS)}}


def paired_intervals(y, probabilities, groups, *, seed, n_bootstrap=N_BOOTSTRAP):
    y, groups = np.asarray(y), np.asarray(groups)
    if (y.ndim != 1 or set(y) != {0, 1} or groups.shape != y.shape
            or set(probabilities) != {"rf", "svm", "selected_blend"}):
        raise ValueError("invalid_paired_bootstrap_inputs")
    for p in probabilities.values():
        if p.shape != y.shape or not np.isfinite(p).all() or not ((p >= 0) & (p <= 1)).all():
            raise ValueError("invalid_paired_bootstrap_probabilities")
    if n_bootstrap <= 0:
        raise ValueError("invalid_bootstrap_budget")
    scores = {arm: metric_vector(y, p) for arm, p in probabilities.items()}
    points = {arm: scores["selected_blend"] - scores[arm] for arm in ("rf", "svm")}
    samples = {arm: np.full((n_bootstrap, len(METRICS)), np.nan) for arm in points}
    rng = np.random.default_rng(seed)
    for i in range(n_bootstrap):
        idx = cluster_indices(groups, rng)
        if len(np.unique(y[idx])) < 2:
            continue
        resampled = {arm: metric_vector(y[idx], p[idx]) for arm, p in probabilities.items()}
        for arm in points:
            samples[arm][i] = resampled["selected_blend"] - resampled[arm]
    result = {"attempted_replicates": n_bootstrap, "seed": seed, "n_groups": len(np.unique(groups)),
              "comparisons_blend_minus": {arm: interval_summary(points[arm], samples[arm]) for arm in points}}
    return result, samples


def predict_bundle(bundle, X):
    rp = probabilities(bundle["rf"], X)
    sp = probabilities(bundle["svm"], X) if bundle["svm"] is not None else None
    return ensemble.blend(rp, sp, bundle["rf_weight"])


def build(data, final_rf, original_threshold, checkpoint=lambda name, record: None):
    comparison.validate_development(data)
    train, valid = data["train"], data["validation"]
    outer, boot = [], []
    for number, (fit, hold) in enumerate(candidate.folds(train), 1):
        print(f"Outer training fold {number}/3: joint SVM C / RF weight selection", flush=True)
        fitting = candidate.subset(train, fit)
        selection = select(fitting)
        chosen, control = selection["selected"], selection["svm_control"]
        rf, rf_cal = fit_rf(fitting)
        rp = probabilities(rf, train["X"][hold])
        needed = sorted({c for c in (chosen["C"], control["C"]) if c is not None})
        predictions, calibrations = {}, {}
        for c in needed:
            model, calibrations[str(c)] = svm.fit_svm(fitting, c)
            predictions[c] = probabilities(model, train["X"][hold])
        scores = {"rf": rp, "svm": predictions[control["C"]],
                         "selected_blend": ensemble.blend(rp, predictions.get(chosen["C"]), chosen["rf_weight"])}
        measures = {arm: diagnosis.probability_metrics(train["y"][hold], p) for arm, p in scores.items()}
        print(f"Outer fold {number}: paired group-bootstrap intervals", flush=True)
        intervals, samples = paired_intervals(train["y"][hold], scores, train["groups"][hold], seed=42+number, n_bootstrap=N_BOOTSTRAP)
        boot.append(samples)
        record = {**candidate.fold_ids(train, fit, hold), "inner_selection": selection,
                  "rf_calibration_folds": rf_cal, "svm_calibration_folds_by_C": calibrations,
                  "metrics": measures, "paired_intervals": intervals,
                  "predictions": [{"structure_id": train["structure_ids"][i], **{arm: float(p[j]) for arm, p in scores.items()}}
                                  for j, i in enumerate(hold)]}
        outer.append(record)
        checkpoint(f"outer_fold_{number}.json", record)
    print("Final joint selection inside frozen training only", flush=True)
    selection = select(train)
    chosen = selection["selected"]
    model, cal = svm.fit_svm(train, chosen["C"]) if chosen["C"] is not None else (None, [])
    bundle = {"rf": final_rf, "svm": model, "rf_weight": chosen["rf_weight"], "C": chosen["C"]}
    p = predict_bundle(bundle, valid["X"])
    rf_p = probabilities(final_rf, valid["X"])
    threshold = original_threshold if chosen["rf_weight"] == 1 else experiment.choose_threshold(valid["y"], p)
    bundle["threshold"] = threshold
    means = {arm: {key: float(np.mean([r["metrics"][arm][key] for r in outer])) for key in outer[0]["metrics"][arm]}
             for arm in ("rf", "svm", "selected_blend")}
    aggregate = {}
    for arm in ("rf", "svm"):
        samples = np.mean(np.stack([b[arm] for b in boot]), axis=0)
        point = np.array([means["selected_blend"][k]-means[arm][k] for k in METRICS])
        aggregate[arm] = interval_summary(point, samples)
    report = {"protocol": PROTOCOL, "training_selection": selection, "final_svm_calibration_folds": cal,
              "counts": {part: {"n": len(d["y"]), "positives": int(d["y"].sum())} for part, d in data.items()},
              "nested_training_cv": {"folds": outer, "mean": means,
                                     "mean_paired_intervals_blend_minus": aggregate},
              "validation": {"selected_blend": experiment.metrics(valid["y"], p, threshold),
                             "rf": experiment.metrics(valid["y"], rf_p, original_threshold)},
              "validation_reliability": {"selected_blend": experiment.reliability(valid["y"], p), "rf": experiment.reliability(valid["y"], rf_p)},
              "validation_predictions": [{"structure_id": sid, "selected_blend": float(p[i]), "rf": float(rf_p[i])}
                                         for i, sid in enumerate(valid["structure_ids"])],
              "limitations": [PROTOCOL["status"], PROTOCOL["uncertainty"]["scope"],
                               "Three outer folds share fitting data; bootstrap intervals are conditional descriptive intervals, not an independent-CV significance test.",
                               "RF settings/calibration originally validation-selected; frozen comparator retained.",
                               "Validation thresholds selected there; sensitivity/specificity optimistic. Blended probabilities not assumed calibrated.",
                               "No new test/external scoring, automatic deployment, patient incidence or proof-of-safety claim."]}
    return bundle, report


def run(output_dir=DEFAULT_OUTPUT, rf_path=ensemble.RF_PATH):
    output_dir, rf_path = Path(output_dir), Path(rf_path)
    if output_dir.exists():
        raise ValueError("refusing_to_overwrite_rf_svm_ensemble")
    lock = Path(__file__).resolve().parents[1] / "requirements-model.lock"
    comparison.validate_locked_runtime(lock, version_lookup=version, error_prefix="runtime_mismatch")
    if experiment.digest(rf_path) != ensemble.RF_SHA256:
        raise ValueError("unverified_rf_artifact_refuse_pickle_load")
    rows, _, membership, data_sha, split_sha = experiment.load_frozen_inputs()
    data = comparison.development_data(rows, membership)
    original = joblib.load(rf_path)  # Exact hash-verified local reproduction only.
    if (original["data_sha256"] != data_sha or not original["calibrated"]
            or original["rf"].get_params() != RandomForestClassifier(**ensemble.RF_PARAMS).get_params()):
        raise ValueError("rf_identity_or_configuration_mismatch")
    for part in data:
        if [original["rows"][i]["structure_id"] for i in original[part+"_indices"]] != data[part]["structure_ids"]:
            raise ValueError("rf_partition_mismatch")
    idx = {part: [i for i, r in enumerate(rows) if membership[r["structure_id"]]["partition"] == part] for part in data}
    applicability = experiment.applicability(rows, idx["train"], idx["validation"])
    protected = {p: experiment.digest(p) for p in (experiment.DATA, experiment.SPLIT, rf_path, lock, experiment.BASELINE_REPORT,
                 experiment.ROOT / "evaluation/reports/baseline_selection.json",
                 experiment.ROOT / "artifacts/runs/morgan_svm_v1/report.json",
                 experiment.ROOT / "artifacts/runs/morgan_svm_v1/svm.joblib")}
    baseline = experiment.ROOT / "artifacts/models/dili_baseline.joblib"
    baseline_sha = experiment.digest(baseline) if baseline.exists() else None
    provenance = {"data_sha256": data_sha, "split_sha256": split_sha, "rf_reproduction_sha256": ensemble.RF_SHA256,
                  "dependency_lock_sha256": experiment.digest(lock),
                  "source_sha256": {n: experiment.digest(Path(__file__).with_name(n)) for n in
                                     ("rf_svm_ensemble.py", "morgan_svm.py", "bionemo_ensemble.py", "research_common.py",
                                      "bionemo_candidate.py", "bionemo_diagnostics.py", "bionemo_experiment.py", "baseline.py", "ingest_dilirank.py")},
                  "runtime": {"python": platform.python_version(), **{n: version(n) for n in ("numpy", "scipy", "scikit-learn", "joblib", "rdkit", "threadpoolctl")}}}
    output_dir.mkdir(parents=True, exist_ok=False)
    experiment.save_json(output_dir / "protocol.json", {**PROTOCOL, "provenance": provenance})
    protocol_sha = experiment.digest(output_dir / "protocol.json")
    del rows, membership
    bundle, report = build(data, original["predictor"], original["threshold"],
                           checkpoint=lambda name, value: experiment.save_json(output_dir / name, value))
    report.update(provenance)
    report["protocol_sha256"] = protocol_sha
    report["validation_applicability"] = {"method": "nearest training Morgan Tanimoto; no fitted cutoff", "records": applicability}
    path = output_dir / "ensemble.joblib"
    joblib.dump({**bundle, "metadata": report}, path)
    restored = joblib.load(path)  # Only the artifact just created by this process.
    reloaded = predict_bundle(restored, data["validation"]["X"])
    recorded = np.array([r["selected_blend"] for r in report["validation_predictions"]])
    np.testing.assert_array_equal(reloaded, recorded)
    np.testing.assert_array_equal(reloaded >= bundle["threshold"], recorded >= bundle["threshold"])
    for p, expected in protected.items():
        if experiment.digest(p) != expected:
            raise ValueError("protected_input_changed")
    if (experiment.digest(baseline) if baseline.exists() else None) != baseline_sha:
        raise ValueError("baseline_changed_or_promoted")
    if experiment.digest(output_dir / "protocol.json") != protocol_sha:
        raise ValueError("protocol_changed_during_run")
    report["artifact"] = {"filename": path.name, "sha256": experiment.digest(path), "validation_roundtrip_exact": True,
                          "roundtrip_max_absolute_difference": float(np.max(np.abs(reloaded-recorded))),
                          "thresholded_classes_exact": True, "promoted": False}
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
    r = run(args.output_dir, args.rf)
    print(json.dumps({"selected": r["training_selection"]["selected"], "nested_mean": r["nested_training_cv"]["mean"],
                      "mean_paired_intervals": r["nested_training_cv"]["mean_paired_intervals_blend_minus"], "validation": r["validation"]}, indent=2))


if __name__ == "__main__":
    main()
