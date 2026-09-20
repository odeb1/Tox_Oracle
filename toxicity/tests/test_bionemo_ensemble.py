"""Offline synthetic ensemble tests; never require/download scientific artifacts."""
import joblib
import numpy as np
import pytest

from toxicity.src import bionemo_ensemble as ensemble


class FinalRFGuard:
    """Stand-in that forbids using the full-training model on CV holdouts."""
    def __init__(self):
        self.calls = 0

    def predict_proba(self, X):
        assert np.min(X) > 10  # Only deliberately shifted validation may enter.
        self.calls += 1
        p = np.linspace(.2, .8, len(X))
        return np.column_stack([1-p, p])


def fixture():
    rng = np.random.default_rng(15)
    return {part: {"X": rng.normal(size=(n, 6)) + shift, "y": np.arange(n) % 2,
                   "groups": np.arange(n) // 6 + start // 6,
                   "structure_ids": [str(i) for i in range(start, start+n)]}
            for part, n, shift, start in (("train", 60, 0, 0), ("validation", 18, 20, 60))}


def test_tie_rule_favors_rf_then_smaller_c():
    assert ensemble.choose([{"rf_weight": w, "C": c, "mean_average_precision": .8}
                            for w, c in [(0, .001), (.75, 1), (1, None)]])["rf_weight"] == 1
    result = ensemble.choose([{"rf_weight": .5, "C": c, "mean_average_precision": .8} for c in (1, .001)])
    assert result["C"] == .001


def test_blend_endpoints_and_misalignment():
    rp, ep = np.array([.2, .7]), np.array([.4, .9])
    np.testing.assert_array_equal(ensemble.blend(rp, None, 1), rp)
    np.testing.assert_array_equal(ensemble.blend(rp, ep, 0), ep)
    np.testing.assert_allclose(ensemble.blend(rp, ep, .5), [.3, .8])
    with pytest.raises(ValueError, match="misaligned"):
        ensemble.blend(rp, np.array([.5]), .5)
    with pytest.raises(ValueError, match="unregistered"):
        ensemble.blend(rp, ep, .3)


def assert_grouped_within(folds, allowed):
    holdouts = []
    for fold in folds:
        fits, holds = set(fold["fit_ids"]), set(fold["holdout_ids"])
        assert fits | holds == allowed
        assert not {int(i)//6 for i in fits} & {int(i)//6 for i in holds}
        holdouts.extend(holds)
    assert sorted(holdouts, key=int) == sorted(allowed, key=int)


def test_every_calibrator_and_estimator_stays_inside_training_folds(monkeypatch, tmp_path):
    data = fixture()
    monkeypatch.setattr(ensemble, "RF_PARAMS", {**ensemble.RF_PARAMS, "n_estimators": 3, "n_jobs": 1})
    monkeypatch.setattr(ensemble, "C_VALUES", (.1, .01))
    original_rf_fit = ensemble.RandomForestClassifier.fit
    original_scale_fit = ensemble.hybrid.StandardScaler.fit
    original_threshold = ensemble.experiment.choose_threshold
    original_select = ensemble.select
    selections, thresholds, rf_fits = [], [], []

    def fit_rf(self, X, *args, **kwargs):
        assert np.max(np.abs(X)) < 10
        rf_fits.append(len(X))
        return original_rf_fit(self, X, *args, **kwargs)

    def scale(self, X, *args, **kwargs):
        assert np.max(np.abs(X)) < 10
        return original_scale_fit(self, X, *args, **kwargs)

    def select(train, n_morgan):
        assert all(int(i) < 60 for i in train["structure_ids"])
        selections.append(len(train["y"]))
        return original_select(train, n_morgan)

    def threshold(y, p):
        np.testing.assert_array_equal(y, data["validation"]["y"])
        thresholds.append(len(p))
        return original_threshold(y, p)

    monkeypatch.setattr(ensemble.RandomForestClassifier, "fit", fit_rf)
    monkeypatch.setattr(ensemble.hybrid.StandardScaler, "fit", scale)
    monkeypatch.setattr(ensemble, "select", select)
    monkeypatch.setattr(ensemble.experiment, "choose_threshold", threshold)
    final = FinalRFGuard()
    bundle, report = ensemble.build(data, final, .558, 3)
    assert final.calls == 1
    assert len(selections) == 4 and selections[-1] == 60
    assert all(n < 60 for n in selections[:3])
    assert max(rf_fits) < 60  # Final RF reused, never fitted here.
    assert thresholds == ([] if bundle["rf_weight"] == 1 else [18])
    if bundle["rf_weight"] == 1:
        assert bundle["threshold"] == .558
    outer = report["nested_training_cv"]["folds"]
    assert_grouped_within(outer, set(data["train"]["structure_ids"]))
    for fold in outer:
        allowed = set(fold["fit_ids"])
        assert_grouped_within(fold["rf_calibration_folds"], allowed)
        inner = fold["inner_selection"]["fold_membership"]
        assert_grouped_within(inner, allowed)
        for selection_fold in inner:
            assert_grouped_within(selection_fold["rf_calibration_folds"], set(selection_fold["fit_ids"]))
        assert {r["structure_id"] for r in fold["predictions"]} == set(fold["holdout_ids"])
    for fold in report["training_selection"]["fold_membership"]:
        assert_grouped_within(fold["rf_calibration_folds"], set(fold["fit_ids"]))
    path = tmp_path / "own_bundle.joblib"
    joblib.dump(bundle, path)
    np.testing.assert_allclose(ensemble.predict_bundle(joblib.load(path), data["validation"]["X"]),
                               [r["positive_probability"] for r in report["validation_predictions"]])
    assert set(report["counts"]) == {"train", "validation"}
    assert "test_predictions" not in report


def test_rejects_test_partition_and_development_overlap():
    data = fixture()
    with pytest.raises(ValueError, match="only_development"):
        ensemble.build({**data, "test": data["validation"]}, FinalRFGuard(), .5, 3)
    data["validation"]["groups"][0] = 0
    with pytest.raises(ValueError, match="development_overlap"):
        ensemble.build(data, FinalRFGuard(), .5, 3)


def test_existing_output_refused_before_reading_artifacts(tmp_path):
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        ensemble.run(output_dir=tmp_path, rf_path=tmp_path/'missing')


def test_unverified_rf_never_unpickled(tmp_path, monkeypatch):
    path = tmp_path/'untrusted.joblib'
    path.write_bytes(b'not a verified artifact')
    def forbidden(*args, **kwargs):
        raise AssertionError("untrusted pickle loaded")
    monkeypatch.setattr(ensemble.joblib, "load", forbidden)
    with pytest.raises(ValueError, match="unverified_rf"):
        ensemble.run(output_dir=tmp_path/'new', rf_path=path)
