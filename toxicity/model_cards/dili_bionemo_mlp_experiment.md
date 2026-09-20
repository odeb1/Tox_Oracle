# Small MLP: Morgan versus cached BioNeMo embeddings

Branch-only, exploratory research. The existing RF, frozen cohort/split and v2
interface remain unchanged. This document is separate from BUILD_PLAN and READMEs.

**Outcome:** v2 completed. Neither tested MLP pipeline established an advantage
over RF. Keep the RF reference; do not promote the saved research MLP.

## Frozen design

Data: the existing 802 standardized DILIrank2 structures; 539 train, 158 validation,
105 test. Most/Less concern is positive, No concern is negative; Ambiguous and
unsupported structures remain excluded. No new external compounds are included.

Dataset SHA256: `997ad736dc1d282c2a0b3b4a7f9fca2d05740eacb7c6ec9d7cdf7919f312d750`.
Split SHA256: `e3d14890336c92e8428e83382092ef6577b20b9651e5a69e8ec245f21020938e`.
Preprocessing remains `dilirank_parent_v1`; no change to scaffold/connectivity groups.

Compare the same compounds/folds using:

1. Fixed existing Morgan/RF recipe, refitted inside each outer fitting subset.
2. Morgan fingerprints (radius 2, 2048 bits, chirality) with a small MLP.
3. Checksum-verified cached MegaMolBART embeddings (512 dimensions) with a small MLP.

The cache SHA256 is `7990795575c2d2637e60c61d5cc8cb674b4bc6dc42970fff4047bd27b1d19397`.
Its model/version, canonical-SMILES, preprocessing and per-record checksums are
validated by the existing cache contract. No live model/API calls, new embeddings,
credentials or GPU are needed. The original dataset and cache are not modified.

## Protocol, fixed before fitting

- One tanh hidden layer, width 16 or 32; L2 alpha 1, 10 or 100: six configurations
  per representation, twelve total. No concatenated-feature head or new ensemble.
- StandardScaler fitted only on selected columns inside each fitting subset,
  including for Morgan bits. The unused representation cannot enter that MLP.
- L-BFGS, maximum 2,000 iterations / 50,000 function calls, tolerance 1e-4; primary
  seed 42. No automatic early-stopping holdout, calibration fit or feature selection.
- Select representation and settings jointly by mean training-fold average
  precision. Exact ties favor Morgan, fewer hidden units, then stronger L2.
- Three outer grouped training folds with three inner grouped folds inside each
  outer fitting subset; all use StratifiedGroupKFold, shuffle=True, seed 42.
- Each outer fold reports both training-selected per-arm models and the procedure
  that chooses between arms. RF sigmoid calibration is refitted inside the same
  outer fitting subset using three grouped folds; RF settings are not retuned.
- Final representation/settings selection uses three grouped folds of all training.
  Only that selected MLP reaches validation; validation chooses its operating
  threshold using the existing balanced-accuracy/sensitivity/lower-threshold rule.
- Seeds 43 and 44 evaluate the primary-selected per-arm configurations in training
  CV only. This is descriptive, non-nested sensitivity analysis, **not** best-seed
  selection, a second ranking criterion or additional validation evaluation.
- A convergence warning or nonfinite fitted weights/loss aborts the experiment.
  Failed configurations are not silently discarded and the search is not expanded.
- Budget: 144 grid fits, six outer selected-per-arm fits, one final fit and twelve
  additional-seed fits: 163 MLP fits. Fit/predict linear-algebra threads limited to one.
- No test-label arrays or predictions. Whole-source/cache integrity checks still
  read the frozen files; no external evaluation takes place.

