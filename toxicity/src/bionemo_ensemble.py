"""Exploratory nested training-CV RF/embedding probability blend; no test scoring.

The existing full-training RF is used only after all ensemble choices are fixed.
Every CV RF and its sigmoid calibration are fitted within that fitting subset.
"""
from __future__ import annotations

import argparse
import json
import platform
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier

from toxicity.src import bionemo_candidate as candidate
from toxicity.src import bionemo_diagnostics as diagnosis
from toxicity.src import bionemo_experiment as experiment
from toxicity.src import bionemo_hybrid as hybrid

RF_PARAMS = dict(n_estimators=500, max_depth=None, min_samples_leaf=2,
                 class_weight=None, random_state=42, n_jobs=-1)
WEIGHTS = (0., .25, .5, .75, 1.)  # Weight on RF; embedding gets 1-weight.
C_VALUES = diagnosis.C_VALUES
RF_PATH = experiment.ROOT / "artifacts/runs/rf-reproduction-dmd67bwk/dili_baseline_reproduced.joblib"
RF_SHA256 = "acd6bbde5a64c5fb95c9f39a1433871dce5d412ef717b2b776b8cfa73fbc2345"
CACHE_SHA256 = "7990795575c2d2637e60c61d5cc8cb674b4bc6dc42970fff4047bd27b1d19397"
DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/bionemo_ensemble_v1"
PROTOCOL = {
    "id": "bionemo_ensemble_v1", "rf_parameters": RF_PARAMS,
    "rf_weight_grid": list(WEIGHTS), "embedding_C_grid": list(C_VALUES),
    "blend": "w * RF_positive_probability + (1-w) * embedding_logistic_probability",
    "selection": "maximum arithmetic mean inner-fold AP jointly over C and w; ties favor higher RF weight then smaller C",
    "cv": "identical shuffled 3-fold StratifiedGroupKFold seed=42, inside frozen training only",
    "nested": "3 outer training folds; all C/weight selection inside 3 inner folds of each outer fitting subset",
    "rf_calibration": "fixed sigmoid, ensemble=False, 3 grouped fitting-subset folds; never calibrate on selection or outer holdouts",
    "embedding": "existing MegaMolBART cache; per-fitting-fold StandardScaler and L2 logistic, max_iter=5000, seed=42",
    "final_rf": "reuse checksum-verified functional reproduction after selection; never use it for CV predictions",
    "threshold": "validation balanced accuracy, sensitivity then lower threshold tie-break; pure RF retains its existing threshold",
    "blend_calibration": "none fitted; Brier/reliability assessed without assuming calibrated blend",
    "test": "no test labels extracted or predictions generated; whole-input integrity verification only",
    "status": "exploratory: repeated development analysis and prior test inspection; not confirmatory",
}


def fit_rf(train, n_morgan):
    split = candidate.folds(train)
    model = CalibratedClassifierCV(RandomForestClassifier(**RF_PARAMS), method="sigmoid",
                                  cv=split, ensemble=False)
    model.fit(train["X"][:, :n_morgan], train["y"])
    return model, [candidate.fold_ids(train, fit, hold) for fit, hold in split]


def fit_embedding(train, c, n_morgan):
    return diagnosis.fit_checked(hybrid.make_model("embedding", c, n_morgan), train["X"], train["y"])


def blend(rf_p, embedding_p, weight):
    if weight not in WEIGHTS:
        raise ValueError("unregistered_rf_weight")
    if weight == 1:
        return rf_p.copy()
    if embedding_p is None or rf_p.shape != embedding_p.shape:
        raise ValueError("missing_or_misaligned_embedding_predictions")
    return weight * rf_p + (1 - weight) * embedding_p


def choose(scores):
    best = max(scores, key=lambda r: (r["mean_average_precision"], r["rf_weight"],
                                     -(r["C"] if r["C"] is not None else 0.)))
    return {k: best[k] for k in ("rf_weight", "C", "mean_average_precision")}


