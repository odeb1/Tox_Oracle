# Model-update branch: research progress

Branch-only working notes for teammate review. Do not update BUILD_PLAN.md or
READMEs from this work. No commit, push, merge or production integration authorized.

## Whole roadmap

| Step | Status | Result / next gate |
| --- | --- | --- |
| 1. Audit Team B RF and data | Done | Baseline preserved; labels and preprocessing documented |
| 2. Freeze evaluation boundaries | Done | 802 compounds; scaffold/connectivity train 539 / validation 158 / test 105 |
| 3. Verify BioNeMo and test MolMIM | Done, limited | MolMIM token limit prevents full frozen-cohort coverage |
| 4. Generate MegaMolBART embeddings | Done | Real cached embeddings for all 802 compounds |
| 5. Initial embedding logistic comparison | Done | Did not outperform RF on original held-out test |
| 6. Diagnose / regularize logistic head | Done, exploratory | Candidate saved; no further test scoring |
| 7. Audit external DILI sources | Done | 65 TDC rows need identity/label/independence review |
| 8. Compare fingerprint, embedding and hybrid logistic models | Done, exploratory | Hybrid selected; no clear advantage over Morgan logistic; results below |
| 9. Recover trusted RF artifact and consider prediction ensemble | Blocked | Original RF weights absent locally; no silent RF retraining |
| 10. Review external cohort | Pending | Audit remainder is not approved evaluation data |
| 11. Freeze external protocol and selected artifacts | Pending | Review endpoint, overlap, thresholds and uncertainty analysis |
| 12. Paired external evaluation | Pending | Same compounds for both models; no tuning on external labels |
| 13. Teammate review and integration decision | Pending | No improvement or safety claims without supporting evidence |

## Pipeline

```text
Structures + compound-level DILI labels
  → unchanged parent preprocessing and frozen scaffold/connectivity partitions
  → parallel representations:
      Morgan bits → original RF baseline (preserved)
      Morgan bits → logistic control
      BioNeMo embeddings → logistic control
      Morgan bits + BioNeMo embeddings → hybrid logistic
  → training-only grouped CV chooses the exploratory logistic arm and penalty
  → validation chooses only that selected candidate's operating threshold
  → independently reviewed external cohort (not yet available)
  → paired metrics, calibration assessment and nearest-training-compound context
  → teammate review
```

Embeddings are numerical molecular representations, not DILI predictions by
themselves. The current BioNeMo representation is MegaMolBART; this step introduces
no new model provider, GPU dependency, credential or embedding download.

## Step 8 protocol, recorded before executing the comparison

Three logistic arms: Morgan, embedding, concatenated hybrid. Morgan is exactly the
baseline's chiral radius-2 2048-bit representation; cached MegaMolBART adds 512
dimensions. Each arm uses StandardScaler (including Morgan bits), fit only within
each fitting subset, and L2 logistic regression. No feature selection, PCA, block
weight tuning, calibration or MLP. Use only C = [1, .1, .01, .001, .0001].

All arms share identical three-fold StratifiedGroupKFold splits, shuffle=True,
seed=42, restricted to the frozen 539 training compounds. Select by arithmetic
mean fold AP. Exact ties favor smaller C, then Morgan, embedding, hybrid.

Three outer training-only folds repeat arm/C selection within three inner folds.
Report both per-arm nested estimates (C selected internally) and the entire
arm-selection procedure's nested estimate. Select the final arm/C using CV on
all training compounds, then fit on training only. Only that selected candidate
is scored on validation to select the unchanged balanced-accuracy threshold
(ties: sensitivity, then smaller threshold). No model choice from validation.
This avoids publishing additional validation results for every new candidate.

Report AUROC, AP and Brier across outer folds; sensitivity, specificity, confusion
matrix, validation threshold, Brier, reliability bins and nearest training compound
for the selected candidate on validation. Nested CV has no validation-derived
threshold: threshold-dependent outer metrics are intentionally not claimed.
Probability outputs are not assumed calibrated. No external/test labels or predictions
enter selection, scaling, tuning or thresholding. Whole-cache checks include test
structures/vectors only for integrity, not modeling.

