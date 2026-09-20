"""Audit tests use only small synthetic training OOF predictions."""
import copy

import numpy as np
import pytest

from toxicity.src import training_error_audit as audit


def fixture():
    ids = {"a", "b", "c", "d"}
    membership = {s: {"group": s} for s in ids}
    rows = [{"structure_id": s, "rf": .5} for s in sorted(ids)]
    report = {"nested_training_cv": {"folds": [
        {"fit_ids": ["a", "b"], "holdout_ids": ["c", "d"], "predictions": rows[2:]},
        {"fit_ids": ["c", "d"], "holdout_ids": ["a", "b"], "predictions": rows[:2]}]}}
    return report, ids, membership


def test_only_training_access_and_both_report_formats():
    class Guard(dict):
        def __getitem__(self, key):
            assert key == "nested_training_cv"
            return super().__getitem__(key)
    report, ids, membership = fixture()
    old, signature = audit.extract_oof(Guard(report), ids, membership)
    new = copy.deepcopy(report)
    new["nested_training_cv"]["predictions"] = list(reversed(list(old.values())))
    assert audit.extract_oof(Guard(new), ids, membership) == (old, signature)


@pytest.mark.parametrize("change", ["foreign", "duplicate_fit", "missing_prediction", "duplicate_prediction", "group_overlap", "misaligned"])
def test_invalid_oof_rejected(change):
    report, ids, membership = fixture()
    folds = report["nested_training_cv"]["folds"]
    if change == "foreign":
        folds[0]["holdout_ids"][0] = "test_id"
    elif change == "duplicate_fit":
        folds[0]["fit_ids"].append("a")
    elif change == "missing_prediction":
        folds[0]["predictions"].pop()
    elif change == "duplicate_prediction":
        folds[0]["predictions"].append(folds[0]["predictions"][0])
    elif change == "group_overlap":
        membership["a"]["group"] = "c"
    else:
        folds[0]["predictions"], folds[1]["predictions"] = folds[1]["predictions"], folds[0]["predictions"]
    with pytest.raises(ValueError):
        audit.extract_oof(report, ids, membership)


def test_rescues_new_errors_and_consensus_counts():
    y = np.array([0, 0, 1, 1])
    result = audit.summarize(y, {"rf": np.array([.8, .2, .2, .8]), "other": np.array([.2, .8, .2, .8])})
    comparison = result["comparisons_to_rf"]["other"]
    for key in ("both_wrong", "rf_wrong_other_correct", "rf_correct_other_wrong", "both_correct"):
        assert comparison[key] == 1
    assert comparison["per_class"]["0"]["rf_wrong_other_correct"] == 1
    assert result["all_models_wrong"] == result["all_models_wrong_positive"] == 1
    assert result["all_models_wrong_negative"] == 0
    assert result["diagnostic_threshold"] == .5


def test_constant_residual_correlation_is_none():
    y = np.array([0, 1])
    report = audit.summarize(y, {"rf": y.astype(float), "other": np.array([.2, .8])})
    assert report["comparisons_to_rf"]["other"]["residual_pearson_correlation"] is None


@pytest.mark.parametrize("p", [np.array([.2]), np.array([np.nan, .2]), np.array([-.1, .2])])
def test_invalid_probabilities_rejected(p):
    with pytest.raises(ValueError, match="invalid_audit_probabilities"):
        audit.summarize(np.array([0, 1]), {"rf": p})


def test_existing_output_rejected_before_read(tmp_path, monkeypatch):
    monkeypatch.setattr(audit.experiment, "load_frozen_inputs", lambda: pytest.fail("unexpected read"))
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        audit.run(tmp_path)
