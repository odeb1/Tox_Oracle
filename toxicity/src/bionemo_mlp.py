"""Offline, bounded Morgan-vs-BioNeMo MLP research; no test-set predictions.

Joint representation/head selection is nested entirely within frozen training.
Only the training-selected MLP reaches validation. Existing RF stays unchanged.
"""
from __future__ import annotations

import argparse
import itertools
import json
import platform
import warnings
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from toxicity.src import bionemo_candidate as candidate
from toxicity.src import bionemo_diagnostics as diagnosis
from toxicity.src import bionemo_ensemble as ensemble
from toxicity.src import bionemo_experiment as experiment
from toxicity.src import bionemo_hybrid as hybrid
from toxicity.src import research_common as comparison

ARMS = ("morgan", "embedding")
GRID = tuple(dict(arm=arm, hidden=hidden, alpha=alpha)
             for arm, hidden, alpha in itertools.product(ARMS, (16, 32), (100., 10., 1.)))
PRIMARY_SEED = 42
SENSITIVITY_SEEDS = (43, 44)
FIXED = dict(activation="tanh", solver="lbfgs", max_iter=2000, max_fun=50000,
             tol=1e-4, early_stopping=False)
DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/bionemo_mlp_v2"
PROTOCOL = {
    "id": "bionemo_mlp_v2", "grid": list(GRID), "fixed_mlp_parameters": FIXED,
    "revision": "v1 ReLU/L-BFGS hit its iteration cap in the first outer fold's inner fitting; no completed outer/validation result. One numerical retry uses smooth tanh; same grid/splits/budget, no metric-driven expansion. v1 protocol/failure/source snapshot preserved.",
    "primary_seed": PRIMARY_SEED, "sensitivity_seeds": list(SENSITIVITY_SEEDS),
    "representation": "Morgan radius=2 bits=2048 chirality=True OR frozen checksum-verified MegaMolBART embeddings; no feature concatenation used by a head",
    "scaling": "StandardScaler on selected columns only, fitted within each fitting subset (also for Morgan bits)",
    "selection": "max arithmetic mean inner-fold AP jointly over arm/hidden/alpha; exact ties use grid order: Morgan, fewer hidden units, stronger L2",
    "nested_cv": "identical 3-fold StratifiedGroupKFold shuffle=True seed=42; 3 inner folds within each of 3 outer training fitting subsets",
    "rf_comparator": "fixed original RF recipe; sigmoid calibration refitted using 3 grouped folds within each outer fitting subset; no retuning",
    "convergence": "any ConvergenceWarning or nonfinite weights/loss aborts the experiment; never silently drop configurations",
    "seed_sensitivity": "after primary-seed selection, evaluate both per-arm selected configurations at seeds 43/44 in 3 training folds; descriptive non-nested sensitivity only, never choose seed or change selection",
    "budget": "144 primary grid fits + 6 outer selected-per-arm fits + 1 final selected fit + 12 sensitivity fits = 163 MLP fits; no adaptive expansion",
    "validation": "only final training-selected MLP; balanced-accuracy threshold, sensitivity then lower threshold ties; unchanged RF uses existing threshold",
    "calibration": "no MLP calibration fitted; Brier/reliability assessed because outputs are probabilities, not assumed calibrated",
    "test": "no test-label array extraction or predictions; whole-source/cache integrity checks only",
    "external_data": "none",
    "runtime": "existing model lock; CPU; BLAS/OpenMP limited to one thread during MLP fit and prediction; no network or GPU",
    "status": "exploratory, after prior test inspection and repeated development-data analysis; not confirmatory",
}


def validate_development(data, n_morgan):
    if set(data) != {"train", "validation"}:
        raise ValueError("only_development_partitions_allowed")
    if not isinstance(n_morgan, int) or n_morgan < 1:
        raise ValueError("invalid_feature_dimensions")
    for d in data.values():
        if (d["X"].ndim != 2 or d["X"].shape[1] <= n_morgan
                or not np.isfinite(d["X"]).all()):
            raise ValueError("invalid_feature_dimensions_or_values")
    if data["train"]["X"].shape[1] != data["validation"]["X"].shape[1]:
        raise ValueError("invalid_feature_dimensions")
    comparison.validate_development({p: {**d, "X": d["X"][:, :n_morgan]} for p, d in data.items()})


def make_model(config, n_morgan, seed=PRIMARY_SEED):
    if config not in GRID or seed not in (PRIMARY_SEED, *SENSITIVITY_SEEDS) or n_morgan < 1:
        raise ValueError("unregistered_mlp_configuration")
    columns = slice(0, n_morgan) if config["arm"] == "morgan" else slice(n_morgan, None)
    return Pipeline([
        ("features", ColumnTransformer([("scale", StandardScaler(), columns)], remainder="drop")),
        ("mlp", MLPClassifier(hidden_layer_sizes=(config["hidden"],), alpha=config["alpha"],
                              random_state=seed, **FIXED)),
    ])