The existing dependency lock is sufficient; no environment changes are required.
[Scikit-learn's MLP documentation](https://scikit-learn.org/1.7/modules/neural_networks_supervised.html)
describes scaling sensitivity, L2 regularization and initialization variability.
[The pinned-version API](https://scikit-learn.org/1.7/modules/generated/sklearn.neural_network.MLPClassifier.html)
documents the solver and iteration controls. This implementation runs on CPU.

## Outputs and safeguards

New outputs go only into a fresh `artifacts/runs/bionemo_mlp_v2/` directory:

- `protocol.json`: settings, source/runtime hashes written before scientific fitting.
- `outer_fold_1.json` through `outer_fold_3.json`: completed-fold checkpoints.
- `report.json`: per-arm and selected-procedure CV results, selected-candidate/RF
  validation AUROC, AP, sensitivity, specificity, confusion matrix and thresholds;
  Brier/reliability, seed sensitivity, probabilities, applicability and limitations.
- `selected_mlp.joblib`: selected research pipeline, threshold and metadata; not a
  replacement v2 artifact. Save/reload validation probabilities must match exactly.
- `failure.json` only if a checked fitting error prevents completion. Partial
  checkpoints are not a completed or deployable candidate.

Only the checksum-verified, functionally reproduced RF may be loaded for final
validation, and it is not used for any CV predictions. The original teammate RF
artifact request remains open; the original is preferred if recovered. No file is
promoted to `artifacts/models/dili_baseline.joblib`.

### Preserved numerical failure and explicit retry

The first version used ReLU with L-BFGS and hit the 2,000-iteration limit during
inner fitting in outer fold 1. The configured convergence guard stopped it. No
outer fold completed and no validation predictions or candidate artifact were
produced. This is an incomplete fit, not a scored negative result for MLPs.

`artifacts/runs/bionemo_mlp_v1/` preserves that run's protocol, `failure.json` and
exact `source_snapshot.py`. Its protocol SHA256 is
`9beec7579bada2e676b5857b20cfc8781eb28a780480e4eb9b2a399dd7c41189`.

One separately recorded numerical retry, v2, switches to smooth tanh activation.
The representations, grid, solver, iteration limits, seeds, cohort, groups and
selection/evaluation rules stay fixed. This revision was motivated by fitting
failure, not held-out scores; it does not erase v1 or treat it as a completed
experiment. The 163-fit budget applies to v2, in addition to the incomplete v1 work.

## Interpretation limits

This is exploratory after previous test inspection and repeated development-data
analysis. Nested training CV does not create a new independent confirmation set.
RF hyperparameters/calibration were originally validation-selected and are fixed
here. Validation threshold-dependent metrics are optimistic because that threshold
was selected there. Do not compare nested-CV scores directly to the old test scores.

Equal hidden widths are not equal parameter counts for 2048-dimensional Morgan
versus 512-dimensional embeddings. Initialization sensitivity is not an uncertainty
interval. MLP probabilities are not assumed calibrated; Brier and reliability
assess rather than establish clinical calibration. Nearest-training-compound
Morgan similarity is descriptive, not confidence or a validated applicability cutoff.

Scaffold/connectivity grouping does not exclude every tautomer/analogue relationship.
Exact BioNeMo representation-pretraining compound overlap is unknown. Compound-level
DILI concern is neither patient DILI incidence nor proof of safety. No superiority
claim is warranted without credible held-out evaluation.

## Results: completed v2

### Nested training CV (mean of the same three outer holdouts)

| Metric | Fixed RF | Morgan MLP | BioNeMo MLP |
| --- | ---: | ---: | ---: |
| AUROC | 0.7069451025222556 | 0.7047786417542700 | 0.6789962560554423 |
| Average precision | 0.8103182142158131 | 0.7778244150966528 | 0.7716176778448219 |
| Brier, lower is better | 0.20651620829628722 | 0.2239054957296102 | 0.2458764065507317 |

Both arms selected their own settings within each outer fitting subset; these
numbers evaluate selection procedures, not one fixed configuration. The joint
representation-selection procedure chose Morgan in all three outer folds, so its
outer metrics equal the Morgan column. These are **not original test-set scores**.

### Final training-only choice and initialization sensitivity

Selecting on all 539 training compounds chose **BioNeMo embeddings, 32 tanh units,
alpha 10, seed 42**. The selected head has 512 inputs and 16,449 parameters and
converged in 455 iterations. The corresponding best Morgan configuration was
32 units / alpha 100. The final primary CV selection AP values were 0.7832426008
versus 0.7802815722: a small development-data difference, not evidence that
BioNeMo is superior.

At the fixed primary-selected per-arm configurations, non-nested training-CV AP:

| Seed | Morgan MLP | BioNeMo MLP |
| --- | ---: | ---: |
| 42 (primary) | 0.7802815721901113 | 0.7832426008278901 |
| 43 (sensitivity only) | 0.7802455041539121 | 0.7812857622640298 |
| 44 (sensitivity only) | 0.7804125540090597 | 0.7736064920819955 |

The representation ranking changes at seed 44. No seed was selected from these
results, and they did not change the final candidate. These sensitivity scores
must not replace the nested-CV estimates above.

### Validation: selected BioNeMo MLP versus unchanged RF

Same 158 compounds, 95 positive / 63 negative. Morgan MLP was not separately
evaluated on validation; representation selection was already complete.

| Metric | Existing RF reproduction | Selected BioNeMo MLP |
| --- | ---: | ---: |
| AUROC | 0.7435254803675857 | 0.6688387635756057 |
| Average precision | 0.7696285308220074 | 0.7610443206120413 |
| Sensitivity | 0.7368421052631579 | 0.43157894736842106 |
| Specificity | 0.7301587301587301 | 0.8412698412698413 |
| Validation-selected threshold | 0.5581990015219468 | 0.8667387278769721 |
| Brier score | 0.19666174846635165 | 0.2692110973018349 |
| Confusion matrix, `[[TN, FP], [FN, TP]]` | `[[46, 17], [25, 70]]` | `[[53, 10], [54, 41]]` |

Higher specificity came with substantially lower sensitivity; this is not a
general improvement. MLP validation ranking and Brier were worse. Five-quantile-bin
reliability records for both validation outputs and all training-OOF arms are in
the report. Every validation compound has nearest-training Morgan similarity
information (158 records). There are no new test/external predictions or metrics.

## Verification and provenance

All 12 new synthetic MLP tests passed; full toxicity suite: **97 passed, 6 skipped**
with the earlier optional XGBoost dependency enabled. Five skips concern the absent
original production-path RF; one concerns optional HDF5 support.

Independent checks recomputed every outer-fold metric and both validation metric
sets from saved probabilities, including the MLP validation threshold. They checked
that the OOF cohort is exactly the frozen 539 training identities, validation is
exactly the frozen 158, and all inner and RF-calibration groups remain within their
outer fitting subsets. Every saved selected-procedure probability agrees with the
arm chosen by that fold's inner CV.

Source, protocol, model, frozen dataset/split, embedding cache, RF reproduction and
dependency-lock checksums were verified. The v1 source snapshot matches its original
protocol hash. The v2 model reload reproduces all validation probabilities exactly.
No baseline artifact was promoted and no existing shared source/document was changed.

Final report: `artifacts/runs/bionemo_mlp_v2/report.json`.
Report SHA256: `50a21945c4f37aacefb2979e5a092ea1604aafcb128d96004698634c5c98aa60`.
Model SHA256: `c6956893a862501bac7c11864f95c4b4eb87edb0bf4f7e9bd23af32ab5c95c19`.

## Commands

Run from repository root with the existing environment matching
`toxicity/requirements-model.lock`. All commands below are offline and CPU-only.

```sh
# Print the protocol without loading data or fitting.
toxicity/.venv/bin/python -m toxicity.src.bionemo_mlp --print-protocol

# A NEW output directory is mandatory; existing runs are never overwritten.
toxicity/.venv/bin/python -m toxicity.src.bionemo_mlp --output-dir artifacts/runs/bionemo_mlp_v2_reproduction

# Synthetic MLP unit tests: no scientific cache or original RF artifact needed.
toxicity/.venv/bin/python -m pytest toxicity/tests/test_bionemo_mlp.py -q

# Full offline suite, with the earlier optional XGBoost CPU dependency enabled.
PYTHONPATH=artifacts/experimental_deps/xgboost-3.0.5:. toxicity/.venv/bin/python -m pytest toxicity/tests -q
```

Existing-output refusal preserves failed/partial runs too. Checkpoints document
completed folds but do not implement resume or authorize changing the protocol.
There are no live-service or GPU tests in this module.

## Project position

Completed before this experiment: RF/split audit and functional RF reproduction;
real BioNeMo embeddings; embedding LR/regularization; feature hybrid; prediction
ensemble; external-data audit; bounded XGBoost comparison.

Now completed: two-input small-MLP comparison, with the failed v1 and successful
numerical retry v2 both recorded. Keep RF as the reference; no candidate here
justifies replacement. The recommended next decision is independent label/identity
curation or a narrowly justified new hypothesis, not unbounded model searching.
External-data curation remains separate work; no cohort has been approved by this
experiment. No commit or push was performed.
