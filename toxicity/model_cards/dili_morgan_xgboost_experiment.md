# Morgan + XGBoost: bounded exploratory comparison

Status: completed branch-only research. **The tested XGBoost search underperformed
the fixed RF comparator. No replacement, promotion or improvement claim.**

This is separate from the team's delivery plan. BUILD_PLAN and READMEs are unchanged.
The small-MLP comparison has not been implemented or run by this experiment.

## Frozen design and scope

The existing 802-structure DILIrank2 snapshot, `dilirank_parent_v1`, and frozen
scaffold/connectivity split remain unchanged: 539 train, 158 validation, 105 test.
Most/Less DILI concern is positive, No concern is negative; Ambiguous is excluded.
Features are the baseline's chiral Morgan radius-2 / 2048-bit binary fingerprints.
No clinical metadata, external compounds, embeddings or pretrained models are inputs.

Dataset SHA256: `997ad736dc1d282c2a0b3b4a7f9fca2d05740eacb7c6ec9d7cdf7919f312d750`.
Split SHA256: `e3d14890336c92e8428e83382092ef6577b20b9651e5a69e8ec245f21020938e`.

XGBoost 3.0.5 ran locally on CPU. The existing model environment was not modified;
the optional dependency was installed under ignored experimental artifacts.
[Official installation documentation](https://xgboost.readthedocs.io/en/stable/install.html)
describes platform support. This run did not need Brev, GPU access or credentials.

## Protocol declared before fitting

`artifacts/runs/morgan_xgboost_v1/protocol.json` records parameters, source hashes,
dependency hashes and runtime before the first scientific fit.

- Eight configurations: depth 2/4, 100/300 trees, L2 penalty 10/1.
- Fixed learning rate 0.05, minimum child weight 5, row and column subsampling 0.8,
  no L1 penalty, class weight ratio 1, histogram trees, CPU, one thread, seed 42.
- Select maximum arithmetic mean **scikit-learn average precision**, not XGBoost's
  interpolated PR-AUC. Exact ties favor shallower trees, fewer trees, stronger L2.
- Three outer scaffold/connectivity-grouped training folds; three inner grouped
  folds within each outer fitting subset. Both use shuffle=True, seed=42.
- RF comparator: existing fixed 500-tree recipe, with its sigmoid calibration
  refitted only within each outer fitting subset using three grouped folds.
- No early stopping, scaling, feature selection or fitted XGBoost calibration.
- Select final XGBoost configuration using three grouped folds of all training;
  refit on training only. Validation selects its threshold by balanced accuracy,
  then sensitivity, then lower threshold. RF retains its stored threshold.
- No test feature/label arrays or predictions. Full-file integrity and group
  checks still read the frozen source/split. No external evaluation performed.

The code shares the existing fold, RF calibration, metric, threshold and
applicability implementations rather than adding a different scientific recipe.
RF hyperparameters/calibration were originally validation-selected and are fixed
here. Repeated development analysis and previously inspected test results mean
this is exploratory, not a fresh confirmatory comparison.

## Results

### Nested training CV: arithmetic means of three outer holdouts

| Metric | Fixed RF comparator | Training-selected XGBoost procedure |
| --- | ---: | ---: |
| AUROC | 0.7069451025222556 | 0.6165602855108167 |
| Average precision | 0.8103182142158131 | 0.7241134584064590 |
| Brier score, lower is better | 0.20651620829628717 | 0.23466948575784863 |

All three outer folds had lower XGBoost AUROC/AP and higher Brier than RF. These
are paired descriptive fold results, not an independence assumption or a formal
significance test. Pooled out-of-fold predictions and reliability bins are also
saved separately; pooled metrics are not substituted for fold means.

Final training-CV choice: depth **2**, **100** trees, L2 penalty **1**. Do not expand
the grid or select a different configuration based on the validation outcomes.

### Validation: same 158 compounds, 95 positive / 63 negative

| Metric | Existing RF reproduction | Selected XGBoost |
| --- | ---: | ---: |
| AUROC | 0.7435254803675857 | 0.6837928153717627 |
| Average precision | 0.7696285308220074 | 0.7358090152169219 |
| Sensitivity | 0.7368421052631579 | 0.5578947368421052 |
| Specificity | 0.7301587301587301 | 0.7777777777777778 |
| Validation-selected threshold | 0.5581990015219468 | 0.6603074669837952 |
| Brier score | 0.19666174846635165 | 0.21822805141453822 |
| Confusion matrix, `[[TN, FP], [FN, TP]]` | `[[46, 17], [25, 70]]` | `[[49, 14], [42, 53]]` |

XGBoost has higher specificity at its selected threshold but substantially lower
sensitivity; this is not evidence of overall superiority. Validation was used for
threshold selection, so threshold-dependent performance there is optimistic.
No new held-out **test** metrics were calculated.

## Probability quality and applicability

Both models output scores treated as probabilities for Brier and five-quantile-bin
reliability assessment. XGBoost is not calibrated; the sigmoid-calibrated RF is not
assumed clinically calibrated either. See `validation_reliability` and
`nested_training_cv.pooled_oof_reliability` in the report.

Every validation compound has the same nearest-training-compound Morgan Tanimoto
information for both models (`validation_applicability`, 158 records). Similarity
is descriptive, not a confidence probability or validated applicability cutoff.
Frozen scaffold/connectivity grouping reduces leakage but does not guarantee
absence of every tautomer, metabolite or analogue relationship.

These compound-level concern labels do not estimate patient DILI incidence. A
negative prediction is not proof of safety. This bounded result does not prove
that all XGBoost configurations or other representations would perform poorly.

## Preserved baseline and artifacts

The checksum-verified, functionally reproduced RF was used for final validation
only after XGBoost selection. It was never used to predict training-CV holdouts.
The original teammate artifact remains preferred if recovered; its request is
still open. No file was promoted to `artifacts/models/dili_baseline.joblib`.

New local run directory: `artifacts/runs/morgan_xgboost_v1/`.

- `protocol.json`: frozen before fitting, including source/runtime provenance.
- `report.json`: fold memberships, selected settings, all requested validation
  metrics, probabilities, reliability, applicability and limitations.
- `xgboost.ubj`: native XGBoost model; its decision threshold stays in the report
  at `validation.xgboost.threshold`. This is not a production/v2 model bundle.

Report SHA256: `cbfa3d1ac6813aaf097da803a819fcd683cf27091545af8b77813c04f10f910a`.
Model SHA256: `09e201fb42899138fc7859ce3a26e3ee303193a21d502867ed72946630eb301d`.

Native save/reload preserves all 158 validation probabilities exactly. A separate
check recomputed outer-fold and validation metrics from the saved predictions,
verified nested group boundaries and checked all source/protocol/model hashes.
Frozen data, split, baseline reports, baseline lockfile and RF artifact checksums
were unchanged after the run. No shared interface was changed.

## Reproducible commands

Run from the repository root, using the existing environment that exactly matches
`toxicity/requirements-model.lock`. These are the tested local macOS arm64 commands.
The dependency download is the only network step; all tests/training are offline.

```sh
# Optional isolated package; no changes to the baseline environment.
toxicity/.venv/bin/python -m pip install --no-deps --target artifacts/experimental_deps/xgboost-3.0.5 xgboost==3.0.5

# Inspect the fixed protocol without reading data or fitting models.
toxicity/.venv/bin/python -m toxicity.src.morgan_xgboost --print-protocol

# Run into a NEW directory. Existing output directories are always refused.
PYTHONPATH=artifacts/experimental_deps/xgboost-3.0.5:. toxicity/.venv/bin/python -m toxicity.src.morgan_xgboost --output-dir artifacts/runs/morgan_xgboost_v1_reproduction

# Full offline toxicity suite with the optional XGBoost CPU test enabled.
PYTHONPATH=artifacts/experimental_deps/xgboost-3.0.5:. toxicity/.venv/bin/python -m pytest toxicity/tests -q

# Without the optional dependency: pure guards still run, real-XGBoost test skips.
toxicity/.venv/bin/python -m pytest toxicity/tests/test_morgan_xgboost.py -q -rs
```

`toxicity/requirements-xgboost.lock` specifies the full baseline dependency pins
plus the optional XGBoost version for a separate experimental environment. Do not
install it over the baseline environment. Native library/platform changes can
affect numerical reproduction; the report records this run's versions/platform.

Checks: **85 passed, 6 skipped** for the full toxicity suite with XGBoost available.
Five skips concern the absent original production-path RF; one concerns optional
HDF5 support. All **16 new tests passed** with XGBoost. Without it, 15 passed and
one optional CPU test skipped. There are no live-service or GPU tests in this module.

## Position and next step

Completed: baseline/split audit and RF reproduction; real BioNeMo embeddings;
embedding LR and regularization; hybrid/ensemble experiments; external-data audit;
bounded Morgan/XGBoost comparison.

Next: predeclare a small, strongly regularized Morgan-input MLP comparison using
the same training-only grouped selection boundary. Do not reuse the test set to
choose its architecture. Independent external-data curation remains separate
work before any confirmatory superiority claim. RF stays the reference model.
