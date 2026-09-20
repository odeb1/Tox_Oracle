"""Offline synthetic checks. Optional real XGBoost tests need its pinned CPU wheel."""
import numpy as np
import pytest

from toxicity.src import morgan_xgboost as research


def fixture():
    rng = np.random.default_rng(29)
    result = {}
    for part, start, n in (("train", 0, 60), ("validation", 60, 18)):
        ids = np.arange(start, start + n)
        X = rng.integers(0, 2, (n, 16)).astype(np.float32)
        X[:, :7] = (ids[:, None] >> np.arange(7)) & 1
        result[part] = dict(X=X, y=ids % 2, groups=ids // 6,
                            structure_ids=[str(i) for i in ids])
    return result


def decode(X):
    return set((X[:, :7] @ (2 ** np.arange(7))).astype(int))


class FinalRFGuard:
    classes_ = np.array([0, 1])

    def __init__(self):
        self.calls = 0

    def predict_proba(self, X):
        assert min(decode(X)) >= 60
        self.calls += 1
        p = np.linspace(.2, .8, len(X))
        return np.column_stack([1 - p, p])


def test_development_extraction_does_not_touch_test_features_or_labels():
    class Poison:
        def __int__(self):
            raise AssertionError("test label accessed")

    rows = [dict(structure_id="a", canonical_smiles="CCO", dili_label="0"),
            dict(structure_id="b", canonical_smiles="CCN", dili_label="1"),
            dict(structure_id="test", canonical_smiles="INVALID", dili_label=Poison())]
    membership = {r["structure_id"]: dict(partition=p, group=i)
                  for i, (r, p) in enumerate(zip(rows, ("train", "validation", "test")))}
    data = research.development_data(rows, membership)
    assert data["train"]["X"].shape == (1, 2048)
    assert data["validation"]["structure_ids"] == ["b"]


def test_exact_tie_uses_registered_grid_order():
    scores = [dict(config=c, grid_index=i, mean_average_precision=.7)
              for i, c in reversed(list(enumerate(research.GRID)))]
    assert research.choose(scores) == research.GRID[0]
    assert len(research.GRID) == 8
    assert research.FIXED["device"] == "cpu"
    assert "early_stopping_rounds" not in research.FIXED


@pytest.mark.parametrize("change,match", [
    ("test", "only_development"), ("group", "overlap"), ("identity", "overlap"),
    ("nan", "invalid_development"), ("nonbinary", "invalid_development"),
    ("dimension", "dimension"), ("label", "invalid_development"),
])
def test_invalid_or_leaking_inputs_rejected(change, match):
    data = fixture()
    if change == "test":
        data["test"] = data["validation"]
    elif change == "group":
        data["validation"]["groups"][0] = 0
    elif change == "identity":
        data["validation"]["structure_ids"][0] = "0"
    elif change == "dimension":
        data["validation"]["X"] = data["validation"]["X"][:, :-1]
    elif change == "label":
        data["train"]["y"][0] = 2
    else:
        data["train"]["X"][0, 0] = np.nan if change == "nan" else 2
    with pytest.raises(ValueError, match=match):
        research.validate_development(data)