def fit_checked(model, X, y):
    try:
        with threadpool_limits(limits=1), warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            model.fit(X, y)
    except ConvergenceWarning as exc:
        raise ValueError("mlp_did_not_converge") from exc
    head = model.named_steps["mlp"]
    if not np.isfinite(head.loss_) or any(not np.isfinite(w).all() for w in head.coefs_ + head.intercepts_):
        raise ValueError("nonfinite_mlp_fit")
    return model


def probabilities(model, X):
    with threadpool_limits(limits=1):
        return comparison.positive_probability(model, X)


def diagnostics(model):
    head = model.named_steps["mlp"]
    return {"iterations": int(head.n_iter_), "training_objective": float(head.loss_),
            "input_dimensions": int(head.n_features_in_),
            "parameters": int(sum(w.size for w in head.coefs_ + head.intercepts_))}


def choose(scores):
    row = max(scores, key=lambda r: (r["mean_average_precision"], -r["grid_index"]))
    return dict(row["config"])


def select(train, n_morgan):
    splits = candidate.folds(train)
    scores = []
    for number, config in enumerate(GRID):
        if number == 0 or config["arm"] != GRID[number - 1]["arm"]:
            print(f"  Training CV: {config['arm']}, {len(train['y'])} fitting-cohort compounds", flush=True)
        values, fits = [], []
        for fold_number, (fit, hold) in enumerate(splits, 1):
            try:
                model = fit_checked(make_model(config, n_morgan), train["X"][fit], train["y"][fit])
            except ValueError as exc:
                raise ValueError(f"training_selection_failed:{config}:fold={fold_number}:{exc}") from exc
            p = probabilities(model, train["X"][hold])
            values.append(diagnosis.probability_metrics(train["y"][hold], p))
            fits.append(diagnostics(model))
        scores.append({"grid_index": number, "config": config, "folds": values, "fit_diagnostics": fits,
                       "mean_average_precision": float(np.mean([r["average_precision"] for r in values]))})
    return {"selected": choose(scores), "scores": scores,
            "per_arm": {arm: choose([r for r in scores if r["config"]["arm"] == arm]) for arm in ARMS},
            "fold_membership": [candidate.fold_ids(train, fit, hold) for fit, hold in splits]}


def seed_sensitivity(train, selection, n_morgan):
    splits = candidate.folds(train)
    result = []
    for arm, config in selection["per_arm"].items():
        primary = next(r for r in selection["scores"] if r["config"] == config)
        result.append({"arm": arm, "config": config, "seed": PRIMARY_SEED, "folds": primary["folds"],
                       "mean_average_precision": primary["mean_average_precision"]})
        for seed in SENSITIVITY_SEEDS:
            values = []
            for fit, hold in splits:
                model = fit_checked(make_model(config, n_morgan, seed), train["X"][fit], train["y"][fit])
                values.append(diagnosis.probability_metrics(train["y"][hold], probabilities(model, train["X"][hold])))
            result.append({"arm": arm, "config": config, "seed": seed, "folds": values,
                           "mean_average_precision": float(np.mean([v["average_precision"] for v in values]))})
    return {"purpose": "non-nested training-only sensitivity; not a new model-selection score", "records": result,
            "fold_membership": [candidate.fold_ids(train, fit, hold) for fit, hold in splits]}


