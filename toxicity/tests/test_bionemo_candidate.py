"""Synthetic offline tests for the exploratory selection procedure."""
import joblib
import numpy as np
import pytest

from toxicity.src import bionemo_candidate as candidate


def development_fixture():
    rng = np.random.default_rng(12)
    return {
        "train": {"X": rng.normal(size=(60, 4)), "y": np.arange(60) % 2,
                  "groups": np.arange(60) // 6, "structure_ids": [str(i) for i in range(60)]},
        "validation": {"X": rng.normal(size=(18, 4)) + 20, "y": np.arange(18) % 2,
                       "groups": np.arange(18) // 6 + 10, "structure_ids": [str(i) for i in range(60, 78)]},
    }


def test_exact_ap_tie_uses_stronger_penalty():
    assert candidate.choose_c([
        {"C": 1.0, "mean_average_precision": 0.8},
        {"C": 0.01, "mean_average_precision": 0.8},
        {"C": 0.001, "mean_average_precision": 0.7},
    ]) == 0.01


def test_nested_selection_is_training_only_and_artifact_roundtrips(monkeypatch, tmp_path):
    development = development_fixture()
    original_select = candidate.select_on_training
    original_scale_fit = candidate.diagnosis.StandardScaler.fit
    original_threshold = candidate.experiment.choose_threshold
    selections, threshold_calls = [], []

    def guarded_select(train):
        assert all(int(sid) < 60 for sid in train["structure_ids"])
        selections.append(len(train["y"]))
        return original_select(train)

    def guarded_scale_fit(self, X, *args, **kwargs):
        assert np.max(np.abs(X)) < 10  # Validation deliberately shifted by +20.
        return original_scale_fit(self, X, *args, **kwargs)

    def guarded_threshold(y, p):
        np.testing.assert_array_equal(y, development["validation"]["y"])
        threshold_calls.append(len(p))
        return original_threshold(y, p)

    monkeypatch.setattr(candidate, "select_on_training", guarded_select)
    monkeypatch.setattr(candidate.diagnosis.StandardScaler, "fit", guarded_scale_fit)
    monkeypatch.setattr(candidate.experiment, "choose_threshold", guarded_threshold)
    model, report = candidate.build_candidate(development)
    assert len(selections) == 4 and selections[-1] == 60
    assert all(n < 60 for n in selections[:-1])
    assert threshold_calls == [18]
    held_ids = []
    for outer in report["nested_training_cv"]["folds"]:
        fit_ids, hold_ids = set(outer["fit_ids"]), set(outer["holdout_ids"])
        assert not {int(sid) // 6 for sid in fit_ids} & {int(sid) // 6 for sid in hold_ids}
        for inner in outer["inner_selection"]["fold_membership"]:
            assert set(inner["fit_ids"]) | set(inner["holdout_ids"]) == fit_ids
            assert not {int(sid) // 6 for sid in inner["fit_ids"]} & {int(sid) // 6 for sid in inner["holdout_ids"]}
        held_ids.extend(hold_ids)
    assert sorted(held_ids, key=int) == [str(i) for i in range(60)]
    assert "test_predictions" not in report
    assert "test" not in report["counts"]
    path = tmp_path / "trusted_test_model.joblib"
    joblib.dump(model, path)
    restored = joblib.load(path)
    np.testing.assert_array_equal(restored.predict_proba(development["validation"]["X"]),
                                  model.predict_proba(development["validation"]["X"]))


def test_existing_artifact_directory_is_never_overwritten(tmp_path, monkeypatch):
    existing = tmp_path / "candidate"
    existing.mkdir()
    sentinel = existing / "candidate.joblib"
    sentinel.write_bytes(b"preserve this")

    def forbidden():
        raise AssertionError("should refuse before reading data")

    monkeypatch.setattr(candidate.experiment, "load_frozen_inputs", forbidden)
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        candidate.run(output_dir=existing)
    assert sentinel.read_bytes() == b"preserve this"
