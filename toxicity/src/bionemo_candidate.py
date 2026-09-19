"""Freeze an exploratory regularized embedding candidate, without test scoring.

Select C by training-grouped CV average precision. Nested training-only CV assesses
the selection procedure descriptively. Validation chooses only the final threshold.
Never writes to the RF artifact path or changes the shared inference contract.
"""
from __future__ import annotations

import argparse
import json
import platform
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

from toxicity.src import bionemo_diagnostics as diagnosis
from toxicity.src import bionemo_experiment as experiment

DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/megamolbart_regularized_candidate_v1"
PROTOCOL = {
    "id": "megamolbart_regularized_candidate_v1",
    "C_values": list(diagnosis.C_VALUES),
    "selection": "maximum arithmetic mean training-CV average precision; exact tie: smallest C",
    "cv": "3-fold StratifiedGroupKFold, shuffled, seed 42, scaffold/connectivity groups",
    "nested_cv": "3 outer training-only folds; repeat selection in 3 inner folds of each outer fitting subset",
    "preprocessing": "StandardScaler refit only on each fitting subset; no feature selection",
    "threshold": "validation balanced accuracy; sensitivity then lower threshold tie-break",
    "calibration": "none; probability calibration is assessed, not assumed",
    "test": "not scored or used for fitting, C selection, calibration or thresholding",
    "status": "exploratory follow-up after inspecting original experiment; not preregistered confirmatory evidence",
}


def folds(data):
    result = list(StratifiedGroupKFold(3, shuffle=True, random_state=42).split(
        data["X"], data["y"], data["groups"]))
    for fit, hold in result:
        if set(data["groups"][fit]) & set(data["groups"][hold]):
            raise ValueError("cv_group_overlap")
        if any(len(np.unique(data["y"][idx])) != 2 for idx in (fit, hold)):
            raise ValueError("cv_requires_both_classes")
    return result


def subset(data, indices):
    return {"X": data["X"][indices], "y": data["y"][indices],
            "groups": data["groups"][indices],
            "structure_ids": [data["structure_ids"][i] for i in indices]}


def fold_ids(data, fit, hold):
    return {"fit_ids": [data["structure_ids"][i] for i in fit],
            "holdout_ids": [data["structure_ids"][i] for i in hold]}


def choose_c(scores):
    return max(scores, key=lambda row: (row["mean_average_precision"], -row["C"]))["C"]


def select_on_training(train):
    split = folds(train)
    scores = []
    for c in diagnosis.C_VALUES:
        fold_scores = []
        for fit, hold in split:
            model = diagnosis.fit_checked(diagnosis.make_model(c), train["X"][fit], train["y"][fit])
            fold_scores.append(diagnosis.probability_metrics(
                train["y"][hold], model.predict_proba(train["X"][hold])[:, 1]))
        scores.append({"C": c, "folds": fold_scores,
                       "mean_average_precision": float(np.mean([r["average_precision"] for r in fold_scores]))})
    return {"selected_C": choose_c(scores), "scores": scores,
            "fold_membership": [fold_ids(train, fit, hold) for fit, hold in split]}


def build_candidate(development):
    train, valid = development["train"], development["validation"]
    if set(train["groups"]) & set(valid["groups"]):
        raise ValueError("development_group_overlap")
    outer_records = []
    for fit, hold in folds(train):
        selected = select_on_training(subset(train, fit))
        model = diagnosis.fit_checked(diagnosis.make_model(selected["selected_C"]),
                                      train["X"][fit], train["y"][fit])
        score = diagnosis.probability_metrics(train["y"][hold], model.predict_proba(train["X"][hold])[:, 1])
        outer_records.append({**fold_ids(train, fit, hold), "inner_selection": selected,
                              "outer_holdout_metrics": score})
    selection = select_on_training(train)
    model = diagnosis.fit_checked(diagnosis.make_model(selection["selected_C"]), train["X"], train["y"])
    p = model.predict_proba(valid["X"])[:, 1]
    threshold = experiment.choose_threshold(valid["y"], p)
    report = {
        "protocol": PROTOCOL,
        "counts": {part: {"n": len(d["y"]), "positive": int(d["y"].sum())}
                   for part, d in development.items()},
        "training_selection": selection,
        "nested_training_cv": {"folds": outer_records,
            "mean": {k: float(np.mean([r["outer_holdout_metrics"][k] for r in outer_records]))
                     for k in outer_records[0]["outer_holdout_metrics"]}},
        "validation": {**experiment.metrics(valid["y"], p, threshold), **diagnosis.probability_metrics(valid["y"], p)},
        "validation_reliability": experiment.reliability(valid["y"], p),
        "validation_predictions": [{"structure_id": sid, "positive_probability": float(probability)}
                                   for sid, probability in zip(valid["structure_ids"], p)],
        "limitations": [
            "Repeated use of development data and prior test inspection make this exploratory.",
            "Nested training CV does not restore a fresh independent confirmatory evaluation.",
            "No evidence here of superiority to RF; no clinical calibration, patient incidence or safety claim.",
            "Exact ZINC15 pretraining overlap is unknown.",
        ],
    }
    return model, report


def run(cache_path=diagnosis.DEFAULT_CACHE, output_dir=DEFAULT_OUTPUT):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError("refusing_to_overwrite_candidate_directory")
    rows, _, membership, data_hash, split_hash = experiment.load_frozen_inputs()
    cache = json.loads(Path(cache_path).read_text())
    matrix = experiment.validate_cache(cache, rows, data_hash, split_hash)
    development = diagnosis.development_data(rows, membership, matrix)
    indices = {part: [i for i, row in enumerate(rows) if membership[row["structure_id"]]["partition"] == part]
               for part in ("train", "validation")}
    applicability = experiment.applicability(rows, indices["train"], indices["validation"])
    del rows, membership, matrix
    model, report = build_candidate(development)
    report.update({
        "data_sha256": data_hash, "split_manifest_sha256": split_hash,
        "cache_sha256": experiment.digest(cache_path),
        "source_sha256": {name: experiment.digest(Path(__file__).with_name(name)) for name in
                          ("bionemo_candidate.py", "bionemo_diagnostics.py", "bionemo_experiment.py")},
        "representation": {k: cache[k] for k in ("model_id", "model_version", "embedding_dimension", "preprocessing_version")},
        "runtime": {"python": platform.python_version(), **{name: version(name) for name in
                    ("numpy", "scipy", "scikit-learn", "joblib", "rdkit")}},
        "validation_applicability": {"method": "nearest training Morgan radius-2 2048-bit Tanimoto",
                                      "records": applicability},
    })
    output_dir.mkdir(parents=True, exist_ok=False)
    model_path = output_dir / "candidate.joblib"
    joblib.dump({"model": model, "threshold": report["validation"]["threshold"],
                 "metadata": report}, model_path)
    # Only load our own freshly written trusted artifact, never arbitrary pickle input.
    restored = joblib.load(model_path)
    expected = [r["positive_probability"] for r in report["validation_predictions"]]
    np.testing.assert_array_equal(restored["model"].predict_proba(development["validation"]["X"])[:, 1], expected)
    report["artifact"] = {"filename": model_path.name, "sha256": experiment.digest(model_path),
                          "validation_roundtrip_exact": True, "production_integration": "none"}
    experiment.save_json(output_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=diagnosis.DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args.cache, args.output_dir)
    print(json.dumps({"output_dir": str(args.output_dir), "selected_C": report["training_selection"]["selected_C"],
                      "nested_training_cv": report["nested_training_cv"]["mean"],
                      "validation": report["validation"]}, indent=2))


if __name__ == "__main__":
    main()
