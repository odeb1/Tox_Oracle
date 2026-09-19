"""Exploratory training-only selection of Morgan, BioNeMo and hybrid logistic heads.

No RF retraining, test predictions, external data use or shared-contract changes.
Validation selects only the training-selected model's operating threshold.
"""
from __future__ import annotations

import argparse
import json
import platform
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from toxicity.src import bionemo_candidate as candidate
from toxicity.src import bionemo_diagnostics as diagnosis
from toxicity.src import bionemo_experiment as experiment

ARMS = ("morgan", "embedding", "hybrid")
C_VALUES = diagnosis.C_VALUES
DEFAULT_OUTPUT = experiment.ROOT / "artifacts/runs/bionemo_hybrid_v1"
PROTOCOL = {
    "id": "bionemo_hybrid_v1",
    "arms": list(ARMS), "C_values": list(C_VALUES),
    "selection": "maximum mean training-fold AP; exact ties: smaller C, then morgan/embedding/hybrid",
    "cv": "identical 3-fold StratifiedGroupKFold, shuffle=True, seed=42, frozen training only",
    "nested_cv": "3 outer training folds; select arm and C using 3 inner folds within each fitting subset",
    "features": "Morgan radius=2, bits=2048, chirality=True; verified cached MegaMolBART; concatenate in that order",
    "scaling": "StandardScaler on all selected columns, including bits, fit separately in each fitting fold",
    "head": "L2 logistic, max_iter=5000, seed=42; no PCA, feature selection, block weighting or calibration",
    "validation": "only final training-selected arm/C; balanced accuracy threshold, sensitivity then lower threshold tie-break",
    "test": "closed; no label extraction or prediction; full structures/cache checked for integrity only",
    "ensemble": "deferred: original trusted RF weights unavailable; baseline is not retrained or substituted",
    "status": "exploratory after earlier test inspection; not confirmatory evidence of RF improvement",
}


def development_data(rows, membership, embeddings):
    result = diagnosis.development_data(rows, membership, embeddings)
    by_id = {row["structure_id"]: row for row in rows}
    for data in result.values():
        bits = np.asarray([experiment.fingerprint(by_id[sid]["canonical_smiles"])
                           for sid in data["structure_ids"]], dtype=float)
        data["X"] = np.concatenate([bits, data["X"]], axis=1)
    return result


def make_model(arm, c, n_morgan):
    if arm not in ARMS or n_morgan < 1:
        raise ValueError("invalid_feature_arm")
    columns = {"morgan": slice(0, n_morgan), "embedding": slice(n_morgan, None),
               "hybrid": slice(0, None)}[arm]
    return Pipeline([
        ("features", ColumnTransformer([("scale", StandardScaler(), columns)], remainder="drop")),
        ("logistic", LogisticRegression(C=c, max_iter=5000, random_state=42)),
    ])


def choose(scores):
    winner = max(scores, key=lambda r: (r["mean_average_precision"], -r["C"], -ARMS.index(r["arm"])))
    return {key: winner[key] for key in ("arm", "C", "mean_average_precision")}


def select(train, n_morgan):
    split = candidate.folds(train)
    scores = []
    for arm in ARMS:
        for c in C_VALUES:
            held_metrics = []
            for fit, hold in split:
                model = diagnosis.fit_checked(make_model(arm, c, n_morgan), train["X"][fit], train["y"][fit])
                held_metrics.append(diagnosis.probability_metrics(
                    train["y"][hold], model.predict_proba(train["X"][hold])[:, 1]))
            scores.append({"arm": arm, "C": c, "folds": held_metrics,
                           "mean_average_precision": float(np.mean([r["average_precision"] for r in held_metrics]))})
    return {"selected": choose(scores), "scores": scores,
            "per_arm": {arm: choose([r for r in scores if r["arm"] == arm]) for arm in ARMS},
            "fold_membership": [candidate.fold_ids(train, fit, hold) for fit, hold in split]}