def select(train, n_morgan):
    split = candidate.folds(train)
    configurations = [(1., None)] + [(w, c) for w in WEIGHTS if w != 1 for c in C_VALUES]
    scores = {(w, c): [] for w, c in configurations}
    fold_records = []
    for fit, hold in split:
        fitting = candidate.subset(train, fit)
        rf, calibration = fit_rf(fitting, n_morgan)
        rp = rf.predict_proba(train["X"][hold, :n_morgan])[:, 1]
        embeddings = {c: fit_embedding(fitting, c, n_morgan).predict_proba(train["X"][hold])[:, 1]
                      for c in C_VALUES}
        for w, c in configurations:
            p = blend(rp, embeddings.get(c), w)
            scores[w, c].append(diagnosis.probability_metrics(train["y"][hold], p))
        fold_records.append({**candidate.fold_ids(train, fit, hold), "rf_calibration_folds": calibration})
    records = [{"rf_weight": w, "C": c, "folds": metrics,
                "mean_average_precision": float(np.mean([m["average_precision"] for m in metrics]))}
               for (w, c), metrics in scores.items()]
    return {"selected": choose(records), "embedding_control": choose([r for r in records if r["rf_weight"] == 0]),
            "scores": records, "fold_membership": fold_records}


def predict_bundle(bundle, X):
    rp = bundle["rf"].predict_proba(X[:, :bundle["n_morgan"]])[:, 1]
    ep = bundle["embedding"].predict_proba(X)[:, 1] if bundle["embedding"] is not None else None
    return blend(rp, ep, bundle["rf_weight"])


def build(development, final_rf, original_threshold, n_morgan=2048):
    if set(development) != {"train", "validation"}:
        raise ValueError("only_development_partitions_allowed")
    train, valid = development["train"], development["validation"]
    if set(train["groups"]) & set(valid["groups"]) or set(train["structure_ids"]) & set(valid["structure_ids"]):
        raise ValueError("development_overlap")
    if train["X"].shape[1] <= n_morgan or train["X"].shape[1] != valid["X"].shape[1]:
        raise ValueError("invalid_feature_dimensions")
    outer_records = []
    for number, (fit, hold) in enumerate(candidate.folds(train), 1):
        print(f"Outer training fold {number}/3", flush=True)
        fitting = candidate.subset(train, fit)
        selection = select(fitting, n_morgan)
        chosen = selection["selected"]
        rf, calibration = fit_rf(fitting, n_morgan)
        rp = rf.predict_proba(train["X"][hold, :n_morgan])[:, 1]
        c_control = selection["embedding_control"]["C"]
        needed = {c for c in (c_control, chosen["C"]) if c is not None}
        embeddings = {c: fit_embedding(fitting, c, n_morgan).predict_proba(train["X"][hold])[:, 1] for c in needed}
        probabilities = {"rf": rp, "embedding": embeddings[c_control],
                         "selected_blend": blend(rp, embeddings.get(chosen["C"]), chosen["rf_weight"])}
        outer_records.append({**candidate.fold_ids(train, fit, hold), "inner_selection": selection,
                              "rf_calibration_folds": calibration,
                              "metrics": {arm: diagnosis.probability_metrics(train["y"][hold], p) for arm, p in probabilities.items()},
                              "predictions": [{"structure_id": train["structure_ids"][i],
                                               **{arm: float(p[j]) for arm, p in probabilities.items()}}
                                              for j, i in enumerate(hold)]})
    print("Final selection within all 539 training compounds (or synthetic test fixture)", flush=True)
    selection = select(train, n_morgan)
    chosen = selection["selected"]
    embedding = fit_embedding(train, chosen["C"], n_morgan) if chosen["C"] is not None else None
    bundle = {"rf": final_rf, "embedding": embedding, "rf_weight": chosen["rf_weight"],
              "C": chosen["C"], "n_morgan": n_morgan}
    # The pre-existing full-training RF is first used here, after model selection.
    p = predict_bundle(bundle, valid["X"])
    threshold = original_threshold if chosen["rf_weight"] == 1 else experiment.choose_threshold(valid["y"], p)
    bundle["threshold"] = threshold
    mean = {arm: {key: float(np.mean([r["metrics"][arm][key] for r in outer_records]))
                  for key in outer_records[0]["metrics"][arm]} for arm in ("rf", "embedding", "selected_blend")}
    report = {"protocol": PROTOCOL, "training_selection": selection,
              "counts": {part: {"n": len(d["y"]), "positive": int(d["y"].sum())} for part, d in development.items()},
              "nested_training_cv": {"folds": outer_records, "mean": mean},
              "validation": experiment.metrics(valid["y"], p, threshold),
              "validation_reliability": experiment.reliability(valid["y"], p),
              "validation_predictions": [{"structure_id": sid, "positive_probability": float(prob)}
                                         for sid, prob in zip(valid["structure_ids"], p)],
              "limitations": ["Exploratory; prior test inspection and repeated development-data use.",
                              "RF hyperparameters/calibration choice were originally validation-selected; held fixed here.",
                              "Nested training metrics are not independent test evidence or an improvement claim.",
                              "Unknown exact representation-pretraining overlap; blended probabilities are not assumed calibrated.",
                              "Compound-level concern, not patient incidence or proof of safety.",
                              "Original teammate RF still preferred; functional reproduction is preserved, not promoted."]}
    return bundle, report


