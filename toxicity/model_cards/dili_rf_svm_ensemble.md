# RF + Tanimoto SVM late fusion

Branch-only exploratory comparison. Completed run: `rf_svm_ensemble_v3`.
Final training-only choice: **25% RF + 75% sigmoid-calibrated SVM, C=10**.
No evidence here justifies replacing RF. No test/external scoring or promotion.

## Fixed design and reused machinery

Same 802-compound DILIrank2 cohort, 539 training / 158 validation / 105 test,
unchanged `dilirank_parent_v1`, labels, scaffold/connectivity groups and chiral
2048-bit radius-2 Morgan fingerprints. Dataset and split hashes remain
`997ad736dc1d282c2a0b3b4a7f9fca2d05740eacb7c6ec9d7cdf7919f312d750` and
`e3d14890336c92e8428e83382092ef6577b20b9651e5a69e8ec245f21020938e`.

The new runner reuses `bionemo_ensemble.blend`, `choose`, `fit_rf`,
`bionemo_candidate.folds/subset/fold_ids`, and `morgan_svm.fit_svm`. It does not
modify those existing modules or substitute full-training predictions for OOF ones.

- RF weights: 0, 0.25, 0.5, 0.75, 1. SVM C: 0.01, 0.1, 1, 10, 100.
- Jointly select C and weight by arithmetic mean inner-fold AP, as in the existing
  ensemble. Exact ties favor higher RF weight, then smaller C. Pure RF is allowed
  once as `(1, None)`: 21 combinations, not a forced blend.
- Three identical outer training folds, with three inner grouped folds within
  each fitting subset; StratifiedGroupKFold, shuffled, seed 42.
- Both arms have fixed sigmoid calibration, `ensemble=False`, using three further
  grouped folds wholly inside every fitting subset. SVC internal probability CV
  is disabled. There is no blend recalibration or feature selection.
- Standalone SVM control selects C from the weight-zero configurations inside
  each outer fitting subset. RF uses its unchanged fixed recipe. All arms share
  each outer holdout. The prior OOF audit is not used to fit blend weights.
- Final C/weight selection uses training only. Only the chosen blend reaches
  validation, where the existing balanced-accuracy/sensitivity/lower-threshold rule
  chooses its threshold. Pure RF would retain its stored threshold.
- The checksum-verified scratch RF is reused only after selection for validation.
  Original teammate weights remain preferred if recovered; nothing is promoted.
- Per-run budget: 15 calibrated RF fits; at most 67 calibrated SVM fits. Actual
  v3 used 64 SVM fits because selected/control C values coincided in every outer
  fold. No adaptive search expansion. CPU only; no dependency changes or secrets.

## Mean nested-training outer-holdout results

These evaluate the selection procedure, not the single final full-training blend.

| Metric | RF | Standalone SVM | Selected fusion procedure |
| --- | ---: | ---: | ---: |
| AUROC | 0.7069451025222556 | 0.7236080524727693 | 0.7242457059081272 |
| Average precision | 0.8103182142158131 | 0.8115057240960875 | 0.8105317973132459 |
| Brier, lower is better | 0.20651620829628722 | 0.19692237862711495 | 0.19705235486699124 |

The fusion procedure is almost indistinguishable from standalone SVM internally.
Two of three outer selections chose pure SVM; only fold 1 chose a mixed model.
The full-training inner selection AP is 0.8252449983879838, which is a selection
score, not a replacement for the nested estimate above.

## Paired differences and conditional intervals

Differences are **selected fusion minus comparator**: positive AUROC/AP and
negative Brier favor fusion. Brackets are 95% conditional percentile intervals.

| Outer fold | Holdout n | RF weight / C | Delta AUROC vs RF [interval] | Delta AP vs RF [interval] | Delta Brier vs RF [interval] |
| --- | ---: | --- | --- | --- | --- |
| 1 | 143 | 0.25 / 1 | +0.015065 [-0.021563, +0.050155] | +0.008260 [-0.019197, +0.034735] | -0.005381 [-0.013751, +0.003116] |
| 2 | 231 | 0 / 10 | +0.044838 [-0.018906, +0.095068] | +0.021922 [-0.034604, +0.055828] | -0.013170 [-0.022011, +0.000173] |
| 3 | 165 | 0 / 1 | -0.008001 [-0.064402, +0.041123] | -0.029541 [-0.079323, +0.016683] | -0.009840 [-0.024594, +0.005459] |
| Arithmetic mean | 539 total | Selection procedure | +0.017301 [-0.014985, +0.042624] | +0.000214 [-0.027378, +0.022078] | -0.009464 [-0.015477, -0.002144] |

| Comparison to standalone SVM | Delta AUROC [interval] | Delta AP [interval] | Delta Brier [interval] |
| --- | --- | --- | --- |
| Fold 1 | +0.001913 [-0.012839, +0.017864] | -0.002922 [-0.018263, +0.010177] | +0.000390 [-0.002310, +0.003029] |
| Fold 2 | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] |
| Fold 3 | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] |
| Arithmetic mean | +0.000638 [-0.004280, +0.005955] | -0.000974 [-0.006088, +0.003392] | +0.000130 [-0.000770, +0.001010] |

The zero intervals in folds 2/3 reflect identical selected and standalone-SVM
predictions, not certainty about population performance.

Earlier reports did not implement uncertainty intervals. This run adds a declared
paired group bootstrap: 2,000 draws per fold, seeds 43/44/45, resampling whole
scaffold/connectivity groups with replacement. Identical sampled rows are used
for all model arms. All 2,000 draws were valid in every fold. Single-class draws
would be discarded jointly without redraw. Mean intervals use the arithmetic
mean of each replicate's paired fold differences, retaining only replicates
valid in all three folds. No model is refitted during resampling.

