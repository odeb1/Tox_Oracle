"""Optional GPU-only BioNeMo worker. Run inside the pinned NVIDIA container.

Input is a label-free structure manifest, never a training/evaluation CSV.
No network calls or credentials are needed once the checkpoint is downloaded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

CHECKPOINT_SHA256 = "108923c3081e6d0debd76c9e33d692af18d46b71f8001c2d6c1eaa3fb4df032e"
IMAGE_DIGEST = "sha256:7700c5556935a93055bee5367d36acb6d3e55d22fd1ba28503f5447656fa63fa"
MODEL_ID = "nvidia/clara/megamolbart"
MODEL_VERSION = "1.0;checkpoint_sha256=" + CHECKPOINT_SHA256 + ";pooling=masked_mean_v1"


def check_structures(records, tokenizer, max_tokens):
    """Fail closed on unknown tokens, changed strings, duplicates or long inputs."""
    seen = set()
    counts = []
    for row in records:
        if set(row) != {"structure_id", "canonical_smiles"}:
            raise ValueError("worker_requires_label_free_structures")
        if row["structure_id"] in seen:
            raise ValueError("duplicate_structure_id")
        seen.add(row["structure_id"])
        tokens = tokenizer.text_to_tokens(row["canonical_smiles"])
        if "".join(tokens) != row["canonical_smiles"]:
            raise ValueError("tokenizer_changed_smiles")
        if any(token not in tokenizer.vocab for token in tokens):
            raise ValueError("unknown_token:" + row["structure_id"])
        if not tokens or len(tokens) > max_tokens:
            raise ValueError("unsupported_token_length:" + row["structure_id"])
        counts.append(len(tokens))
    if not counts:
        raise ValueError("empty_structure_manifest")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing_to_overwrite_worker_output")
    checkpoint_hash = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()
    if checkpoint_hash != CHECKPOINT_SHA256:
        raise ValueError("unexpected_checkpoint")
    records = json.loads(args.input.read_text())

    # GPU imports deliberately excluded from ordinary offline tests.
    import torch
    from bionemo.utils.hydra import load_model_config
    from bionemo.model.molecule.megamolbart.infer import MegaMolBARTInference

    torch.manual_seed(42)
    cfg = load_model_config(config_name="megamolbart_infer.yaml",
                            config_path="/workspace/bionemo/examples/tests/conf/")
    cfg.model.downstream_task.restore_from_path = str(args.checkpoint)
    os.environ["BIONEMO_HOME"] = "/tmp/bionemo"
    model = MegaMolBARTInference(cfg, interactive=True, inference_batch_size_for_warmup=1)
    model.eval()
    limit = min(model.model.cfg.seq_length, model.model.cfg.max_position_embeddings)
    counts = check_structures(records, model.tokenizer, limit)
    result = []
    # Fixed single-structure calls avoid any dependence on batch composition.
    # seq_to_embeddings uses mask-aware mean pooling, with no input augmentation.
    with torch.inference_mode():
        first = model.seq_to_embeddings([records[0]["canonical_smiles"]])
        repeated = model.seq_to_embeddings([records[0]["canonical_smiles"]])
        if not torch.equal(first, repeated):
            raise ValueError("nonrepeatable_embedding_smoke_test")
        for i, row in enumerate(records):
            vector = model.seq_to_embeddings([row["canonical_smiles"]])[0].float().cpu()
            if not torch.isfinite(vector).all():
                raise ValueError("nonfinite_embedding")
            result.append(dict(row, embedding=vector.tolist(), token_count=counts[i]))
            if (i + 1) % 100 == 0:
                print(f"Embedded {i + 1}/{len(records)}", flush=True)
    output = {
        "model_id": MODEL_ID, "model_version": MODEL_VERSION,
        "checkpoint_sha256": checkpoint_hash, "container_image_digest": IMAGE_DIGEST,
        "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "pooling": "mean of encoder hidden states over unpadded input tokens",
        "input_transformation": "none; direct seq_to_embeddings on frozen canonical SMILES",
        "max_supported_tokens": int(limit), "max_observed_tokens": max(counts),
        "unknown_tokens": 0, "all_tokenizations_round_trip": True,
        "repeat_smoke_exact_match": True, "torch_version": torch.__version__,
        "gpu": torch.cuda.get_device_name(0), "records": result,
    }
    args.output.write_text(json.dumps(output, allow_nan=False) + "\n")
    print(f"Completed {len(result)} structures; dimension={len(result[0]['embedding'])}")


if __name__ == "__main__":
    main()