def build(data, final_rf, rf_threshold, n_morgan=2048, checkpoint=None):
    validate_development(data, n_morgan)
    train, valid = data["train"], data["validation"]
    names = ("rf", *ARMS, "selected_procedure")
    oof = {arm: np.full(len(train["y"]), np.nan) for arm in names}
    outer = []
    for number, (fit, hold) in enumerate(candidate.folds(train), 1):
        print(f"Outer training fold {number}/3: select Morgan and BioNeMo MLPs", flush=True)
        fitting = candidate.subset(train, fit)
        selection = select(fitting, n_morgan)
        rf, calibration = ensemble.fit_rf(fitting, n_morgan)
        scores = {"rf": probabilities(rf, train["X"][hold, :n_morgan])}
        fit_info = {}
        for arm, config in selection["per_arm"].items():
            model = fit_checked(make_model(config, n_morgan), fitting["X"], fitting["y"])
            scores[arm] = probabilities(model, train["X"][hold])
            fit_info[arm] = diagnostics(model)
        scores["selected_procedure"] = scores[selection["selected"]["arm"]]
        for arm, p in scores.items():
            if not np.isnan(oof[arm][hold]).all():
                raise ValueError("duplicate_oof_assignment")
            oof[arm][hold] = p
        measures = {arm: diagnosis.probability_metrics(train["y"][hold], p) for arm, p in scores.items()}
        record = {**candidate.fold_ids(train, fit, hold), "inner_selection": selection,
                  "rf_calibration_folds": calibration, "metrics": measures, "fit_diagnostics": fit_info,
                  "delta_vs_rf": {arm: {k: measures[arm][k] - measures["rf"][k]
                                         for k in ("auroc", "average_precision", "brier")} for arm in names if arm != "rf"}}
        outer.append(record)
        if checkpoint is not None:
            checkpoint(f"outer_fold_{number}.json", record)
    if any(not np.isfinite(p).all() for p in oof.values()):
        raise ValueError("incomplete_oof_coverage")
    print("Final representation/settings selection within all frozen training", flush=True)
    selection = select(train, n_morgan)
    print("Training-only seed sensitivity (no seed selection)", flush=True)
    sensitivity = seed_sensitivity(train, selection, n_morgan)
    config = selection["selected"]
    model = fit_checked(make_model(config, n_morgan), train["X"], train["y"])
    # No validation predictions until arm, hyperparameters AND primary seed are fixed.
    vp = {"selected_mlp": probabilities(model, valid["X"]),
          "rf": probabilities(final_rf, valid["X"][:, :n_morgan])}
    threshold = experiment.choose_threshold(valid["y"], vp["selected_mlp"])
    report = {
        "protocol": PROTOCOL, "training_selection": selection, "seed_sensitivity": sensitivity,
        "counts": {p: {"n": len(d["y"]), "positive": int(d["y"].sum())} for p, d in data.items()},
        "feature_dimensions": {"morgan": n_morgan, "embedding": train["X"].shape[1] - n_morgan},
        "final_fit_diagnostics": diagnostics(model),
        "nested_training_cv": {
            "folds": outer, "mean": {arm: {k: float(np.mean([r["metrics"][arm][k] for r in outer]))
                                           for k in outer[0]["metrics"][arm]} for arm in names},
            "pooled_oof_metrics": {arm: diagnosis.probability_metrics(train["y"], p) for arm, p in oof.items()},
            "pooled_oof_reliability": {arm: experiment.reliability(train["y"], p) for arm, p in oof.items()},
            "predictions": [{"structure_id": sid, **{arm: float(p[i]) for arm, p in oof.items()}}
                            for i, sid in enumerate(train["structure_ids"])],
        },
        "validation": {arm: experiment.metrics(valid["y"], p, threshold if arm == "selected_mlp" else rf_threshold)
                       for arm, p in vp.items()},
        "validation_reliability": {arm: experiment.reliability(valid["y"], p) for arm, p in vp.items()},
        "validation_predictions": [{"structure_id": sid, **{arm: float(p[i]) for arm, p in vp.items()}}
                                   for i, sid in enumerate(valid["structure_ids"])],
        "limitations": [
            "Exploratory: previous test inspection and repeated development analysis; not independent confirmation.",
            "RF configuration/calibration originally validation-selected; held fixed here, not retuned.",
            "Identical hidden widths do not mean equal parameter counts for 2048-bit vs embedding inputs.",
            "Seed sensitivity uses primary-selected settings on training CV; descriptive, not nested confirmation.",
            "MLP outputs assessed as probabilities, not assumed clinically calibrated; no calibration fitted.",
            "Scaffold/connectivity checks do not rule out every analogue/tautomer relationship.",
            "Exact representation-pretraining compound overlap remains unknown.",
            "No test or external predictions; no claim of RF superiority or inferiority on unseen data.",
            "Compound-level DILI concern, not patient incidence or proof of safety.",
            "Original teammate RF preferred if recovered; scratch reproduction not promoted.",
        ],
    }
    return model, report