The pairing principle follows [SciPy's bootstrap documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html);
this implementation resamples groups, rather than SciPy's default individual
observations. These intervals condition on fitted models, the split and observed
groups. They omit model-fitting/selection variability, dependence from overlapping
training sets, repeated-search uncertainty and multiplicity. They are descriptive,
not an independent-CV significance test or confirmatory superiority evidence.
The mean Brier interval lies below zero versus RF, but ranking intervals include
zero and the Brier advantage does not carry over to validation.

## Final validation comparison

Same 158 compounds, 95 positive / 63 negative. The chosen blend was fixed before
validation; no other mixture was compared there to select weights.

| Metric | Fixed RF | Final 25% RF / 75% SVM |
| --- | ---: | ---: |
| AUROC | 0.7435254803675857 | 0.7151211361737678 |
| Average precision | 0.7696285308220074 | 0.7535213859034533 |
| Brier | 0.19666174846635165 | 0.20825800695568164 |
| Validation-selected threshold | 0.5581990015219468 | 0.4657560896602195 |
| Sensitivity | 0.7368421052631579 | 0.8315789473684211 |
| Specificity | 0.7301587301587301 | 0.5555555555555556 |
| Confusion matrix [[TN, FP], [FN, TP]] | [[46, 17], [25, 70]] | [[35, 28], [16, 79]] |

Higher sensitivity comes with lower specificity. Threshold-dependent validation
metrics are optimistic because thresholds were selected there. Reliability
curves (five quantile bins) and nearest-training Morgan Tanimoto/structure IDs
for all 158 queries are recorded. Blend mean-prediction/observed-fraction pairs
are 0.2315/0.2813, 0.4486/0.5161, 0.5787/0.6875, 0.7218/0.7419,
0.8522/0.7813. Blending calibrated arms does not establish a calibrated blend;
nearest similarity is not confidence or a validated applicability cutoff.

## Numerical verification history

All three executions used the same scientific grid, folds and selection rules.
The first two reached validation but failed post-save verification; they are
preserved, not presented as completed validated artifacts:

1. v1 required bitwise probability equality. Parallel RF summation introduced
   differences up to 1.1102230246251565e-16 after reload.
2. v2 adopted the prior ensemble's 1e-14 probability tolerance and additionally
   required identical thresholded classes. One probability at the exact selected
   threshold crossed that boundary after reload, causing this check to fail.
3. v3 executes RF fitting/calibration and probability calculations through a
   sequential joblib backend, without modifying RF hyperparameters or stored
   weights. Both bitwise probability and class equality now pass, including a
   separate-process reload. Use `predict_bundle` for deterministic inference;
   directly bypassing that helper may reintroduce parallel-summation roundoff.

V1 and v2 retain protocols, fold checkpoints, saved artifacts, `failure.json`
and execution-checksummed source snapshots. These were verification fixes, not
metric-driven retries. Selected C/weights are identical across all three runs;
per-fold and validation metrics agree within 1e-14 and recorded validation
confusion matrices are identical. The total executed budget includes all three
runs, not just one run's budget.

## Outputs and reproduction

Completed outputs: `artifacts/runs/rf_svm_ensemble_v3/` contains protocol, three
outer-fold checkpoints, full report and `ensemble.joblib`. Report SHA256:
`a96a27f302d3f16201fc8ed4af22cc42f62abcf0738c9da1e04f3429a6a59f2e`.
Artifact SHA256:
`6b88a12ada959066b1dfb603bd5803afc1fc775d82777c98725262dfc829a339`.
Hashes identify these files; reproducibility does not require identical pickle bytes.

```bash
# Existing locked CPU environment, verified scratch RF and prior SVM artifacts.
toxicity/.venv/bin/python -m toxicity.src.rf_svm_ensemble --print-protocol
toxicity/.venv/bin/python -m toxicity.src.rf_svm_ensemble --output-dir artifacts/runs/rf_svm_ensemble_reproduction_01
toxicity/.venv/bin/python -m pytest toxicity/tests/test_rf_svm_ensemble.py -q
PYTHONPATH=artifacts/experimental_deps/xgboost-3.0.5:. toxicity/.venv/bin/python -m pytest toxicity/tests artifacts/external_audit/test_review65.py -q
# Read-only independent verification of the completed v3 outputs:
PYTHONPATH=. toxicity/.venv/bin/python artifacts/runs/verify_rf_svm_ensemble.py
```

Output directories must be new; overwrite is refused. No network, GPU, credentials
or live tests are required. New offline tests cover nested boundaries, calibration,
pairing, whole-group resampling, degenerate draws, serialization, deterministic
execution without RF-parameter mutation, and refusal of untrusted artifacts.
Verification: **154 passed, six skipped**, including 13 new fusion tests. Skips
are five original-RF-artifact tests and one optional h5py test.

Independent verification reproduced all bootstrap bounds to 1e-12 using group
multiplicities as sample weights rather than expanded rows. Controls match prior
RF/SVM OOF predictions within 1e-12; all fold, calibration, metric, threshold,
source checksum and artifact-reload checks passed. Frozen data/split, prior RF/SVM
artifacts, baseline reports and dependencies were checked unchanged. No shared
contract changes, BUILD_PLAN/README edits, commits, pushes or model promotion.

This remains exploratory after previous test inspection and repeated development
analysis. Scaffold groups do not remove every analogue relationship. No patient
incidence, safety or clinically validated probability interpretation is supported.