Previous test inspection and repeated development analysis mean this remains
exploratory. Nested CV does not restore a fresh confirmatory test. Original RF
aggregate test metrics must not be compared to these internal CV estimates as if
they came from the same evaluation cohort. Representation pretraining overlap
remains unknown. Outputs are not patient-level incidence or proof of safety.

RF/BioNeMo prediction ensembling is explicitly deferred, not silently replaced with
a new forest. It also needs a reviewed training-only procedure for ensemble weights.

## Reproduction and artifacts

Offline, CPU-only, using existing verified embeddings:

```sh
toxicity/.venv/bin/python -m pytest toxicity/tests/test_bionemo_hybrid.py -q
toxicity/.venv/bin/python -m toxicity.src.bionemo_hybrid
```

Default output: `artifacts/runs/bionemo_hybrid_v1/` (ignored). Existing directories
are refused; to reproduce use `--output-dir artifacts/runs/bionemo_hybrid_repeat`.
The report includes fold IDs, source/cache/dataset/split hashes, package versions,
per-arm selections and metrics, selected validation predictions and applicability.
The saved model expects concatenated [2048 Morgan bits, 512 cached embeddings] in
that order; its pipeline selects the arm's columns. Never load untrusted joblib files.

## Step 8 result — 19 September 2026

**Current position: hybrid development run complete; RF recovery and external
cohort review are the next gates.** No new test-set scoring was performed.

Training-only selection chose **hybrid, C=0.001**, with selection-CV mean AP
0.802580. That selection score is not an unbiased performance estimate. The
matched nested training-only comparison (mean outer-fold metrics) was:

| Logistic representation | AUROC ↑ | Average precision ↑ | Brier ↓ |
| --- | ---: | ---: | ---: |
| Morgan fingerprints | 0.710669 | 0.788547 | 0.212518 |
| MegaMolBART embeddings | 0.665913 | 0.753941 | 0.224213 |
| Morgan + MegaMolBART | 0.699764 | 0.788802 | 0.222503 |

The hybrid AP advantage over Morgan logistic is only 0.000255; Morgan has better
AUROC and Brier. No uncertainty analysis establishes an advantage, and no RF
comparison was run. **These results do not demonstrate a useful hybrid advantage
or improvement over the original RF.** Do not pick a different winner after seeing
these metrics: the prespecified training-CV AP rule selected the saved candidate.

All three outer inner-selections chose hybrid, but chose different C values
(.0001, .1, .001), indicating sensitivity to the fitting subset. The whole
arm-selection procedure's nested metrics equal the hybrid row for this run.
The embedding arm reproduces the earlier regularized candidate's nested metrics.

Only the final training-selected hybrid was scored on the 158 validation compounds
(95 positive / 63 negative), solely for threshold selection and descriptive reporting:

| Validation measure | Value |
| --- | ---: |
| AUROC | 0.692732 |
| Average precision | 0.733775 |
| Brier | 0.210923 |
| Validation-selected threshold | 0.583088 |
| Sensitivity | 0.736842 |
| Specificity | 0.666667 |
| Confusion matrix `[[TN, FP], [FN, TP]]` | `[[42,21],[25,70]]` |

Validation has been reused previously; these are not new confirmatory held-out
results. Reliability bins and nearest-training Morgan Tanimoto information are
saved in the report, without fitting a calibrator. The candidate is an exploratory
artifact, not a replacement deployed model.

Saved `artifacts/runs/bionemo_hybrid_v1/candidate.joblib` SHA256:
`068db9a3974665171383d8a376d52975cd25769b6b1e7b061e8c845c86d2a073`.
Reload reproduced validation probabilities exactly. Source, frozen data/split and
embedding-cache checksums are recorded in the adjacent `report.json`.

Verification: eight new synthetic offline tests passed. Full default toxicity suite:
63 passed / 6 skipped (five require absent original RF weights, one requires the
optional HDF5 audit dependency). Tests cover shared/nested group boundaries,
training-only scaling/selection, selected-only validation thresholding, no test
label/structure feature extraction, correct feature-column selection, deterministic
tie rules, trusted artifact round-trip and refusal to overwrite outputs.

BUILD_PLAN.md and READMEs were not edited in this step. Baseline code/artifacts,
prior reports, the frozen split and v2 interfaces remain unchanged. Nothing was
committed, pushed or merged.
