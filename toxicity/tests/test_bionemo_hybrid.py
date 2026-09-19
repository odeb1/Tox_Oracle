"""Offline synthetic tests for feature isolation and training-only selection."""
import joblib
import numpy as np
import pytest

from toxicity.src import bionemo_hybrid as hybrid


def fixture():
    rng = np.random.default_rng(9)
    return {part: {"X": rng.normal(size=(n, 6)) + shift, "y": np.arange(n) % 2,
                   "groups": np.arange(n) // 6 + start // 6,
                   "structure_ids": [str(i) for i in range(start, start + n)]}
            for part, n, shift, start in (("train", 60, 0, 0), ("validation", 18, 20, 60))}


def test_exact_ties_choose_smaller_c_then_morgan():
    scores = [{"arm": arm, "C": c, "mean_average_precision": .8}
              for arm in reversed(hybrid.ARMS) for c in (1., .01)]
    assert hybrid.choose(scores) == {"arm": "morgan", "C": .01, "mean_average_precision": .8}


@pytest.mark.parametrize("arm,dimensions", [("morgan", 3), ("embedding", 3), ("hybrid", 6)])
def test_only_requested_columns_enter_classifier(arm, dimensions):
    data = fixture()["train"]
    model = hybrid.make_model(arm, .1, 3).fit(data["X"], data["y"])
    assert model.named_steps["logistic"].n_features_in_ == dimensions
    transformed = model.named_steps["features"].transform(data["X"])
    np.testing.assert_allclose(transformed.mean(axis=0), 0, atol=1e-14)
    if arm != "hybrid":
        changed = data["X"].copy()
        changed[:, 3:] += 1000 if arm == "morgan" else 0
        changed[:, :3] += 1000 if arm == "embedding" else 0
        np.testing.assert_array_equal(model.predict_proba(data["X"]), model.predict_proba(changed))


def test_nested_selection_and_scaling_never_use_validation(monkeypatch, tmp_path):
    data = fixture()
    monkeypatch.setattr(hybrid, "C_VALUES", (.1, .01))
    original_select = hybrid.select
    original_scale_fit = hybrid.StandardScaler.fit
    original_threshold = hybrid.experiment.choose_threshold
    selection_sizes, thresholds = [], []

    def select(train, n_morgan):
        assert all(int(sid) < 60 for sid in train["structure_ids"])
        selection_sizes.append(len(train["y"]))
        return original_select(train, n_morgan)

    def scale(self, X, *args, **kwargs):
        assert np.max(np.abs(X)) < 10  # Validation intentionally shifted above 10.
        return original_scale_fit(self, X, *args, **kwargs)

    def threshold(y, p):
        np.testing.assert_array_equal(y, data["validation"]["y"])
        thresholds.append(len(p))
        return original_threshold(y, p)

    monkeypatch.setattr(hybrid, "select", select)
    monkeypatch.setattr(hybrid.StandardScaler, "fit", scale)
    monkeypatch.setattr(hybrid.experiment, "choose_threshold", threshold)
    model, report = hybrid.build_comparison(data, 3)
    assert len(selection_sizes) == 4 and selection_sizes[-1] == 60
    assert all(n < 60 for n in selection_sizes[:-1])
    assert thresholds == [18]  # Only selected model reaches threshold selection.
    seen = []
    for outer in report["nested_training_cv"]["folds"]:
        fits, holds = set(outer["fit_ids"]), set(outer["holdout_ids"])
        assert not {int(i) // 6 for i in fits} & {int(i) // 6 for i in holds}
        for inner in outer["inner_selection"]["fold_membership"]:
            assert set(inner["fit_ids"]) | set(inner["holdout_ids"]) == fits
            assert not {int(i) // 6 for i in inner["fit_ids"]} & {int(i) // 6 for i in inner["holdout_ids"]}
        for arm in hybrid.ARMS:
            assert {r["structure_id"] for r in outer["per_arm"][arm]["predictions"]} == holds
        seen.extend(holds)
    assert sorted(seen, key=int) == [str(i) for i in range(60)]
    assert set(report["counts"]) == {"train", "validation"}
    assert "test_predictions" not in report
    path = tmp_path / "own_model.joblib"
    joblib.dump(model, path)
    np.testing.assert_array_equal(joblib.load(path).predict_proba(data["validation"]["X"]),
                                  model.predict_proba(data["validation"]["X"]))


def test_extraction_never_reads_test_label_or_fingerprints_test_structure(monkeypatch):
    class Guard(dict):
        def __getitem__(self, key):
            if key in {"dili_label", "canonical_smiles"}:
                raise AssertionError("test modeling input read")
            return super().__getitem__(key)

    rows = [{"structure_id": "a", "dili_label": "1", "canonical_smiles": "CC"},
            {"structure_id": "b", "dili_label": "0", "canonical_smiles": "CCC"},
            Guard(structure_id="c")]
    membership = {sid: {"partition": part, "group": i} for i, (sid, part) in enumerate(
        (("a", "train"), ("b", "validation"), ("c", "test")))}
    monkeypatch.setattr(hybrid.experiment, "fingerprint", lambda smiles: np.array([1, 0]))
    data = hybrid.development_data(rows, membership, np.array([[1., 2.], [3., 4.], [np.nan, np.nan]]))
    np.testing.assert_array_equal(data["train"]["X"], [[1, 0, 1, 2]])
    np.testing.assert_array_equal(data["validation"]["X"], [[1, 0, 3, 4]])


def test_rejects_test_partition_and_group_overlap():
    data = fixture()
    with pytest.raises(ValueError, match="only_development"):
        hybrid.build_comparison({**data, "test": data["validation"]}, 3)
    data["validation"]["groups"][0] = 0
    with pytest.raises(ValueError, match="development_overlap"):
        hybrid.build_comparison(data, 3)


def test_refuses_overwrite_before_loading_inputs(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("inputs must not be loaded")
    monkeypatch.setattr(hybrid.experiment, "load_frozen_inputs", forbidden)
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        hybrid.run(output_dir=tmp_path)