def assert_grouped_within(folds, allowed):
    held = []
    for fold in folds:
        fit, hold = set(fold["fit_ids"]), set(fold["holdout_ids"])
        assert fit | hold == allowed
        assert not {int(i) // 6 for i in fit} & {int(i) // 6 for i in hold}
        held.extend(hold)
    assert sorted(held) == sorted(allowed)


def test_real_cpu_nested_fits_never_see_holdouts_or_validation(monkeypatch, tmp_path):
    xgb = pytest.importorskip("xgboost", reason="optional pinned CPU research dependency")
    if xgb.__version__ != research.XGBOOST_VERSION:
        pytest.skip("requires pinned research XGBoost version")
    data = fixture()
    grid = tuple(dict(max_depth=d, n_estimators=3, reg_lambda=10.) for d in (2, 4))
    monkeypatch.setattr(research, "GRID", grid)
    monkeypatch.setattr(research.ensemble, "RF_PARAMS", {**research.ensemble.RF_PARAMS, "n_estimators": 3, "n_jobs": 1})
    original_fit, original_predict = xgb.XGBClassifier.fit, xgb.XGBClassifier.predict_proba
    original_threshold, original_select = research.experiment.choose_threshold, research.select
    fits, selections, thresholds = [], [], []

    def fit(self, X, y, **kwargs):
        ids = decode(X)
        assert max(ids) < 60
        assert not kwargs  # No eval_set can leak an outer holdout or validation.
        self._test_fit_ids = ids
        fits.append(ids)
        return original_fit(self, X, y)

    def predict(self, X, **kwargs):
        assert not decode(X) & self._test_fit_ids
        return original_predict(self, X, **kwargs)

    def select(train):
        assert max(map(int, train["structure_ids"])) < 60
        selections.append(set(train["structure_ids"]))
        return original_select(train)

    def threshold(y, p):
        np.testing.assert_array_equal(y, data["validation"]["y"])
        thresholds.append(len(p))
        return original_threshold(y, p)

    monkeypatch.setattr(xgb.XGBClassifier, "fit", fit)
    monkeypatch.setattr(xgb.XGBClassifier, "predict_proba", predict)
    monkeypatch.setattr(research, "select", select)
    monkeypatch.setattr(research.experiment, "choose_threshold", threshold)
    final = FinalRFGuard()
    model, report = research.build(data, final, .558)
    assert final.calls == 1 and thresholds == [18]
    assert len(selections) == 4 and len(selections[-1]) == 60
    assert len(fits) == 28  # 4 selections * 2 configs * 3 folds + 4 selected fits.
    assert len(fits[-1]) == 60
    outer = report["nested_training_cv"]["folds"]
    assert_grouped_within(outer, set(data["train"]["structure_ids"]))
    for fold in outer:
        assert_grouped_within(fold["inner_selection"]["fold_membership"], set(fold["fit_ids"]))
        assert_grouped_within(fold["rf_calibration_folds"], set(fold["fit_ids"]))
    assert len(report["nested_training_cv"]["predictions"]) == 60
    assert report["validation"]["rf"]["threshold"] == .558
    assert "test_predictions" not in report and set(report["counts"]) == {"train", "validation"}
    # Native persistence must retain exact probabilities; avoid monkeypatch-only state.
    monkeypatch.setattr(xgb.XGBClassifier, "predict_proba", original_predict)
    path = tmp_path / "synthetic.ubj"
    model.save_model(path)
    restored = research.make_model(report["training_selection"]["selected"])
    restored.load_model(path)
    np.testing.assert_array_equal(research.positive_probability(restored, data["validation"]["X"]),
                                  [r["xgboost"] for r in report["validation_predictions"]])


def test_existing_output_rejected_before_optional_dependency_or_data(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "make_model", lambda _: pytest.fail("dependency should not be loaded"))
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        research.run(tmp_path)


def test_untrusted_rf_rejected_before_pickle_load(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "make_model", lambda _: None)
    monkeypatch.setattr(research, "version", lambda name: dict(line.split("==") for line in
                        (research.experiment.ROOT / "toxicity/requirements-model.lock").read_text().splitlines())[name])
    monkeypatch.setattr(research.joblib, "load", lambda _: pytest.fail("untrusted pickle loaded"))
    path = tmp_path / "untrusted.joblib"
    path.write_bytes(b"synthetic invalid artifact")
    with pytest.raises(ValueError, match="unverified_rf"):
        research.run(tmp_path / "output", path)


@pytest.mark.parametrize("values,classes", [([[.5, .5]], [1, 0]),
    ([[np.nan, .5]], [0, 1]), ([[.3, .3]], [0, 1]), ([[-.1, 1.1]], [0, 1])])
def test_invalid_probabilities_rejected(values, classes):
    class Bad:
        classes_ = classes

        def predict_proba(self, X):
            return np.array(values)

    with pytest.raises(ValueError, match="class_order|probability"):
        research.positive_probability(Bad(), np.zeros((1, 4)))
