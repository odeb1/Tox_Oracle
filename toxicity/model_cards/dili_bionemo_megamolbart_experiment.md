# Frozen MegaMolBART + logistic regression experiment

## Held-out outcome

Completed on 2026-09-19. **This experiment does not support replacing or improving
the RF baseline with this fixed MegaMolBART + logistic head.** No tuning was part
of this original evaluation. A later user-requested
[train/validation-only diagnosis](dili_bionemo_train_validation_diagnosis.md)
is exploratory and does not change these test results. It does not establish that every BioNeMo
representation or separately prespecified head would fail.

| Test measure | Existing calibrated Morgan RF | MegaMolBART + logistic |
| --- | ---: | ---: |
| AUROC | 0.759808 | 0.612467 |
| Average precision | 0.880970 | 0.805224 |
| Sensitivity | 0.783784 | 0.756757 |
| Specificity | 0.548387 | 0.258065 |
| Brier (lower is better) | 0.177186 | 0.311026 |
| Validation-selected threshold | 0.558199 | 0.491029 |
| Confusion matrix `[[TN, FP], [FN, TP]]` | `[[17,14],[16,58]]` | `[[8,23],[18,56]]` |

Candidate validation AUROC/AP were 0.654135/0.750312; validation Brier was 0.304887.
Five test reliability bins (mean prediction → observed positive fraction) were
0.069931→0.619048, 0.608658→0.619048, 0.943393→0.619048,
0.994675→0.857143 and 0.999750→0.809524. These small-bin observations show substantial
probability miscalibration, not clinically calibrated risk. Nothing was calibrated
against test labels. No confidence interval or statistical superiority claim is made;
the RF artifact needed for paired score comparisons was unavailable.

Nearest-training-compound Morgan Tanimoto on the frozen test set had median
0.307692 and minimum 0.088235. The ignored JSON report contains each nearest
training structure ID/similarity, each test prediction, calibration bins, and provenance:
`artifacts/runs/bionemo_megamolbart_logistic_test.json`.
The real embedding cache is `artifacts/embeddings/megamolbart_dilirank2.json`, SHA256
`7990795575c2d2637e60c61d5cc8cb674b4bc6dc42970fff4047bd27b1d19397`.
Evaluation runtime: Python 3.13.0, NumPy 2.5.3, SciPy 1.18.1, scikit-learn 1.7.2,
RDKit 2025.9.6. Package versions are also saved in the JSON report.

## Design frozen before candidate test evaluation (2026-09-19)

MegaMolBART was selected for full-cohort input compatibility after MolMIM failed on
11 long structures, not by comparing test scores. All 802 frozen structures remain.
No MLP, feature selection, hyperparameter search, probability calibration fitting,
or model fine-tuning is performed. Fit StandardScaler and LogisticRegression
(`C=1`, `max_iter=5000`, seed 42) on the 539 training compounds only. Select the
threshold on the 158 validation compounds with the existing balanced-accuracy rule
(ties: sensitivity, then lower threshold). Evaluate once on the same 105 test
compounds (74 positive) as the published RF report. This is an exploratory comparison
on a previously reported benchmark, not a new confirmatory holdout.

The target is FDA DILIrank2 drug-level concern: Most/Less concern positive, No concern
negative, Ambiguous excluded. Parent preprocessing remains `dilirank_parent_v1`.
The dataset SHA256 is
`997ad736dc1d282c2a0b3b4a7f9fca2d05740eacb7c6ec9d7cdf7919f312d750`;
the scaffold/connectivity split SHA256 is
`e3d14890336c92e8428e83382092ef6577b20b9651e5a69e8ec245f21020938e`.
Both are pinned in the experiment runner. RF code, artifacts, and v2 contracts are
unchanged. The RF comparison uses the checked-in report; original RF weights are
not locally available for a paired prediction/uncertainty analysis.

## Verified representation

- NVIDIA NGC resource: `nvidia/clara/megamolbart:1.0`.
- Checkpoint `megamolbart.nemo` SHA256:
  `108923c3081e6d0debd76c9e33d692af18d46b71f8001c2d6c1eaa3fb4df032e`.
