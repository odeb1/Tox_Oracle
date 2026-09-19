import copy
import hashlib
import json

import pytest

from toxicity.src import bionemo_experiment as experiment


class DeterministicEmbedder:
    """Offline test double; these vectors are never scientific results."""

    def embed(self, smiles):
        result = []
        for value in smiles:
            raw = hashlib.sha256(value.encode()).digest()
            result.append([raw[i] / 255.0 for i in range(8)])
        return result


def test_frozen_split_audit():
    result = experiment.audit()
    assert result["status"] == "frozen_split_integrity_verified"
    assert result["cross_partition_group_overlap"] == 0
    assert result["identity_duplicates"] == 0
    assert result["counts"] == {
        "train": {"n": 539, "positive": 339},
        "validation": {"n": 158, "positive": 95},
        "test": {"n": 105, "positive": 74},
    }


def test_cache_contract_and_tamper_detection(tmp_path):
    path = tmp_path / "embeddings.json"
    cache = experiment.acquire_embeddings(
        DeterministicEmbedder(), "test/molmim", "offline-test-only", path, batch_size=97
    )
    rows, _, _, data_checksum, split_checksum = experiment.load_frozen_inputs()
    matrix = experiment.validate_cache(cache, rows, data_checksum, split_checksum)
    assert matrix.shape == (802, 8)
    assert not any("dili_label" in record for record in cache["records"])
    assert all(record["preprocessing_version"] == "dilirank_parent_v1" for record in cache["records"])

    tampered = copy.deepcopy(cache)
    tampered["records"][0]["embedding"][0] += 1
    tampered["records_sha256"] = experiment.canonical_digest(tampered["records"])
    with pytest.raises(ValueError, match="cache_embedding_checksum_mismatch"):
        experiment.validate_cache(tampered, rows, data_checksum, split_checksum)


def test_embedding_shape_is_discovered_not_assumed():
    vectors, dimension = experiment.validate_vectors([[1, 2, 3], [4, 5, 6]], 2)
    assert dimension == 3
    assert vectors == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    with pytest.raises(ValueError, match="embedding_dimension_changed"):
        experiment.validate_vectors([[1, 2]], 1, dimension=3)


def test_offline_evaluation_uses_frozen_cohort_and_validation_threshold(tmp_path, monkeypatch):
    cache_path = tmp_path / "embeddings.json"
    report_path = tmp_path / "report.json"
    experiment.acquire_embeddings(
        DeterministicEmbedder(), "test/molmim", "offline-test-only", cache_path, batch_size=128
    )
    rows, _, membership, *_ = experiment.load_frozen_inputs()
    expected_labels = {
        part: [int(r["dili_label"]) for r in rows if membership[r["structure_id"]]["partition"] == part]
        for part in ("train", "validation")
    }
    original_fit = experiment.Pipeline.fit
    original_threshold = experiment.choose_threshold
    calls = []

    def checked_fit(self, X, y, **kwargs):
        assert len(X) == 539
        assert list(y) == expected_labels["train"]
        calls.append("train_only_fit")
        return original_fit(self, X, y, **kwargs)

    def checked_threshold(y, probability):
        assert len(probability) == 158
        assert list(y) == expected_labels["validation"]
        calls.append("validation_only_threshold")
        return original_threshold(y, probability)

    monkeypatch.setattr(experiment.Pipeline, "fit", checked_fit)
    monkeypatch.setattr(experiment, "choose_threshold", checked_threshold)
    report = experiment.evaluate(cache_path, report_path)
    assert calls == ["train_only_fit", "validation_only_threshold"]
    assert report["same_frozen_test_cohort_as_baseline"] is True
    assert report["counts"]["test"] == {"n": 105, "positive": 74}
    assert report["test"]["threshold"] == report["validation"]["threshold"]
    assert len(report["applicability"]["records"]) == 105
    assert report["pretraining_overlap"]["status"] == "unknown"
    assert json.loads(report_path.read_text())["representation"]["model_version"] == "offline-test-only"


def test_endpoint_rejects_embedded_credentials():
    with pytest.raises(ValueError, match="invalid_endpoint"):
        experiment.MolMIMClient("https://user:secret@example.test")


@pytest.mark.parametrize("endpoint", ["https://example.test?key=secret", "https://example.test#secret"])
def test_endpoint_rejects_query_or_fragment_credentials(endpoint):
    with pytest.raises(ValueError, match="invalid_endpoint"):
        experiment.MolMIMClient(endpoint)


@pytest.mark.parametrize("vector", [[True, 1], ["1", 2], [float("nan"), 1]])
def test_invalid_vector_values_rejected(vector):
    with pytest.raises(ValueError):
        experiment.validate_vectors([vector], 1)


def test_frozen_split_cannot_be_replaced(tmp_path):
    path = tmp_path / "changed_split.json"
    doc = json.loads(experiment.SPLIT.read_text())
    doc["records"][0]["partition"] = "train"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="frozen_design_checksum_mismatch"):
        experiment.load_frozen_inputs(split=path)


def test_record_provenance_cannot_disagree_with_cache(tmp_path):
    cache = experiment.acquire_embeddings(DeterministicEmbedder(), "test", "test-only", tmp_path / "cache.json")
    rows, _, _, data_hash, split_hash = experiment.load_frozen_inputs()
    record = cache["records"][0]
    record["preprocessing_version"] = "wrong"
    identity = {key: record[key] for key in (
        "structure_id", "canonical_smiles", "model_id", "model_version",
        "preprocessing_version", "dataset_sha256", "split_manifest_sha256")}
    record["cache_key"] = experiment.canonical_digest(identity)
    cache["records_sha256"] = experiment.canonical_digest(cache["records"])
    with pytest.raises(ValueError, match="cache_record_preprocessing_version_mismatch"):
        experiment.validate_cache(cache, rows, data_hash, split_hash)


def test_worker_preflight_rejects_unsupported_structures_and_labels():
    from toxicity.src.megamolbart_worker import check_structures

    class Tokenizer:
        vocab = {"C": 0, "O": 1}

        def text_to_tokens(self, text):
            return list(text)

    row = {"structure_id": "test-only", "canonical_smiles": "CCO"}
    assert check_structures([row], Tokenizer(), 3) == [3]
    with pytest.raises(ValueError, match="unsupported_token_length"):
        check_structures([row], Tokenizer(), 2)
    with pytest.raises(ValueError, match="unknown_token"):
        check_structures([dict(row, canonical_smiles="N")], Tokenizer(), 3)
    with pytest.raises(ValueError, match="label_free"):
        check_structures([dict(row, dili_label=1)], Tokenizer(), 3)
    with pytest.raises(ValueError, match="duplicate_structure_id"):
        check_structures([row, row], Tokenizer(), 3)
