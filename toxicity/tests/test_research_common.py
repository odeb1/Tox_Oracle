"""Offline regression checks for shared helpers; no model artifacts or data needed."""
import subprocess
import sys
from importlib.metadata import PackageNotFoundError

import numpy as np
import pytest

from toxicity.src import research_common as common


def test_historical_xgboost_helper_imports_remain_compatible():
    from toxicity.src import morgan_xgboost

    for name in ("development_data", "validate_development", "positive_probability"):
        assert getattr(morgan_xgboost, name) is getattr(common, name)


@pytest.mark.parametrize("module", ["research_common", "bionemo_mlp", "morgan_svm", "rf_svm_ensemble"])
def test_non_xgboost_modules_do_not_import_xgboost_or_its_runner(module):
    # A fresh process avoids already-imported modules hiding accidental coupling.
    script = """
import importlib
import importlib.abc
import sys

class BlockXGBoost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'toxicity.src.morgan_xgboost' or fullname.split('.')[0] == 'xgboost':
            raise AssertionError('unexpected optional-model import: ' + fullname)

sys.meta_path.insert(0, BlockXGBoost())
importlib.import_module('toxicity.src.' + sys.argv[1])
"""
    subprocess.run(
        [sys.executable, "-c", script, module],
        cwd=common.experiment.ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_runtime_lock_checks_exact_versions_in_order(tmp_path):
    lock = tmp_path / "synthetic.lock"
    lock.write_text("# Synthetic test dependencies\n\nalpha==1.2.3\nbeta==4.5.6\n")
    calls = []

    def lookup(name):
        calls.append(name)
        return {"alpha": "1.2.3", "beta": "4.5.6"}[name]

    common.validate_locked_runtime(lock, version_lookup=lookup)
    assert calls == ["alpha", "beta"]


@pytest.mark.parametrize("prefix", ["baseline_runtime_mismatch", "runtime_mismatch"])
def test_runtime_lock_preserves_caller_error_prefix_and_fails_fast(tmp_path, prefix):
    lock = tmp_path / "synthetic.lock"
    lock.write_text("alpha==1.2.3\nbeta==4.5.6\n")
    calls = []

    def lookup(name):
        calls.append(name)
        return "unexpected-version"

    with pytest.raises(ValueError, match=f"^{prefix}:alpha$"):
        common.validate_locked_runtime(lock, version_lookup=lookup, error_prefix=prefix)
    assert calls == ["alpha"]


def test_missing_runtime_dependency_is_not_ignored(tmp_path):
    lock = tmp_path / "synthetic.lock"
    lock.write_text("uninstalled-package==1.0\n")

    def lookup(name):
        raise PackageNotFoundError(name)

    with pytest.raises(PackageNotFoundError):
        common.validate_locked_runtime(lock, version_lookup=lookup)


@pytest.mark.parametrize("line", ["alpha>=1", "alpha==1==2"])
def test_malformed_runtime_lock_is_not_silently_accepted(tmp_path, line):
    lock = tmp_path / "synthetic.lock"
    lock.write_text(line + "\n")
    with pytest.raises(ValueError):
        common.validate_locked_runtime(lock, version_lookup=lambda _: pytest.fail("malformed pin used"))


def test_missing_runtime_lock_is_not_ignored(tmp_path):
    with pytest.raises(FileNotFoundError):
        common.validate_locked_runtime(tmp_path / "missing.lock")


def test_probability_validation_preserves_values_dtype_and_inputs():
    matrix = np.array([[.25, .75], [.875, .125]], dtype=np.float32)
    X = np.array([[0., 1.], [1., 0.]])
    original_X = X.copy()

    class Model:
        classes_ = [0, 1]
        calls = 0

        def predict_proba(self, received):
            assert received is X
            self.calls += 1
            return matrix

    model = Model()
    probabilities = common.positive_probability(model, X)
    assert probabilities.dtype == np.float64
    assert model.calls == 1
    np.testing.assert_array_equal(probabilities, matrix[:, 1])
    np.testing.assert_array_equal(X, original_X)
    probabilities[:] = 0
    np.testing.assert_array_equal(matrix[:, 1], [.75, .125])


@pytest.mark.parametrize("offset,accepted", [(5e-7, True), (2e-6, False)])
def test_probability_normalization_tolerance_is_unchanged(offset, accepted):
    class Model:
        classes_ = [0, 1]

        def predict_proba(self, X):
            return np.array([[.5, .5 + offset]])

    if accepted:
        np.testing.assert_array_equal(common.positive_probability(Model(), np.zeros((1, 2))), [.5 + offset])
    else:
        with pytest.raises(ValueError, match="^invalid_probability_output$"):
            common.positive_probability(Model(), np.zeros((1, 2)))


@pytest.mark.parametrize("matrix", [np.zeros((2, 2)), np.zeros((1, 1)), np.array([.2, .8])])
def test_probability_row_and_class_dimensions_are_checked(matrix):
    class Model:
        classes_ = [0, 1]

        def predict_proba(self, X):
            return matrix

    with pytest.raises(ValueError, match="^invalid_probability_output$"):
        common.positive_probability(Model(), np.zeros((1, 2)))


def test_development_extraction_keeps_order_without_touching_test(monkeypatch):
    class TestRow(dict):
        def __getitem__(self, key):
            assert key == "structure_id", "test structure or label accessed"
            return "test"

    rows = [
        {"structure_id": "z", "canonical_smiles": "first", "dili_label": "1"},
        TestRow(),
        {"structure_id": "a", "canonical_smiles": "second", "dili_label": "0"},
        {"structure_id": "v", "canonical_smiles": "third", "dili_label": "1"},
    ]
    membership = {sid: {"partition": part, "group": group} for sid, part, group in
                  [("z", "train", 0), ("a", "train", 1), ("v", "validation", 2), ("test", "test", 3)]}
    calls = []

    def fingerprint(smiles):
        calls.append(smiles)
        return np.array([0, 1], dtype=np.uint8)

    monkeypatch.setattr(common.experiment, "fingerprint", fingerprint)
    data = common.development_data(rows, membership)
    assert list(data) == ["train", "validation"]
    assert data["train"]["structure_ids"] == ["z", "a"]
    np.testing.assert_array_equal(data["train"]["y"], [1, 0])
    np.testing.assert_array_equal(data["train"]["groups"], [0, 1])
    assert calls == ["first", "second", "third"]
