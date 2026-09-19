"""Frozen-split MolMIM embedding experiment for the DILI baseline.

Embedding acquisition is the only live/GPU step. Training and evaluation are offline.
No credentials are accepted by this module; authenticate the separately deployed NIM
through its documented container setup and expose only its HTTP endpoint here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import requests
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from toxicity.src.baseline import DATA, ROOT, choose_threshold, fingerprint, make_groups, metrics
from toxicity.src.ingest_dilirank import POLICY

SPLIT = ROOT / "data/manifests/dili_baseline_split.json"
SOURCE_REPORT = ROOT / "data/manifests/dilirank2_acquisition_report.json"
BASELINE_REPORT = ROOT / "evaluation/reports/baseline_test.json"
DEFAULT_CACHE = ROOT / "artifacts/embeddings/molmim_dilirank2.json"
DEFAULT_REPORT = ROOT / "artifacts/runs/bionemo_molmim_logistic_test.json"
CACHE_SCHEMA = "toxoracle_bionemo_embedding_cache_v1"
EXPERIMENT_ID = "molmim_embedding_logistic_v1"
FROZEN_DATA_SHA256 = "997ad736dc1d282c2a0b3b4a7f9fca2d05740eacb7c6ec9d7cdf7919f312d750"
FROZEN_SPLIT_SHA256 = "e3d14890336c92e8428e83382092ef6577b20b9651e5a69e8ec245f21020938e"


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_digest(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def load_frozen_inputs(data: Path = DATA, split: Path = SPLIT):
    if digest(data) != FROZEN_DATA_SHA256 or digest(split) != FROZEN_SPLIT_SHA256:
        raise ValueError("frozen_design_checksum_mismatch")
    rows = sorted(csv.DictReader(Path(data).open()), key=lambda row: row["structure_id"])
    split_doc = json.loads(Path(split).read_text())
    source = json.loads(SOURCE_REPORT.read_text())
    data_sha256 = digest(data)
    if data_sha256 != source["artifacts"][Path(data).name]:
        raise ValueError("dataset_manifest_checksum_mismatch")
    if split_doc["data_sha256"] != data_sha256:
        raise ValueError("split_dataset_checksum_mismatch")
    membership = {record["structure_id"]: record for record in split_doc["records"]}
    if len(membership) != len(split_doc["records"]) or set(membership) != {row["structure_id"] for row in rows}:
        raise ValueError("split_membership_mismatch")
    if len({row["canonical_smiles"] for row in rows}) != len(rows):
        raise ValueError("duplicate_canonical_structure")
    if {row["standardization_version"] for row in rows} != {POLICY}:
        raise ValueError("preprocessing_version_mismatch")
    allowed = {"train", "validation", "test"}
    if {record["partition"] for record in split_doc["records"]} != allowed:
        raise ValueError("invalid_split_partitions")
    partitions = {row["structure_id"]: membership[row["structure_id"]]["partition"] for row in rows}
    for field in ("structure_id", "canonical_smiles", "structure_key", "connectivity_group"):
        values = {
            part: {row[field] for row in rows if partitions[row["structure_id"]] == part}
            for part in allowed
        }
        if any(values[left] & values[right] for left, right in (
            ("train", "validation"), ("train", "test"), ("validation", "test")
        )):
            raise ValueError(f"cross_partition_{field}")
    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        left_groups = {record["group"] for record in split_doc["records"] if record["partition"] == left}
        right_groups = {record["group"] for record in split_doc["records"] if record["partition"] == right}
        if left_groups & right_groups:
            raise ValueError("cross_partition_scaffold_or_connectivity_group")
    recomputed_groups = make_groups(rows, scaffold=True)
    group_partitions = {}
    for row, group in zip(rows, recomputed_groups):
        part = partitions[row["structure_id"]]
        if group in group_partitions and group_partitions[group] != part:
            raise ValueError("recomputed_scaffold_or_connectivity_leakage")
        group_partitions[group] = part
    return rows, split_doc, membership, data_sha256, digest(split)


class MolMIMClient:
    """Minimal client for NVIDIA MolMIM NIM's documented POST /embedding API."""

    def __init__(self, endpoint: str, timeout: float = 120.0):
        parsed = urlparse(endpoint)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("invalid_endpoint")
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def embed(self, smiles: list[str]) -> list[list[float]]:
        response = requests.post(
            self.endpoint + "/embedding",
            json={"sequences": smiles},
            headers={"accept": "application/json", "content-type": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        if set(body) != {"embeddings"} or not isinstance(body["embeddings"], list):
            raise ValueError("unexpected_embedding_response")
        return body["embeddings"]


def validate_vectors(vectors, expected: int, dimension: int | None = None) -> tuple[list[list[float]], int]:
    if not isinstance(vectors, list) or len(vectors) != expected:
        raise ValueError("embedding_count_mismatch")
    clean = []
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise ValueError("invalid_embedding_vector")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
            raise ValueError("invalid_embedding_vector")
        try:
            converted = [float(value) for value in vector]
        except (TypeError, ValueError):
            raise ValueError("invalid_embedding_vector") from None
        if not all(math.isfinite(value) for value in converted):
            raise ValueError("nonfinite_embedding")
        if dimension is not None and len(converted) != dimension:
            raise ValueError("embedding_dimension_changed")
        dimension = len(converted)
        clean.append(converted)
    return clean, int(dimension)


def acquire_embeddings(
    client,
    model_id: str,
    model_version: str,
    cache_path: Path = DEFAULT_CACHE,
    batch_size: int = 32,
    data: Path = DATA,
    split: Path = SPLIT,
    capability: str = "MolMIM NIM POST /embedding",
    provenance: dict | None = None,
):
    if not model_id.strip() or not model_version.strip():
        raise ValueError("model_identity_required")
    if batch_size < 1:
        raise ValueError("invalid_batch_size")
    rows, split_doc, _, data_checksum, split_checksum = load_frozen_inputs(data, split)
    records, dimension = [], None
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        vectors, dimension = validate_vectors(
            client.embed([row["canonical_smiles"] for row in batch]), len(batch), dimension
        )
        for row, vector in zip(batch, vectors):
            identity = {
                "structure_id": row["structure_id"],
                "canonical_smiles": row["canonical_smiles"],
                "model_id": model_id,
                "model_version": model_version,
                "preprocessing_version": POLICY,
                "dataset_sha256": data_checksum,
                "split_manifest_sha256": split_checksum,
            }
            records.append(
                dict(
                    identity,
                    canonical_smiles_sha256=hashlib.sha256(row["canonical_smiles"].encode()).hexdigest(),
                    embedding=vector,
                    embedding_sha256=canonical_digest(vector),
                    cache_key=canonical_digest(identity),
                )
            )
    cache = {
        "schema_version": CACHE_SCHEMA,
        "provider": "NVIDIA BioNeMo",
        "capability": capability,
        "provenance": provenance or {},
        "model_id": model_id,
        "model_version": model_version,
        "embedding_dimension": dimension,
        "preprocessing_version": POLICY,
        "dataset_sha256": data_checksum,
        "split_manifest_sha256": split_checksum,
        "split_method": split_doc["method"],
        "records": records,
    }
    cache["records_sha256"] = canonical_digest(records)
    save_json(cache_path, cache)
    return cache


def validate_cache(cache, rows, data_checksum: str, split_checksum: str):
    required = {
        "schema_version": CACHE_SCHEMA,
        "provider": "NVIDIA BioNeMo",
        "preprocessing_version": POLICY,
        "dataset_sha256": data_checksum,
        "split_manifest_sha256": split_checksum,
    }
    for key, expected in required.items():
        if cache.get(key) != expected:
            raise ValueError(f"cache_{key}_mismatch")
    if not isinstance(cache.get("model_id"), str) or not cache["model_id"].strip():
        raise ValueError("cache_model_id_missing")
    if not isinstance(cache.get("model_version"), str) or not cache["model_version"].strip():
        raise ValueError("cache_model_version_missing")
    records = cache.get("records")
    if not isinstance(records, list) or cache.get("records_sha256") != canonical_digest(records):
        raise ValueError("cache_records_checksum_mismatch")
    by_id = {record.get("structure_id"): record for record in records}
    if len(by_id) != len(records) or set(by_id) != {row["structure_id"] for row in rows}:
        raise ValueError("cache_structure_membership_mismatch")
    matrix = []
    for row in rows:
        record = by_id[row["structure_id"]]
        identity = {key: record.get(key) for key in (
            "structure_id", "canonical_smiles", "model_id", "model_version",
            "preprocessing_version", "dataset_sha256", "split_manifest_sha256"
        )}
        if record.get("canonical_smiles") != row["canonical_smiles"]:
            raise ValueError("cache_smiles_mismatch")
        if record.get("model_id") != cache["model_id"] or record.get("model_version") != cache["model_version"]:
            raise ValueError("cache_model_identity_mismatch")
        for key in ("preprocessing_version", "dataset_sha256", "split_manifest_sha256"):
            if record.get(key) != cache[key]:
                raise ValueError(f"cache_record_{key}_mismatch")
        if record.get("canonical_smiles_sha256") != hashlib.sha256(row["canonical_smiles"].encode()).hexdigest():
            raise ValueError("cache_smiles_checksum_mismatch")
        if record.get("cache_key") != canonical_digest(identity):
            raise ValueError("cache_key_mismatch")
        if record.get("embedding_sha256") != canonical_digest(record.get("embedding")):
            raise ValueError("cache_embedding_checksum_mismatch")
        vectors, dimension = validate_vectors([record["embedding"]], 1, cache.get("embedding_dimension"))
        if dimension != cache.get("embedding_dimension"):
            raise ValueError("cache_embedding_dimension_mismatch")
        matrix.append(vectors[0])
    return np.asarray(matrix, dtype=np.float64)


def applicability(rows, train_indices, test_indices):
    train_fp = [fingerprint(rows[i]["canonical_smiles"]) for i in train_indices]
    result = []
    for index in test_indices:
        query = fingerprint(rows[index]["canonical_smiles"])
        similarities = np.asarray([
            np.sum(candidate & query) / max(int(np.sum(candidate | query)), 1) for candidate in train_fp
        ])
        nearest = int(np.argmax(similarities))
        result.append({
            "structure_id": rows[index]["structure_id"],
            "nearest_training_structure_id": rows[int(train_indices[nearest])]["structure_id"],
            "nearest_training_tanimoto": float(similarities[nearest]),
        })
    return result


def reliability(y, probability):
    observed, predicted = calibration_curve(y, probability, n_bins=5, strategy="quantile")
    return [{"mean_predicted": float(p), "observed_positive_fraction": float(o)}
            for o, p in zip(observed, predicted)]


def evaluate(cache_path: Path = DEFAULT_CACHE, output: Path = DEFAULT_REPORT):
    rows, split_doc, membership, data_checksum, split_checksum = load_frozen_inputs()
    cache = json.loads(Path(cache_path).read_text())
    X = validate_cache(cache, rows, data_checksum, split_checksum)
    y = np.asarray([int(row["dili_label"]) for row in rows])
    indices = {
        part: np.asarray([i for i, row in enumerate(rows) if membership[row["structure_id"]]["partition"] == part])
        for part in ("train", "validation", "test")
    }
    baseline_doc = json.loads(BASELINE_REPORT.read_text())
    baseline = baseline_doc["random_forest"]
    if (baseline_doc["data_sha256"] != data_checksum
            or baseline["n"] != len(indices["test"])
            or baseline["positives"] != int(y[indices["test"]].sum())):
        raise ValueError("baseline_cohort_mismatch")
    model = Pipeline([
        ("scale", StandardScaler()),
        ("logistic", LogisticRegression(C=1.0, max_iter=5000, random_state=42)),
    ])
    model.fit(X[indices["train"]], y[indices["train"]])
    validation_probability = model.predict_proba(X[indices["validation"]])[:, 1]
    threshold = choose_threshold(y[indices["validation"]], validation_probability)
    test_probability = model.predict_proba(X[indices["test"]])[:, 1]
    coefficients = model.named_steps["logistic"].coef_[0]
    ranked = np.argsort(np.abs(coefficients))[::-1][:20]
    app = applicability(rows, indices["train"], indices["test"])
    test_metrics = metrics(y[indices["test"]], test_probability, threshold)
    report = {
        "experiment_id": ("megamolbart_embedding_logistic_v1"
                          if cache["model_id"] == "nvidia/clara/megamolbart" else EXPERIMENT_ID),
        "status": "completed",
        "data_sha256": data_checksum,
        "split_manifest_sha256": split_checksum,
        "split_method": split_doc["method"],
        "same_frozen_test_cohort_as_baseline": True,
        "counts": {part: {"n": int(len(idx)), "positive": int(y[idx].sum())} for part, idx in indices.items()},
        "representation": {
            "provider": cache["provider"], "model_id": cache["model_id"],
            "model_version": cache["model_version"], "dimension": cache["embedding_dimension"],
            "preprocessing_version": cache["preprocessing_version"], "cache_sha256": digest(cache_path),
            "capability": cache.get("capability"), "provenance": cache.get("provenance", {}),
        },
        "runtime": {"python": platform.python_version(), **{
            name: version(name) for name in ("numpy", "scipy", "scikit-learn", "rdkit")}},
        "baseline_report_sha256": digest(BASELINE_REPORT),
        "baseline_comparison_source": "Published frozen RF report; original RF weights were not available locally for paired predictions.",
        "classifier": "StandardScaler fit on train + LogisticRegression(C=1.0) fit on train",
        "selection": "No feature or hyperparameter selection; threshold maximizes validation balanced accuracy with sensitivity then lower threshold as tie-breakers.",
        "validation": metrics(y[indices["validation"]], validation_probability, threshold),
        "test": test_metrics,
        "test_reliability_quantile_bins": reliability(y[indices["test"]], test_probability),
        "test_predictions": [
            {"structure_id": rows[int(i)]["structure_id"], "label": int(y[i]),
             "positive_probability": float(p), "predicted_label": int(p >= threshold)}
            for i, p in zip(indices["test"], test_probability)
        ],
        "baseline_random_forest_test": baseline,
        "point_estimate_delta_vs_baseline": {
            key: float(test_metrics[key] - baseline[key])
            for key in ("auroc", "average_precision", "sensitivity", "specificity", "brier")
        },
        "applicability": {
            "method": "nearest training compound Morgan radius-2 2048-bit Tanimoto",
            "median": float(np.median([row["nearest_training_tanimoto"] for row in app])),
            "minimum": float(min(row["nearest_training_tanimoto"] for row in app)),
            "records": app,
        },
        "largest_absolute_logistic_coefficients": [
            {"embedding_dimension_index": int(i), "coefficient": float(coefficients[i])} for i in ranked
        ],
        "pretraining_overlap": {
            "status": "unknown",
            "reason": "NVIDIA documents ZINC15 pretraining, but the exact pretrained-model training identities are not available in this repository for overlap matching.",
        },
        "claim": "Held-out point estimates only; do not claim improvement without reviewing these results and their sampling uncertainty.",
        "limitations": [
            "Drug-level DILI concern labels are not patient-level incidence or proof of safety.",
            "Representation pretraining did not use these DILI labels, but exact molecular pretraining overlap is unknown.",
            "The held-out test cohort has 105 compounds; metric differences may be unstable.",
            "This previously reported benchmark is exploratory, not a fresh confirmatory test set.",
            "Logistic outputs are treated as probabilities for Brier/reliability assessment, not assumed to be calibrated.",
        ],
    }
    save_json(output, report)
    return report


def import_megamolbart(raw_path: Path, cache_path: Path):
    """Validate the real GPU worker's complete output before constructing the cache."""
    from toxicity.src.megamolbart_worker import MODEL_ID, MODEL_VERSION, CHECKPOINT_SHA256, IMAGE_DIGEST
    raw = json.loads(Path(raw_path).read_text())
    for key, expected in {"model_id": MODEL_ID, "model_version": MODEL_VERSION,
                          "checkpoint_sha256": CHECKPOINT_SHA256,
                          "container_image_digest": IMAGE_DIGEST}.items():
        if raw.get(key) != expected:
            raise ValueError(f"worker_{key}_mismatch")
    if (raw.get("unknown_tokens") != 0 or raw.get("all_tokenizations_round_trip") is not True
            or raw.get("repeat_smoke_exact_match") is not True):
        raise ValueError("worker_compatibility_failed")
    rows, *_ = load_frozen_inputs()
    records = raw["records"]
    if len(records) != len(rows):
        raise ValueError("worker_cohort_mismatch")
    for row, record in zip(rows, records):
        if any(row[key] != record.get(key) for key in ("structure_id", "canonical_smiles")):
            raise ValueError("worker_structure_mismatch")
        if not 0 < record["token_count"] <= raw["max_supported_tokens"]:
            raise ValueError("worker_token_length_mismatch")
    vectors = {record["canonical_smiles"]: record["embedding"] for record in records}

    class RecordedEmbeddings:
        def embed(self, smiles):
            return [vectors[value] for value in smiles]

    return acquire_embeddings(
        RecordedEmbeddings(), MODEL_ID, MODEL_VERSION, cache_path,
        capability="BioNeMo MegaMolBARTInference.seq_to_embeddings; masked mean pooling",
        provenance={**{key: value for key, value in raw.items() if key != "records"},
                    "worker_output_sha256": digest(raw_path)},
    )


def audit():
    rows, split_doc, membership, data_checksum, split_checksum = load_frozen_inputs()
    counts = {}
    for part in ("train", "validation", "test"):
        subset = [row for row in rows if membership[row["structure_id"]]["partition"] == part]
        counts[part] = {"n": len(subset), "positive": sum(int(row["dili_label"]) for row in subset)}
    return {
        "data_sha256": data_checksum,
        "split_manifest_sha256": split_checksum,
        "method": split_doc["method"],
        "counts": counts,
        "identity_duplicates": 0,
        "cross_partition_group_overlap": 0,
        "status": "frozen_split_integrity_verified",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("audit")
    imp = sub.add_parser("import-megamolbart", help="Offline import of optional GPU worker output")
    imp.add_argument("--raw", type=Path, required=True)
    imp.add_argument("--cache", type=Path, required=True)
    fetch = sub.add_parser("fetch", help="Optional live/GPU embedding acquisition")
    fetch.add_argument("--endpoint", default="http://127.0.0.1:8000")
    fetch.add_argument("--model-id", default="nvidia/molmim")
    fetch.add_argument("--model-version", required=True,
                       help="Exact deployed checkpoint/version; never inferred from vector shape")
    fetch.add_argument("--batch-size", type=int, default=32)
    fetch.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    run = sub.add_parser("evaluate", help="Offline frozen-split logistic experiment")
    run.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    run.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if args.command == "audit":
        print(json.dumps(audit(), indent=2))
    elif args.command == "import-megamolbart":
        cache = import_megamolbart(args.raw, args.cache)
        print(json.dumps({"records": len(cache["records"]), "dimension": cache["embedding_dimension"]}))
    elif args.command == "fetch":
        cache = acquire_embeddings(MolMIMClient(args.endpoint), args.model_id, args.model_version,
                                   args.cache, args.batch_size)
        print(json.dumps({key: cache[key] for key in ("model_id", "model_version", "embedding_dimension", "records_sha256")}, indent=2))
    else:
        print(json.dumps(evaluate(args.cache, args.output), indent=2))


if __name__ == "__main__":
    main()
