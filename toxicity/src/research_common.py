"""Shared boundaries for offline research comparisons, not production inference.

These helpers do not select models, folds, calibration or thresholds. Keep those
scientific choices in the individual experiment protocols. No XGBoost dependency
is imported here; non-XGBoost comparisons must also work without its optional wheel.
"""
from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import numpy as np

from toxicity.src import bionemo_experiment as experiment


def development_data(rows, membership):
    """Extract Morgan features for train/validation only, preserving row order.

    Test structures and labels must never reach fingerprinting or label conversion.
    The caller may separately verify whole-file identity/checksums.
    """
    result = {}
    for part in ("train", "validation"):
        selected = [r for r in rows if membership[r["structure_id"]]["partition"] == part]
        result[part] = {
            "X": np.asarray([experiment.fingerprint(r["canonical_smiles"]) for r in selected]),
            "y": np.asarray([int(r["dili_label"]) for r in selected]),
            "groups": np.asarray([membership[r["structure_id"]]["group"] for r in selected]),
            "structure_ids": [r["structure_id"] for r in selected],
        }
    return result


def validate_development(data):
    """Require aligned binary features and disjoint development identities/groups.

    This validates a Morgan feature block, not continuous embedding columns.
    Embedding callers validate their extra columns separately before using it.
    """
    if set(data) != {"train", "validation"}:
        raise ValueError("only_development_partitions_allowed")
    for d in data.values():
        n = len(d["structure_ids"])
        if (d["X"].ndim != 2 or not n or d["X"].shape[0] != n
                or d["y"].shape != (n,) or d["groups"].shape != (n,)
                or len(set(d["structure_ids"])) != n
                or not np.isfinite(d["X"]).all() or not np.isin(d["X"], [0, 1]).all()
                or set(d["y"]) != {0, 1}):
            raise ValueError("invalid_development_data")
    train, valid = data["train"], data["validation"]
    if (set(train["structure_ids"]) & set(valid["structure_ids"])
            or set(train["groups"]) & set(valid["groups"])):
        raise ValueError("development_overlap")
    if train["X"].shape[1] != valid["X"].shape[1] or train["X"].shape[1] == 0:
        raise ValueError("feature_dimension_mismatch")


def positive_probability(model, X):
    """Check class order and probability validity without altering predictions.

    Preserve the existing 1e-6 normalization tolerance and float64 output. Thread
    limits/sequential RF execution remain the responsibility of each caller.
    """
    if list(model.classes_) != [0, 1]:
        raise ValueError("unexpected_class_order")
    matrix = np.asarray(model.predict_proba(X))
    if (matrix.shape != (len(X), 2) or not np.isfinite(matrix).all()
            or not ((matrix >= 0) & (matrix <= 1)).all()
            or not np.allclose(matrix.sum(axis=1), 1., atol=1e-6, rtol=0)):
        raise ValueError("invalid_probability_output")
    return matrix[:, 1].astype(np.float64)


def validate_locked_runtime(
    lock: Path,
    *,
    version_lookup: Callable[[str], str] = version,
    error_prefix: str = "baseline_runtime_mismatch",
) -> None:
    """Verify the existing exact-version lock before loading research artifacts.

    The lookup can be supplied by callers/tests without importing optional model
    packages. Missing packages and malformed locks still fail closed. Callers
    retain their historical error prefix; this does not install dependencies.
    """
    for line in lock.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            package, expected = line.split("==")
            if version_lookup(package) != expected:
                raise ValueError(f"{error_prefix}:{package}")