- Runtime image: `nvcr.io/nim/nvidia/molmim` at digest
  `sha256:7700c5556935a93055bee5367d36acb6d3e55d22fd1ba28503f5447656fa63fa`.
  This image supplies the BioNeMo framework; this experiment loads **MegaMolBART**,
  not the MolMIM weights or API. No undocumented MegaMolBART NIM endpoint is assumed.
- Actual checkpoint: 512-token input/position limit and 512-dimensional output,
  checked at runtime. Generic NVIDIA pages describe other configurations; actual
  checkpoint identity and behavior take precedence over an assumed dimension.
- Encoder outputs are averaged over unpadded input tokens using BioNeMo's
  `MegaMolBARTInference.seq_to_embeddings`. No BOS/EOS, SMILES augmentation,
  canonicalization changes, truncation, or missing-vector substitution.
- Fixed single-structure batches; dropout disabled with `eval()`; inference-only
  execution; repeat smoke test matched exactly.
- GPU worker runs as the file-owning user in a detached network-isolated container
  on the existing L40S. It receives only structure IDs and canonical SMILES, no labels
  or credentials. All 802 structures passed length, vocabulary and round-trip checks.

Cache records bind structure identity, canonical SMILES, model/version/checkpoint,
pooling version, preprocessing version and dataset/split checksums. They have
per-record/vector checksums. Provenance records the worker/input/output hashes,
container digest and GPU/runtime versions. Outputs remain under ignored `artifacts/`.

## Limitations

ZINC15 pretraining membership is unavailable; exact unsupervised molecular overlap is
unknown, not proven absent. Large or unusual drugs can be outside the pretraining
distribution. Nearest-training Morgan similarity is reported as descriptive
applicability information, not a guarantee. Logistic outputs are treated as
probabilities only for Brier and reliability assessment; no calibration claim follows.
The outputs are not patient-level DILI incidence or proof of safety. No replacement
of the production RF or shared interface is part of this experiment.

## Official references

- [NVIDIA MegaMolBART catalog](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/clara/models/megamolbart)
- [BioNeMo checkpoint limits](https://docs.nvidia.com/bionemo-framework/1.10/bionemo-fw-for-model-training-fw.html)
- [MegaMolBART inference tutorial](https://docs.nvidia.com/bionemo-framework/1.10/notebooks/MMB_GenerativeAI_Inference_with_examples.html)

## Reproduce

Offline: install `toxicity/requirements-model.lock` in a dedicated environment,
then run `python -m pytest toxicity/tests/test_bionemo_experiment.py -q` and
`python -m toxicity.src.bionemo_experiment audit` from the repository root.

Export a **label-free** manifest locally:

```sh
toxicity/.venv/bin/python - <<'PY'
from toxicity.src.bionemo_experiment import load_frozen_inputs, save_json, ROOT
rows, *_ = load_frozen_inputs()
save_json(ROOT / 'artifacts/embeddings/megamolbart_input.json',
          [{k: r[k] for k in ('structure_id', 'canonical_smiles')} for r in rows])
PY
```

Optional live/GPU: obtain the exact checkpoint through authenticated NVIDIA NGC,
keeping credentials outside the repository, and mount its directory read-only at
`/checkpoint`. Copy the label-free manifest and `toxicity/src/megamolbart_worker.py`
to a dedicated directory mounted at `/work`. In the pinned image, run:

```sh
python /work/megamolbart_worker.py \
  --checkpoint /checkpoint/megamolbart.nemo \
  --input /work/megamolbart_input.json \
  --output /work/megamolbart_output.json
```

Use Docker `--network none --gpus device=0 --shm-size=2g`, the owning user's UID/GID,
and `--entrypoint python` when passing the worker path directly to `docker run`.
No NGC key is needed inside this worker. The worker refuses an existing output file.
Copy the completed output into local `artifacts/embeddings/`, then run offline:

```sh
toxicity/.venv/bin/python -m toxicity.src.bionemo_experiment import-megamolbart \
  --raw artifacts/embeddings/megamolbart_output.json \
  --cache artifacts/embeddings/megamolbart_dilirank2.json
toxicity/.venv/bin/python -m toxicity.src.bionemo_experiment evaluate \
  --cache artifacts/embeddings/megamolbart_dilirank2.json \
  --output artifacts/runs/bionemo_megamolbart_logistic_test.json
```
