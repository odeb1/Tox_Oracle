"""Offline synthetic kernel, nesting and serialization tests."""
import warnings
from functools import wraps

import joblib
import numpy as np
import pytest
from sklearn.exceptions import ConvergenceWarning

from toxicity.src import morgan_svm as svm


def data_fixture():
    result = {}
    for part, start, n in (("train", 0, 60), ("validation", 60, 18)):
        ids = np.arange(start, start+n)
        result[part] = {"X": ((ids[:, None] >> np.arange(7)) & 1).astype(float),
                        "y": ids % 2, "groups": ids // 6,
                        "structure_ids": [str(i) for i in ids]}
    return result


def decode(X):
    return set((X @ (2 ** np.arange(7))).astype(int))


def assert_grouped(folds, allowed):
    held = []
    for f in folds:
        fit, hold = set(f["fit_ids"]), set(f["holdout_ids"])
        assert not fit & hold and fit | hold == allowed
        assert not {int(i)//6 for i in fit} & {int(i)//6 for i in hold}
        held.extend(hold)
    assert sorted(held) == sorted(allowed)


def test_kernel_exact_empty_and_overflow():
    X = np.array([[1, 0, 1], [1, 1, 0], [0, 0, 0]], dtype=np.uint8)
    np.testing.assert_allclose(svm.tanimoto(X, X), [[1, 1/3, 0], [1/3, 1, 0], [0, 0, 1]])
    X = np.ones((2, 300), dtype=np.uint8)
    np.testing.assert_array_equal(svm.tanimoto(X, X), np.ones((2, 2)))


@pytest.mark.parametrize("X,Y", [([[2]], [[1]]), ([[float("nan")]], [[1]]),
                                    ([[1, 0]], [[1]]), ([1], [[1]]), ([[]], [[]])])
def test_kernel_rejects_invalid_features(X, Y):
    with pytest.raises(ValueError, match="binary_features"):
        svm.tanimoto(X, Y)


def test_convergence_failure_aborts(monkeypatch):
    def bad_fit(*args, **kwargs):
        warnings.warn("synthetic failure", ConvergenceWarning)
    monkeypatch.setattr(svm.SVC, "fit", bad_fit)
    with pytest.raises(ValueError, match="did_not_converge"):
        svm.fit_svm(data_fixture()["train"], 1.)


def test_nested_fit_and_calibration_never_see_validation(monkeypatch, tmp_path):
    data = data_fixture()
    monkeypatch.setattr(svm, "C_VALUES", (.1, 1.))
    monkeypatch.setattr(svm.ensemble, "RF_PARAMS", {**svm.ensemble.RF_PARAMS, "n_estimators": 3, "n_jobs": 1})
    old_fit, old_decision = svm.SVC.fit, svm.SVC.decision_function
    old_threshold = svm.experiment.choose_threshold
    fits, thresholds = [], []

    def fit(self, X, y, *args, **kwargs):
        assert max(decode(X)) < 60 and self.probability is False
        self.audit_fit_ids_ = decode(X)
        fits.append(len(X))
        return old_fit(self, X, y, *args, **kwargs)

    @wraps(old_decision)
    def decision(self, X):
        assert not self.audit_fit_ids_ & decode(X)
        return old_decision(self, X)

    def threshold(y, p):
        np.testing.assert_array_equal(y, data["validation"]["y"])
        thresholds.append(len(p))
        return old_threshold(y, p)

    class FinalRF:
        classes_ = np.array([0, 1])
        calls = 0
        def predict_proba(self, X):
            assert min(decode(X)) >= 60
            self.calls += 1
            p = np.linspace(.2, .8, len(X))
            return np.column_stack([1-p, p])

    monkeypatch.setattr(svm.SVC, "fit", fit)
    monkeypatch.setattr(svm.SVC, "decision_function", decision)
    monkeypatch.setattr(svm.experiment, "choose_threshold", threshold)
    final = FinalRF()
    model, report = svm.build(data, final, .558)
    assert len(fits) == 112 and fits[-1] == 60
    assert final.calls == 1 and thresholds == [18]
    assert report["validation"]["rf"]["threshold"] == .558
    outer = report["nested_training_cv"]["folds"]
    allowed = set(data["train"]["structure_ids"])
    assert_grouped(outer, allowed)
    for f in outer:
        permitted = set(f["fit_ids"])
        assert_grouped(f["svm_calibration_folds"], permitted)
        assert_grouped(f["rf_calibration_folds"], permitted)
        for inner in f["inner_selection"]["fold_membership"]:
            assert_grouped(inner["calibration_folds"], set(inner["fit_ids"]))
        assert_grouped(f["inner_selection"]["fold_membership"], permitted)
    assert_grouped(report["final_calibration_folds"], allowed)
    for inner in report["training_selection"]["fold_membership"]:
        assert_grouped(inner["calibration_folds"], set(inner["fit_ids"]))
    assert "test_predictions" not in report
    path = tmp_path / "own_synthetic_model.joblib"
    joblib.dump(model, path)
    np.testing.assert_array_equal(svm.comparison.positive_probability(joblib.load(path), data["validation"]["X"]),
                                  [r["svm"] for r in report["validation_predictions"]])


def test_budget_tie_break_and_unregistered_C():
    assert svm.C_VALUES == (.01, .1, 1., 10., 100.)
    assert svm.candidate.choose_c([{"C": c, "mean_average_precision": .8} for c in reversed(svm.C_VALUES)]) == .01
    with pytest.raises(ValueError, match="unregistered"):
        svm.fit_svm(data_fixture()["train"], 999)


def test_refuse_overwrite_before_read(tmp_path, monkeypatch):
    monkeypatch.setattr(svm.experiment, "load_frozen_inputs", lambda: pytest.fail("unexpected read"))
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        svm.run(tmp_path)


def test_untrusted_pickle_never_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(svm.experiment, "digest", lambda p: "untrusted")
    monkeypatch.setattr(svm.joblib, "load", lambda p: pytest.fail("untrusted pickle loaded"))
    with pytest.raises(ValueError, match="unverified_rf"):
        svm.run(tmp_path / "new", tmp_path / "rf")
