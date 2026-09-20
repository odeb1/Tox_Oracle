"""Offline synthetic tests for nested fusion and paired group intervals."""
from functools import wraps

import joblib
import numpy as np
import pytest

from toxicity.src import rf_svm_ensemble as fusion
from toxicity.tests.test_morgan_svm import data_fixture, decode, assert_grouped


class FinalRFGuard:
    classes_ = np.array([0, 1])

    def __init__(self): self.calls = 0

    def predict_proba(self, X):
        assert min(decode(X)) >= 60
        self.calls += 1
        p = np.linspace(.2, .8, len(X))
        return np.column_stack([1-p, p])


def test_group_bootstrap_preserves_whole_groups():
    groups = np.array([0, 0, 1, 1, 1, 2])
    rng = np.random.default_rng(42)
    for _ in range(20):
        idx = fusion.cluster_indices(groups, rng)
        counts = np.bincount(idx, minlength=len(groups))
        for group in np.unique(groups):
            assert len(set(counts[groups == group])) == 1
        assert sum(counts[np.flatnonzero(groups == g)[0]] for g in np.unique(groups)) == 3


def test_paired_identity_and_reproducibility():
    y, p = np.array([0, 1, 0, 1]), np.array([.1, .7, .2, .8])
    probabilities = {a: p for a in ("rf", "svm", "selected_blend")}
    result, draws = fusion.paired_intervals(y, probabilities, np.array([0, 0, 1, 1]), seed=42, n_bootstrap=20)
    other, other_draws = fusion.paired_intervals(y, probabilities, np.array([0, 0, 1, 1]), seed=42, n_bootstrap=20)
    assert result == other
    for arm in draws:
        np.testing.assert_array_equal(draws[arm], other_draws[arm])
        np.testing.assert_array_equal(draws[arm], 0)
        assert result["comparisons_blend_minus"][arm]["metrics"]["auroc"] == {"difference": 0., "percentile_95": [0., 0.]}


def test_single_class_resamples_discarded_jointly_not_redrawn():
    y, p = np.array([0, 1]), np.array([.2, .8])
    result, draws = fusion.paired_intervals(y, {a: p for a in ("rf", "svm", "selected_blend")}, [0, 1], seed=42, n_bootstrap=100)
    valid = result["comparisons_blend_minus"]["rf"]["valid_replicates"]
    assert 0 < valid < result["attempted_replicates"] == 100
    assert result["comparisons_blend_minus"]["svm"]["valid_replicates"] == valid
    np.testing.assert_array_equal(np.isnan(draws["rf"]), np.isnan(draws["svm"]))


def test_interval_sign_and_missing_interval():
    y = np.array([0, 1, 0, 1])
    good, bad = np.array([.1, .9, .2, .8]), np.array([.9, .1, .8, .2])
    result, _ = fusion.paired_intervals(y, {"rf": bad, "svm": good, "selected_blend": good}, [0, 0, 1, 1], seed=42, n_bootstrap=10)
    metrics = result["comparisons_blend_minus"]["rf"]["metrics"]
    assert metrics["auroc"]["difference"] == 1
    assert metrics["brier"]["difference"] < 0
    missing = fusion.interval_summary(np.zeros(3), np.full((2, 3), np.nan))
    assert missing["valid_replicates"] == 0 and missing["metrics"]["auroc"]["percentile_95"] is None


@pytest.mark.parametrize("change", ["labels", "groups", "probability", "arm"])
def test_bad_interval_inputs_rejected(change):
    y, groups = np.array([0, 1]), np.array([0, 1])
    p = {a: np.array([.2, .8]) for a in ("rf", "svm", "selected_blend")}
    if change == "labels": y[:] = 0
    elif change == "groups": groups = groups[:1]
    elif change == "probability": p["rf"][0] = np.nan
    else: p["extra"] = p["rf"]
    with pytest.raises(ValueError): fusion.paired_intervals(y, p, groups, seed=42, n_bootstrap=3)


