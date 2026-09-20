"""Offline synthetic MLP tests; no cache, GPU, network or production RF required."""
import warnings
from types import SimpleNamespace

import joblib
import numpy as np
import pytest
from sklearn.exceptions import ConvergenceWarning

from toxicity.src import bionemo_mlp as mlp


def fixture():
    rng = np.random.default_rng(19)
    result = {}
    for part, start, n in (("train", 0, 60), ("validation", 60, 18)):
        ids = np.arange(start, start + n)
        bits = ((ids[:, None] >> np.arange(7)) & 1).astype(float)
        embeddings = rng.normal(size=(n, 3)) + (20 if part == "validation" else 0)
        result[part] = {"X": np.column_stack([bits, embeddings]), "y": ids % 2,
                        "groups": ids // 6, "structure_ids": [str(i) for i in ids]}
    return result


def decode(X):
    return set((X[:, :7] @ (2 ** np.arange(7))).astype(int))


class RFGuard:
    classes_ = np.array([0, 1])

    def __init__(self):
        self.calls = 0

    def predict_proba(self, X):
        assert X.shape[1] == 7 and min(decode(X)) >= 60
        self.calls += 1
        p = np.linspace(.2, .8, len(X))
        return np.column_stack([1-p, p])


@pytest.mark.parametrize("arm,dimensions", [("morgan", 7), ("embedding", 3)])
def test_feature_isolation_and_fitting_subset_scaling(arm, dimensions):
    train = fixture()["train"]
    config = next(c for c in mlp.GRID if c["arm"] == arm)
    model = mlp.fit_checked(mlp.make_model(config, 7), train["X"], train["y"])
    assert model.named_steps["mlp"].n_features_in_ == dimensions
    transformed = model.named_steps["features"].transform(train["X"])
    np.testing.assert_allclose(transformed.mean(axis=0), 0, atol=1e-14)
    changed = train["X"].copy()
    changed[:, 7:] += 1000 if arm == "morgan" else 0
    changed[:, :7] += 1000 if arm == "embedding" else 0
    np.testing.assert_array_equal(mlp.probabilities(model, train["X"]), mlp.probabilities(model, changed))


def test_fixed_budget_and_no_hidden_validation_or_seed_selection():
    assert len(mlp.GRID) == 12
    assert mlp.choose([dict(config=c, grid_index=i, mean_average_precision=.8)
                       for i, c in reversed(list(enumerate(mlp.GRID)))]) == mlp.GRID[0]
    head = mlp.make_model(mlp.GRID[0], 7).named_steps["mlp"]
    assert head.solver == "lbfgs" and head.early_stopping is False
    assert head.random_state == 42
    with pytest.raises(ValueError, match="unregistered"):
        mlp.make_model(mlp.GRID[0], 7, 999)


def test_nonconverged_fit_fails_instead_of_silently_excluding_candidate():
    class Bad:
        def fit(self, X, y):
            warnings.warn("synthetic convergence failure", ConvergenceWarning)
    with pytest.raises(ValueError, match="did_not_converge"):
        mlp.fit_checked(Bad(), np.ones((6, 3)), np.arange(6) % 2)


def test_nonfinite_weights_rejected():
    class Bad:
        named_steps = {"mlp": SimpleNamespace(loss_=1., coefs_=[np.array([np.nan])], intercepts_=[])}
        def fit(self, X, y):
            return self
    with pytest.raises(ValueError, match="nonfinite"):
        mlp.fit_checked(Bad(), np.ones((6, 3)), np.arange(6) % 2)


@pytest.mark.parametrize("change", ["test", "overlap", "nan", "dimensions", "bits"])
def test_bad_development_inputs_rejected(change):
    data = fixture()
    if change == "test":
        data["test"] = data["validation"]
    elif change == "overlap":
        data["validation"]["groups"][0] = 0
    elif change == "nan":
        data["train"]["X"][0, -1] = np.nan
    elif change == "dimensions":
        data["validation"]["X"] = data["validation"]["X"][:, :-1]
    else:
        data["train"]["X"][0, 0] = 2
    with pytest.raises(ValueError):
        mlp.validate_development(data, 7)


def assert_grouped(folds, allowed):
    held = []
    for fold in folds:
        fit, hold = set(fold["fit_ids"]), set(fold["holdout_ids"])
        assert fit | hold == allowed
        assert not {int(i)//6 for i in fit} & {int(i)//6 for i in hold}
        held.extend(hold)
    assert sorted(held) == sorted(allowed)


def test_nested_fits_seeds_and_scaling_are_training_only(monkeypatch, tmp_path):
    data = fixture()
    monkeypatch.setattr(mlp, "GRID", tuple(dict(arm=a, hidden=3, alpha=10.) for a in mlp.ARMS))
    monkeypatch.setattr(mlp, "SENSITIVITY_SEEDS", (43,))
    monkeypatch.setattr(mlp.ensemble, "RF_PARAMS", {**mlp.ensemble.RF_PARAMS, "n_estimators": 3, "n_jobs": 1})
    original_fit, original_select = mlp.fit_checked, mlp.select
    original_scale, original_threshold = mlp.StandardScaler.fit, mlp.experiment.choose_threshold
    fits, selects, thresholds = [], [], []

    def fit(model, X, y):
        assert max(decode(X)) < 60 and np.max(np.abs(X[:, 7:])) < 10
        fits.append((len(X), model.named_steps["mlp"].random_state))
        return original_fit(model, X, y)

    def select(train, n_morgan):
        assert max(map(int, train["structure_ids"])) < 60
        selects.append(len(train["y"]))
        return original_select(train, n_morgan)

    def scale(self, X, *args, **kwargs):
        assert np.max(np.abs(X)) < 10
        return original_scale(self, X, *args, **kwargs)

    def threshold(y, p):
        np.testing.assert_array_equal(y, data["validation"]["y"])
        thresholds.append(len(p))
        return original_threshold(y, p)

    monkeypatch.setattr(mlp, "fit_checked", fit)
    monkeypatch.setattr(mlp, "select", select)
    monkeypatch.setattr(mlp.StandardScaler, "fit", scale)
    monkeypatch.setattr(mlp.experiment, "choose_threshold", threshold)
    final = RFGuard()
    saved = []
    model, report = mlp.build(data, final, .558, 7, checkpoint=lambda name, r: saved.append(name))
    assert final.calls == 1 and thresholds == [18]  # Only one selected MLP sees validation.
    assert len(selects) == 4 and selects[-1] == 60
    assert len(fits) == 37 and fits[-1] == (60, 42)
    assert sum(seed == 43 for _, seed in fits) == 6
    assert saved == [f"outer_fold_{i}.json" for i in range(1, 4)]
    assert report["validation"]["rf"]["threshold"] == .558
    assert model.named_steps["mlp"].random_state == 42
    outer = report["nested_training_cv"]["folds"]
    allowed = set(data["train"]["structure_ids"])
    assert_grouped(outer, allowed)
    for fold in outer:
        assert_grouped(fold["inner_selection"]["fold_membership"], set(fold["fit_ids"]))
        assert_grouped(fold["rf_calibration_folds"], set(fold["fit_ids"]))
    assert_grouped(report["seed_sensitivity"]["fold_membership"], allowed)
    assert {r["structure_id"] for r in report["nested_training_cv"]["predictions"]} == allowed
    assert set(report["validation"]) == {"rf", "selected_mlp"}
    assert "test_predictions" not in report
    path = tmp_path / "own_synthetic_model.joblib"
    joblib.dump(model, path)
    np.testing.assert_array_equal(mlp.probabilities(joblib.load(path), data["validation"]["X"]),
                                  [r["selected_mlp"] for r in report["validation_predictions"]])


def test_existing_run_rejected_before_data_access(tmp_path, monkeypatch):
    monkeypatch.setattr(mlp.experiment, "load_frozen_inputs", lambda: pytest.fail("data should not be read"))
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        mlp.run(tmp_path)