def build_comparison(development, n_morgan=2048):
    if set(development) != {"train", "validation"}:
        raise ValueError("only_development_partitions_allowed")
    train, valid = development["train"], development["validation"]
    if set(train["groups"]) & set(valid["groups"]) or set(train["structure_ids"]) & set(valid["structure_ids"]):
        raise ValueError("development_overlap")
    if train["X"].shape[1] <= n_morgan or train["X"].shape[1] != valid["X"].shape[1]:
        raise ValueError("invalid_feature_dimensions")
    outer_records = []
    for fit, hold in candidate.folds(train):
        inner = select(candidate.subset(train, fit), n_morgan)
        per_arm = {}
        for arm, config in inner["per_arm"].items():
            model = diagnosis.fit_checked(make_model(arm, config["C"], n_morgan), train["X"][fit], train["y"][fit])
            probabilities = model.predict_proba(train["X"][hold])[:, 1]
            per_arm[arm] = {"C": config["C"], "metrics": diagnosis.probability_metrics(train["y"][hold], probabilities),
                            "predictions": [{"structure_id": train["structure_ids"][i], "positive_probability": float(p)}
                                            for i, p in zip(hold, probabilities)]}
        outer_records.append({**candidate.fold_ids(train, fit, hold), "inner_selection": inner,
                              "per_arm": per_arm,
                              "selected_procedure_metrics": per_arm[inner["selected"]["arm"]]["metrics"]})
    # Freeze both representation and regularization before looking at validation outputs.
    selection = select(train, n_morgan)
    config = selection["selected"]
    model = diagnosis.fit_checked(make_model(config["arm"], config["C"], n_morgan), train["X"], train["y"])
    p = model.predict_proba(valid["X"])[:, 1]
    threshold = experiment.choose_threshold(valid["y"], p)
    keys = outer_records[0]["selected_procedure_metrics"]
    report = {
        "protocol": PROTOCOL, "training_selection": selection,
        "feature_dimensions": {"morgan": n_morgan, "embedding": train["X"].shape[1] - n_morgan,
                               "hybrid": train["X"].shape[1]},
        "counts": {part: {"n": len(d["y"]), "positive": int(d["y"].sum())} for part, d in development.items()},
        "nested_training_cv": {
            "folds": outer_records,
            "per_arm_mean": {arm: {key: float(np.mean([r["per_arm"][arm]["metrics"][key] for r in outer_records]))
                                   for key in keys} for arm in ARMS},
            "selected_procedure_mean": {key: float(np.mean([r["selected_procedure_metrics"][key] for r in outer_records]))
                                        for key in keys},
        },
        "validation": experiment.metrics(valid["y"], p, threshold),
        "validation_reliability": experiment.reliability(valid["y"], p),
        "validation_predictions": [{"structure_id": sid, "positive_probability": float(prob)}
                                   for sid, prob in zip(valid["structure_ids"], p)],
        "limitations": [
            "Exploratory after earlier test inspection and repeated development-data analysis.",
            "Nested training CV is not a fresh independent test or proof of superiority to RF.",
            "No original RF weights available: RF comparison and prediction ensemble deferred.",
            "No new test or external predictions. No probability calibration fitted.",
            "Compound-level DILI concern, not patient incidence or proof of safety.",
            "Exact representation-pretraining overlap remains unknown.",
        ],
    }
    return model, report


def run(cache_path=diagnosis.DEFAULT_CACHE, output_dir=DEFAULT_OUTPUT):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError("refusing_to_overwrite_hybrid_directory")
    rows, _, membership, data_hash, split_hash = experiment.load_frozen_inputs()
    cache = json.loads(Path(cache_path).read_text())
    matrix = experiment.validate_cache(cache, rows, data_hash, split_hash)
    # Pin the existing representation; a different provider/checkpoint needs protocol review.
    expected_cache = "7990795575c2d2637e60c61d5cc8cb674b4bc6dc42970fff4047bd27b1d19397"
    if experiment.digest(cache_path) != expected_cache:
        raise ValueError("hybrid_representation_checksum_mismatch")
    development = development_data(rows, membership, matrix)
    indices = {part: [i for i, row in enumerate(rows) if membership[row["structure_id"]]["partition"] == part]
               for part in ("train", "validation")}
    applicability = experiment.applicability(rows, indices["train"], indices["validation"])
    del rows, membership, matrix
    model, report = build_comparison(development)
    report.update({
        "data_sha256": data_hash, "split_manifest_sha256": split_hash,
        "cache_sha256": experiment.digest(cache_path),
        "representation": {key: cache[key] for key in ("model_id", "model_version", "embedding_dimension", "preprocessing_version")},
        "source_sha256": {name: experiment.digest(Path(__file__).with_name(name)) for name in
                          ("bionemo_hybrid.py", "bionemo_candidate.py", "bionemo_diagnostics.py",
                           "bionemo_experiment.py", "baseline.py", "ingest_dilirank.py")},
        "runtime": {"python": platform.python_version(), **{name: version(name) for name in
                    ("numpy", "scipy", "scikit-learn", "joblib", "rdkit")}},
        "validation_applicability": {"method": "nearest training Morgan radius-2 2048-bit Tanimoto", "records": applicability},
    })
    output_dir.mkdir(parents=True, exist_ok=False)
    path = output_dir / "candidate.joblib"
    joblib.dump({"model": model, "threshold": report["validation"]["threshold"], "metadata": report}, path)
    restored = joblib.load(path)  # Only our own newly generated trusted artifact.
    np.testing.assert_array_equal(restored["model"].predict_proba(development["validation"]["X"])[:, 1],
                                  [r["positive_probability"] for r in report["validation_predictions"]])
    report["artifact"] = {"filename": path.name, "sha256": experiment.digest(path),
                          "validation_roundtrip_exact": True, "production_integration": "none"}
    experiment.save_json(output_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=diagnosis.DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args.cache, args.output_dir)
    print(json.dumps({"output_dir": str(args.output_dir), "selected": report["training_selection"]["selected"],
                      "nested_training_cv": report["nested_training_cv"]["per_arm_mean"],
                      "selected_procedure_cv": report["nested_training_cv"]["selected_procedure_mean"],
                      "validation": report["validation"]}, indent=2))


if __name__ == "__main__":
    main()