def run(output_dir=DEFAULT_OUTPUT, cache_path=diagnosis.DEFAULT_CACHE, rf_path=RF_PATH):
    output_dir, cache_path, rf_path = map(Path, (output_dir, cache_path, rf_path))
    if output_dir.exists():
        raise ValueError("refusing_to_overwrite_ensemble_directory")
    if experiment.digest(rf_path) != RF_SHA256:
        raise ValueError("unverified_rf_artifact_refuse_pickle_load")
    if experiment.digest(cache_path) != CACHE_SHA256:
        raise ValueError("ensemble_embedding_cache_changed")
    rows, _, membership, data_hash, split_hash = experiment.load_frozen_inputs()
    cache = json.loads(cache_path.read_text())
    matrix = experiment.validate_cache(cache, rows, data_hash, split_hash)
    development = hybrid.development_data(rows, membership, matrix)
    indices = {part: [i for i, row in enumerate(rows) if membership[row["structure_id"]]["partition"] == part]
               for part in ("train", "validation")}
    applicability = experiment.applicability(rows, indices["train"], indices["validation"])
    original = joblib.load(rf_path)  # Exact artifact generated and verified locally; hash checked before loading.
    if original["data_sha256"] != data_hash or not original["calibrated"]:
        raise ValueError("rf_identity_or_calibration_mismatch")
    if original["rf"].get_params() != RandomForestClassifier(**RF_PARAMS).get_params():
        raise ValueError("rf_configuration_mismatch")
    for part in ("train", "validation"):
        ids = [original["rows"][i]["structure_id"] for i in original[part + "_indices"]]
        if ids != development[part]["structure_ids"]:
            raise ValueError("rf_partition_identity_mismatch")
    del rows, membership, matrix
    output_dir.mkdir(parents=True, exist_ok=False)
    experiment.save_json(output_dir / "protocol.json", PROTOCOL)  # Written before fitting or selecting.
    bundle, report = build(development, original["predictor"], original["threshold"])
    report.update({"data_sha256": data_hash, "split_sha256": split_hash,
                   "rf_reproduction_sha256": RF_SHA256, "cache_sha256": CACHE_SHA256,
                   "representation": {k: cache[k] for k in ("model_id", "model_version", "embedding_dimension", "preprocessing_version")},
                   "source_sha256": {name: experiment.digest(Path(__file__).with_name(name)) for name in
                                     ("bionemo_ensemble.py", "bionemo_hybrid.py", "bionemo_candidate.py", "bionemo_diagnostics.py",
                                      "bionemo_experiment.py", "baseline.py", "ingest_dilirank.py")},
                   "runtime": {"python": platform.python_version(), **{name: version(name) for name in
                               ("numpy", "scipy", "scikit-learn", "joblib", "rdkit")}},
                   "validation_applicability": {"method": "nearest training Morgan radius-2 2048-bit Tanimoto", "records": applicability}})
    path = output_dir / "ensemble.joblib"
    joblib.dump({**bundle, "metadata": report}, path)
    restored = joblib.load(path)
    np.testing.assert_allclose(predict_bundle(restored, development["validation"]["X"]),
                               [r["positive_probability"] for r in report["validation_predictions"]], rtol=0, atol=1e-14)
    if experiment.digest(rf_path) != RF_SHA256:
        raise ValueError("original_scratch_rf_changed")
    report["artifact"] = {"filename": path.name, "sha256": experiment.digest(path),
                          "validation_roundtrip_atol": 1e-14, "promoted": False}
    experiment.save_json(output_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=diagnosis.DEFAULT_CACHE)
    parser.add_argument("--rf", type=Path, default=RF_PATH)
    args = parser.parse_args()
    report = run(args.output_dir, args.cache, args.rf)
    print(json.dumps({"selected": report["training_selection"]["selected"],
                      "nested_training_cv": report["nested_training_cv"]["mean"],
                      "validation": report["validation"]}, indent=2))


if __name__ == "__main__":
    main()