def test_all_tuning_calibration_and_fitting_stay_inside_training(monkeypatch, tmp_path):
    data = data_fixture()
    monkeypatch.setattr(fusion.svm, "C_VALUES", (.1, 1.))
    monkeypatch.setattr(fusion, "N_BOOTSTRAP", 5)
    monkeypatch.setattr(fusion.ensemble, "RF_PARAMS", {**fusion.ensemble.RF_PARAMS, "n_estimators": 3, "n_jobs": 1})
    old_rf = fusion.ensemble.RandomForestClassifier.fit
    old_svm = fusion.svm.SVC.fit
    old_decision = fusion.svm.SVC.decision_function
    old_threshold = fusion.experiment.choose_threshold
    old_select = fusion.select
    rf_fits, svc_fits, thresholds, selections = [], [], [], []

    def rf_fit(self, X, *args, **kwargs):
        assert max(decode(X)) < 60
        rf_fits.append(len(X))
        return old_rf(self, X, *args, **kwargs)

    def svc_fit(self, X, *args, **kwargs):
        assert max(decode(X)) < 60 and self.probability is False
        self.audit_ids_ = decode(X)
        svc_fits.append(len(X))
        return old_svm(self, X, *args, **kwargs)

    @wraps(old_decision)
    def decision(self, X):
        assert not self.audit_ids_ & decode(X)
        return old_decision(self, X)

    def threshold(y, p):
        np.testing.assert_array_equal(y, data["validation"]["y"])
        thresholds.append(len(p))
        return old_threshold(y, p)

    def select(train):
        assert max(map(int, train["structure_ids"])) < 60
        selections.append(len(train["y"]))
        return old_select(train)

    monkeypatch.setattr(fusion.ensemble.RandomForestClassifier, "fit", rf_fit)
    monkeypatch.setattr(fusion.svm.SVC, "fit", svc_fit)
    monkeypatch.setattr(fusion.svm.SVC, "decision_function", decision)
    monkeypatch.setattr(fusion.experiment, "choose_threshold", threshold)
    monkeypatch.setattr(fusion, "select", select)
    final, checkpoints = FinalRFGuard(), []
    bundle, report = fusion.build(data, final, .558, checkpoint=lambda name, r: checkpoints.append(name))
    assert len(selections) == 4 and selections[-1] == 60
    assert len(rf_fits) == 60 and max(rf_fits) < 60
    assert len(svc_fits) <= 124 and final.calls == 2
    assert thresholds == ([] if bundle["rf_weight"] == 1 else [18])
    assert report["validation"]["rf"]["threshold"] == .558
    assert checkpoints == [f"outer_fold_{i}.json" for i in range(1, 4)]
    allowed = set(data["train"]["structure_ids"])
    folds = report["nested_training_cv"]["folds"]
    assert_grouped(folds, allowed)
    for fold in folds:
        permitted = set(fold["fit_ids"])
        assert_grouped(fold["rf_calibration_folds"], permitted)
        for cal in fold["svm_calibration_folds_by_C"].values(): assert_grouped(cal, permitted)
        inner = fold["inner_selection"]["fold_membership"]
        assert_grouped(inner, permitted)
        for f in inner:
            for arm in ("rf", "svm"): assert_grouped(f[arm+"_calibration_folds"], set(f["fit_ids"]))
    for f in report["training_selection"]["fold_membership"]:
        for arm in ("rf", "svm"): assert_grouped(f[arm+"_calibration_folds"], set(f["fit_ids"]))
    if bundle["svm"] is not None: assert_grouped(report["final_svm_calibration_folds"], allowed)
    path = tmp_path / "own_bundle.joblib"
    joblib.dump(bundle, path)
    np.testing.assert_array_equal(fusion.predict_bundle(joblib.load(path), data["validation"]["X"]),
                                  [r["selected_blend"] for r in report["validation_predictions"]])
    assert "test_predictions" not in report


def test_refuses_existing_output_before_read(tmp_path, monkeypatch):
    monkeypatch.setattr(fusion.experiment, "digest", lambda p: pytest.fail("unexpected read"))
    with pytest.raises(ValueError, match="refusing_to_overwrite"): fusion.run(tmp_path)


def test_rejects_untrusted_pickle_before_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(fusion.experiment, "digest", lambda p: "untrusted")
    monkeypatch.setattr(fusion.joblib, "load", lambda p: pytest.fail("untrusted pickle"))
    with pytest.raises(ValueError, match="unverified_rf"): fusion.run(tmp_path / "new", tmp_path / "rf")


def test_existing_weight_and_tie_machinery_preserved():
    assert fusion.ensemble.WEIGHTS == (0., .25, .5, .75, 1.)
    scores = [{"rf_weight": .75, "C": 1., "mean_average_precision": .8},
              {"rf_weight": 1., "C": None, "mean_average_precision": .8}]
    assert fusion.ensemble.choose(scores)["rf_weight"] == 1.


def test_probability_execution_is_sequential_without_parameter_mutation(tmp_path):
    class BackendGuard:
        classes_ = np.array([0, 1])
        def predict_proba(self, X):
            assert joblib.effective_n_jobs(-1) == 1
            return np.tile([.4, .6], (len(X), 1))
    fusion.probabilities(BackendGuard(), np.zeros((2, 1)))
    data = data_fixture()
    model = fusion.ensemble.RandomForestClassifier(n_estimators=13, random_state=42, n_jobs=-1).fit(data["train"]["X"], data["train"]["y"])
    before = model.get_params().copy()
    p = fusion.probabilities(model, data["validation"]["X"])
    path = tmp_path / "own_rf.joblib"
    joblib.dump(model, path)
    restored = joblib.load(path)
    for _ in range(3):
        np.testing.assert_array_equal(fusion.probabilities(restored, data["validation"]["X"]), p)
    assert model.get_params() == before and restored.n_jobs == -1
