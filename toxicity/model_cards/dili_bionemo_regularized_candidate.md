# Exploratory regularized MegaMolBART candidate

Date: 2026-09-19. **Experimental artifact only; not integrated into production.**
This follow-up was initiated after the original test result and development
diagnosis were known. The protocol is recorded prospectively for this run, but is
not a preregistered independent study. No new test-set scoring was performed.

## Procedure

The primary selection metric is average precision, matching the RF's primary
selection metric, but measured here by three-fold grouped CV within the frozen
539-compound training partition. Evaluate only the existing five C values
`[1, 0.1, 0.01, 0.001, 0.0001]`. Select the largest arithmetic mean fold AP; exact
ties favor the smallest C. No additional grid exploration or metric switching.

Every fitting fold learns its own StandardScaler and L2 logistic regression
(`max_iter=5000`, seed 42). Scaffold/connectivity groups remain disjoint. A
three-outer/three-inner nested grouped CV within training characterizes the entire
selection procedure. Outer holdout labels do not enter inner C selection.

Select final C by grouped CV on all training compounds, fit that model on training
only, and select its threshold using the unchanged validation balanced-accuracy
rule. Validation does not select C, features, weights or calibration. Previous
validation inspection is acknowledged; this does not make validation pristine.
Test labels are not extracted for analysis, and no test predictions are produced.

## Observed result

Final training-CV AP selected **C=0.1** (mean selection-CV AP 0.782023). It did not
select C=0.001, which looked best on validation in the earlier diagnosis. The
selection objective was not switched to obtain that validation result.

Nested training-CV mean AUROC was **0.665913**, AP **0.753941**, and Brier **0.224213**.
Outer folds selected C values `[0.0001, 0.001, 0.0001]` on their smaller fitting
subsets. The dependence on fitting subset cautions against treating one C as a
stable optimum. These are internal exploratory estimates, not test-set metrics.

For the final training-fitted C=0.1 candidate on 158 validation compounds:

| Measure | Value |
| --- | ---: |
| AUROC | 0.651963 |
| Average precision | 0.754420 |
| Brier | 0.263724 |
| Validation-selected threshold | 0.665414 |
| Sensitivity | 0.536842 |
| Specificity | 0.761905 |
| Confusion matrix `[[TN, FP], [FN, TP]]` | `[[48,15],[44,51]]` |

Validation Brier remains worse than the training-prevalence constant reference
(0.240511 in the diagnosis). Calibration bins and nearest-training-compound
similarities are saved in the JSON report. No calibrator was fitted and no claim of
well-calibrated risk is made. The probability outputs are drug-level DILI concern,
not patient incidence or proof of safety.

**Conclusion:** the procedure and candidate are reproducible, but this evidence
does not support RF replacement or an improvement claim. Nested CV does not undo
earlier inspection of this dataset. A fresh independent evaluation, with its
design explicitly reviewed, is needed for a confirmatory improvement claim.
Exact ZINC15 representation-pretraining overlap remains unknown.

## Artifacts and reproduction

The same verified MegaMolBART checkpoint, immutable embedding cache, preprocessing,
and frozen split from the [initial experiment](dili_bionemo_megamolbart_experiment.md)
are used. No GPU or credential is needed for this offline stage.

```sh
toxicity/.venv/bin/python -m toxicity.src.bionemo_candidate
toxicity/.venv/bin/python -m pytest toxicity/tests/test_bionemo_candidate.py -q
```

The command refuses an existing output directory. To reproduce, supply a fresh
`--output-dir artifacts/runs/<new-name>`. It writes:

- `artifacts/runs/megamolbart_regularized_candidate_v1/candidate.joblib`: fitted
  scaler + logistic model, validation threshold, representation identity and metadata.
- `artifacts/runs/megamolbart_regularized_candidate_v1/report.json`: full nested
  fold memberships, all selection scores, validation metrics/reliability, applicability,
  input/source/artifact checksums and package versions.

Artifact SHA256:
`05e40440c31b472cc8dc83913ab12264bd11eb58729ebba0a3e01ae8b2cc8238`.
Reloading this locally generated artifact reproduced validation probabilities
exactly. Joblib uses pickle: load only trusted artifacts, never untrusted downloads.
No RF file was overwritten; the v2 interface and original test report remain
unchanged. Nothing was committed or pushed by this experiment.
