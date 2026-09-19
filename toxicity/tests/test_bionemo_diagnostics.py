"""Offline synthetic tests; no GPU/cache downloads or scientific test-set scoring."""
import numpy as np
import pytest

from toxicity.src import bionemo_diagnostics as diagnostics


class TestLabelGuard(dict):
    __test__ = False

    def __getitem__(self, key):
        if key == "dili_label":
            raise AssertionError("test label accessed")
        return super().__getitem__(key)


def synthetic_development():
    rng = np.random.default_rng(7)
    matrix = rng.normal(size=(80, 4))
    matrix[60:78] += 10  # Detect accidental validation-fitted scaling.
    matrix[78:] = np.nan  # Test vectors must never enter diagnostic estimators.
    rows, membership = [], {}
    for i in range(80):
        part = "train" if i < 60 else "validation" if i < 78 else "test"
        row = {"structure_id": str(i), "dili_label": i % 2}
        rows.append(TestLabelGuard(row) if part == "test" else row)
        membership[str(i)] = {"partition": part, "group": i // 6}
    return diagnostics.development_data(rows, membership, matrix)


def test_development_extraction_does_not_access_test_labels_or_vectors():
    development = synthetic_development()
    assert set(development) == {"train", "validation"}
    assert development["train"]["X"].shape == (60, 4)
    assert development["validation"]["X"].shape == (18, 4)
    assert all(np.isfinite(d["X"]).all() for d in development.values())


def test_cv_scaling_and_thresholds_use_only_the_correct_partitions(monkeypatch):
    development = synthetic_development()
    original_scale_fit = diagnostics.StandardScaler.fit
    original_threshold = diagnostics.experiment.choose_threshold
    scale_inputs, threshold_calls = [], []

    def guarded_scale_fit(self, X, *args, **kwargs):
        assert np.isfinite(X).all()
        assert len(X) <= 60
        assert np.max(np.abs(X)) < 10  # Validation rows are deliberately shifted.
        scale_inputs.append(X.copy())
        return original_scale_fit(self, X, *args, **kwargs)

    def guarded_threshold(y, p):
        np.testing.assert_array_equal(y, development["validation"]["y"])
        assert len(p) == 18
        threshold_calls.append(True)
        return original_threshold(y, p)

    monkeypatch.setattr(diagnostics.StandardScaler, "fit", guarded_scale_fit)
    monkeypatch.setattr(diagnostics.experiment, "choose_threshold", guarded_threshold)
    report = diagnostics.diagnose(development)
    assert [r["C"] for r in report["candidates"]] == list(diagnostics.C_VALUES)
    assert len(scale_inputs) == 1 + 4 * len(diagnostics.C_VALUES)
    assert len(threshold_calls) == len(diagnostics.C_VALUES)
    seen = []
    for fold in report["training_group_cv_fold_manifest"]:
        assert not set(fold["fit_ids"]) & set(fold["holdout_ids"])
        fit_groups = {int(sid) // 6 for sid in fold["fit_ids"]}
        holdout_groups = {int(sid) // 6 for sid in fold["holdout_ids"]}
        assert not fit_groups & holdout_groups
        assert all(int(sid) < 60 for sid in fold["fit_ids"] + fold["holdout_ids"])
        seen.extend(fold["holdout_ids"])
    assert sorted(seen, key=int) == [str(i) for i in range(60)]
    for candidate in report["candidates"]:
        assert "test" not in candidate
        assert candidate["validation"]["n"] == 18


def test_report_overwrite_is_rejected_before_loading_any_data(tmp_path, monkeypatch):
    path = tmp_path / "existing.json"
    path.write_text("original")

    def forbidden():
        raise AssertionError("should fail before loading inputs")

    monkeypatch.setattr(diagnostics.experiment, "load_frozen_inputs", forbidden)
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        diagnostics.run(output=path)
    assert path.read_text() == "original"
