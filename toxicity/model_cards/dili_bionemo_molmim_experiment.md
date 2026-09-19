# ToxOracle MolMIM embedding experiment

**Status:** adapter and frozen-split experiment are implemented. The real GPU service
passed a smoke test, but the full-cohort comparison is **blocked by input length**.
No full-dataset embedding cache, fitted candidate, or comparative metrics have been
generated **for MolMIM**. Do not exclude compounds or truncate SMILES to make this
experiment run. The separate [MegaMolBART comparison](dili_bionemo_megamolbart_experiment.md)
subsequently covered the full cohort, but its fixed logistic head did not improve
the held-out RF results.

## Deployment and compatibility audit (2026-09-19)

The Brev `my-instance` L40S deployment runs the detached `toxoracle-molmim`
container. The completed download survived the interrupted SSH connection;
`GET /v1/health/ready` returned HTTP 200 with `status: ready`. The API is bound to
remote loopback port 8000, not a public interface. Reconnect using
`brev shell my-instance`; reconnecting does not require downloading the image again.
The GPU instance remains running and may continue to incur charges.

Verified runtime identity:

- Image: `nvcr.io/nim/nvidia/molmim:1.0.0`.
- Image digest: `sha256:7700c5556935a93055bee5367d36acb6d3e55d22fd1ba28503f5447656fa63fa`.
- Checkpoint resource: `nim/nvidia/molmim:1.3`, file `molmim_70m_24_3.nemo`.
- Checkpoint SHA256: `10522c9db6018c355313f9f01a0edea2b021ddc0a5a22ae4540cbf5bdafbd1f5`.
- Tokenizer model SHA256: `4c3781699489ae1d52446d3a688948cf86b26d1ee704feb39517efd88de45b8d`.
- Tokenizer vocabulary SHA256: `3b43e98c839813e2fefcef6b7401cae04019871bd2d78d52f1827252ea50c755`.
- Observed embedding dimension: 512, verified using `CCO` and `c1ccccc1`;
  repeated smoke requests returned identical vectors. This is not DILI evaluation.

The checkpoint specifies `seq_length=128` and `max_position_embeddings=128`.
The deployed BioNeMo `Inference.tokenize` rejects longer token sequences rather
than silently truncating them. Counting the frozen canonical SMILES with the deployed
regex tokenizer and vocabulary found zero unknown-token structures, but 11 of 802
structures exceed 128 tokens (maximum 178). All tokenized strings round-tripped.
No DILI labels were sent to the service or used in this compatibility check.

| Compound | Frozen partition | Tokens |
| --- | --- | ---: |
| Angiotensin ii acetate | train | 133 |
| Setmelanotide acetate | train | 133 |
| Micafungin sodium | train | 167 |
| Heparin sodium | train | 141 |
| Leuprolide acetate | train | 152 |
| Pafolacianine sodium | validation | 178 |
| Anidulafungin | validation | 149 |
| Argipressin | validation | 131 |
| Temsirolimus | validation | 139 |
| Sincalide | test | 138 |
| Dactinomycin | test | 174 |

A real `/embedding` request for the unchanged Micafungin sodium structure returned
HTTP 500; the container traceback confirmed `ValueError: One or more sequence
exceeds max length(128).` Reapplying `dilirank_parent_v1` to all 802 canonical
structures produced no identity mismatches.

**Decision needed:** investigate a verified representation supporting all frozen
structures, or explicitly review a separate coverage-limited experiment. The latter
would not satisfy the original full-cohort comparison and must not be compared
directly with the published 105-compound RF metrics. Do not extend positional limits,
change SMILES/preprocessing, pad missing embeddings, or replace test compounds as an
unreviewed workaround. No model-improvement claim is supported.

## Prespecified comparison

- Baseline: the unchanged Morgan radius-2, 2,048-bit random forest documented in
  `dili_baseline_v1.md`.
- Candidate: NVIDIA BioNeMo MolMIM NIM `/embedding` output, standardized using
  training-partition statistics, followed by logistic regression with fixed `C=1`.
- Data: the same 802 DILIrank-derived structures and exact checked-in
  train/validation/test memberships as the baseline.
- Selection: no embedding feature selection or classifier hyperparameter search.
  The decision threshold is selected on validation balanced accuracy using the
  baseline tie-break policy. Test labels are used only by the final evaluation.
- Outputs: AUROC, average precision, sensitivity, specificity, confusion matrix,
  validation-selected threshold, Brier score, five-bin calibration observations,
  and nearest-training-compound Morgan Tanimoto similarity.

The first experiment deliberately does not use an MLP. With 539 training compounds,
a neural head would introduce architecture and regularization choices before the
representation itself has been tested. It can be a later, separately frozen experiment.

## Verified BioNeMo capability and access boundary

NVIDIA's MolMIM NIM 1.0.0 documentation defines `POST /embedding` with a
`sequences` array of SMILES and an `embeddings` array response. The documentation
does not specify the returned vector dimension, so the adapter discovers it from the
first response and rejects any later mismatch. The exact deployed checkpoint/model
version must be supplied to the command; it is never inferred from vector length.

The NIM is a separately deployed GPU service. NVIDIA documents a single supported
GPU, at least 3 GB GPU memory, Docker, NVIDIA drivers and Container Toolkit, plus an
NGC account/key for container access. Credentials belong only in the deployment
environment and are neither accepted nor logged by the experiment command.

Official references:

- <https://docs.nvidia.com/nim/bionemo/molmim/latest/endpoints.html>
- <https://docs.nvidia.com/nim/bionemo/molmim/latest/deployment-guide.html>
- <https://docs.nvidia.com/nim/bionemo/molmim/latest/support-matrix.html>

## Cache and leakage controls

The ignored embedding cache binds every vector to `structure_id`, canonical SMILES,
MolMIM model ID/version, `dilirank_parent_v1`, dataset checksum and frozen-split
manifest checksum. It also records per-SMILES, per-vector, per-key and whole-record
checksums. Labels are not stored in the cache.

Dataset structure IDs, canonical SMILES, InChIKeys, connectivity groups and combined
scaffold/connectivity groups are disjoint across the frozen partitions. MolMIM was
pretrained without DILI labels on a large ZINC15 collection, but exact pretraining
molecule identities are not available here. Representation-pretraining overlap with
the DILI evaluation structures must therefore be reported as unknown, not absent.

## Interpretation

The output concerns a retrospective drug-level DILI label. It is not patient-level
incidence, exposure response, prospective clinical validation or proof of safety.
No improvement claim exists until real cached embeddings are evaluated on the frozen
test cohort. Even then, point differences should be presented with the small test-set
uncertainty and the unknown unsupervised-pretraining overlap.