def run(output_dir=DEFAULT_OUTPUT, cache_path=diagnosis.DEFAULT_CACHE, rf_path=ensemble.RF_PATH):
    output_dir, cache_path, rf_path = map(Path, (output_dir, cache_path, rf_path))
    if output_dir.exists():
        raise ValueError("refusing_to_overwrite_mlp_directory")
    lock = Path(__file__).resolve().parents[1] / "requirements-model.lock"
    comparison.validate_locked_runtime(lock, version_lookup=version)
    if experiment.digest(rf_path) != ensemble.RF_SHA256:
        raise ValueError("unverified_rf_artifact_refuse_pickle_load")
    if experiment.digest(cache_path) != ensemble.CACHE_SHA256:
        raise ValueError("embedding_cache_changed")
    rows, _, membership, data_sha, split_sha = experiment.load_frozen_inputs()
    cache = json.loads(cache_path.read_text())
    matrix = experiment.validate_cache(cache, rows, data_sha, split_sha)
    data = hybrid.development_data(rows, membership, matrix)
    original = joblib.load(rf_path)  # Exact hash-verified, locally produced artifact only.
    if (original["data_sha256"] != data_sha or not original["calibrated"]
            or original["rf"].get_params() != RandomForestClassifier(**ensemble.RF_PARAMS).get_params()):
        raise ValueError("rf_identity_or_configuration_mismatch")
    for part in data:
        if [original["rows"][i]["structure_id"] for i in original[part + "_indices"]] != data[part]["structure_ids"]:
            raise ValueError("rf_partition_identity_mismatch")
    idx = {part: [i for i, r in enumerate(rows) if membership[r["structure_id"]]["partition"] == part] for part in data}
    applicability = experiment.applicability(rows, idx["train"], idx["validation"])
    paths = [experiment.DATA, experiment.SPLIT, rf_path, cache_path, lock, experiment.BASELINE_REPORT,
             experiment.ROOT / "evaluation/reports/baseline_selection.json"]
    protected = {p: experiment.digest(p) for p in paths}
    baseline = experiment.ROOT / "artifacts/models/dili_baseline.joblib"
    baseline_sha = experiment.digest(baseline) if baseline.exists() else None
    provenance = {
        "data_sha256": data_sha, "split_sha256": split_sha, "cache_sha256": ensemble.CACHE_SHA256,
        "rf_reproduction_sha256": ensemble.RF_SHA256, "dependency_lock_sha256": experiment.digest(lock),
        "representation": {k: cache[k] for k in ("model_id", "model_version", "embedding_dimension", "preprocessing_version")},
        "source_sha256": {name: experiment.digest(Path(__file__).with_name(name)) for name in
                          ("bionemo_mlp.py", "research_common.py", "bionemo_ensemble.py", "bionemo_candidate.py",
                           "bionemo_hybrid.py", "bionemo_diagnostics.py", "bionemo_experiment.py", "baseline.py", "ingest_dilirank.py")},
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    **{n: version(n) for n in ("numpy", "scipy", "scikit-learn", "rdkit", "joblib", "threadpoolctl")}},
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    experiment.save_json(output_dir / "protocol.json", {**PROTOCOL, "provenance": provenance})
    protocol_sha = experiment.digest(output_dir / "protocol.json")
    del rows, membership, matrix
    def checkpoint(name, record):
        experiment.save_json(output_dir / name, record)
    try:
        model, report = build(data, original["predictor"], original["threshold"], checkpoint=checkpoint)
    except ValueError as exc:
        experiment.save_json(output_dir / "failure.json", {"status": "incomplete", "error": str(exc),
                                                         "protocol_sha256": protocol_sha})
        raise
    report.update(provenance)
    report["protocol_sha256"] = protocol_sha
    report["validation_applicability"] = {"method": "nearest training Morgan radius-2 2048-bit Tanimoto; no validated cutoff", "records": applicability}
    path = output_dir / "selected_mlp.joblib"
    joblib.dump({"model": model, "selected": report["training_selection"]["selected"],
                 "threshold": report["validation"]["selected_mlp"]["threshold"], "metadata": report}, path)
    restored = joblib.load(path)  # Only our just-created artifact.
    np.testing.assert_array_equal(probabilities(restored["model"], data["validation"]["X"]),
                                  [r["selected_mlp"] for r in report["validation_predictions"]])
    for p, expected in protected.items():
        if experiment.digest(p) != expected:
            raise ValueError("protected_input_or_artifact_changed")
    if (experiment.digest(baseline) if baseline.exists() else None) != baseline_sha:
        raise ValueError("baseline_artifact_changed_or_promoted")
    if experiment.digest(output_dir / "protocol.json") != protocol_sha:
        raise ValueError("protocol_changed_during_run")
    report["artifact"] = {"filename": path.name, "sha256": experiment.digest(path),
                          "validation_roundtrip_exact": True, "promoted": False}
    experiment.save_json(output_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=diagnosis.DEFAULT_CACHE)
    parser.add_argument("--rf", type=Path, default=ensemble.RF_PATH)
    parser.add_argument("--print-protocol", action="store_true")
    args = parser.parse_args()
    if args.print_protocol:
        print(json.dumps(PROTOCOL, indent=2))
        return
    report = run(args.output_dir, args.cache, args.rf)
    print(json.dumps({"selected": report["training_selection"]["selected"],
                      "nested_training_cv": report["nested_training_cv"]["mean"],
                      "validation": report["validation"]}, indent=2))


if __name__ == "__main__":
    main()
