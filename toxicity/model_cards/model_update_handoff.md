# Model-update research handoff

2026-09-20 · `model-update` · review draft against repository HEAD `c62a985`.
This summarizes local branch experiments; it does not indicate a merged change.

## Recommendation

Retain the existing Morgan-fingerprint random forest (RF). BioNeMo-based heads,
XGBoost, small neural nets, Tanimoto SVM and ensembles were tested. Some improved
internal cross-validation metrics, but none demonstrated a reliable improvement
that justifies replacing RF. This is a useful negative result for these specific
representations, recipes and data—not proof that RF cannot be improved.

This research is separate from the team's discovery-first demo, which uses
BioNeMo Boltz2 upstream and the existing RF for DILI assessment. The toxicity
representation tested here is MegaMolBART, not Boltz2. No production model or v2
response contract was changed. Outputs concern drug-level DILI labels, not
patient-level incidence or proof of safety.

## Completed steps / current step / next

1. Audited the dataset, preprocessing, frozen split and existing RF recipe.
2. Checked real BioNeMo access. MolMIM could not cover 11 long structures;
   MegaMolBART produced verified embeddings for all 802 compounds, without truncation.
3. Evaluated the initial fixed embedding/logistic head on the existing test cohort.
4. Reproduced the missing RF artifact to a scratch path and verified its functional
   metrics; used this checked artifact for subsequent RF validation comparisons.
5. Completed exploratory training/validation follow-ups: regularized logistic heads,
   feature concatenation, RF/embedding fusion, XGBoost, MLPs and Tanimoto SVM.
6. Audited training out-of-fold errors, source labels and external-data overlap.
7. Completed RF + Tanimoto SVM late fusion with paired per-fold intervals.
8. **Current: strengthen the handoff's limitations and evidence for teammate review;
   retain RF.** No additional models or overlap checks are run by this documentation step.
9. **Next, only if agreed:** perform a read-only internal tautomer-overlap audit,
   define the improvement objective, and approve a genuinely independent,
   identity-checked, endpoint-compatible evaluation cohort before scoring.

Research pipeline: frozen structures/labels/split → Morgan and/or cached
MegaMolBART features → training-only nested selection → validation threshold →
comparison and error audit. The original test evaluation is historical evidence;
later model searches did not generate new test predictions.

## Fixed data and evaluation boundary

- DILIrank2: 802 standardized structures; Most/Less concern = 1, No concern = 0,
  Ambiguous excluded. Train 539 (339 positive), validation 158 (95 positive),
  test 105 (74 positive).
- `dilirank_parent_v1`: restricted counterion removal, stereochemistry/isotopes
  preserved, no tautomer canonicalization. Morgan radius 2, 2,048 bits, chirality.
- Frozen scaffold/connectivity grouping prevents the checked identities/groups
  crossing partitions. It does not eliminate every analogue relationship or prove
  absence of all chemical/pretraining overlap. Exact MegaMolBART ZINC15 training
  membership is unknown.
- Follow-up comparisons use the same three outer training folds (143/231/165
  held-out compounds), with candidate choices by mean inner-fold average precision
  (AP). Scaling and any calibration are fitted inside the relevant training subset.
  RF's original validation-selected recipe is held fixed, not newly optimized.
- Final candidate thresholds maximize validation balanced accuracy, then sensitivity,
  then favor the lower threshold. Validation operating metrics are therefore optimistic.
  No follow-up hyperparameters, ensemble weights or calibrators use test labels.
- Earlier test inspection and repeated development analysis make the follow-ups
  exploratory. Nested CV does not turn them into a new confirmatory study.
- The saved protocols specify fitting/selection rules, but no common prospective
  superiority rule requiring an AUROC gain of 0.05 and an interval excluding zero
  was found. That rule is **not** retrospectively attributed to these experiments.
  The recommendation to retain RF is an evidence-based exploratory judgement,
  not a failed preregistered superiority test or proof of equivalence. Any future
  acceptance rule, primary metric and uncertainty method must be agreed before
  the next evaluation; favorable and unfavorable results must both be reported.

Open leakage check: a within-cohort canonical-tautomer overlap audit across all
802 structures and their frozen partitions has not been verified. The external
audit found seven canonical-tautomer/no-stereochemistry matches to frozen-cohort
records (four train, one validation, two test); these are review flags, not proof
that all forms are interchangeable or that the frozen train/test split leaks.
Literal scaffold/connectivity grouping does not guarantee tautomer-disjointness.
The recorded test and training-CV AUROCs also involve different cohorts and fitting
sizes, so their difference cannot diagnose leakage. This remains an open check;
no structures, split assignments or reported metrics were changed or re-evaluated.
Diagnostic details are in `artifacts/external_audit/review65_summary.md`.

Frozen input checksums (SHA256):

```text
data/processed/dilirank2_model_ready.csv
997ad736dc1d282c2a0b3b4a7f9fca2d05740eacb7c6ec9d7cdf7919f312d750
data/manifests/dili_baseline_split.json
e3d14890336c92e8428e83382092ef6577b20b9651e5a69e8ec245f21020938e
artifacts/embeddings/megamolbart_dilirank2.json
7990795575c2d2637e60c61d5cc8cb674b4bc6dc42970fff4047bd27b1d19397
```

The embedding cache binds structure ID, canonical SMILES, model/version/checkpoint,
pooling/preprocessing versions and checksums. It contains actual 512-dimensional
MegaMolBART embeddings from `nvidia/clara/megamolbart:1.0`, not synthetic vectors.
Checkpoint/runtime evidence and official references are in the
[initial BioNeMo card](dili_bionemo_megamolbart_experiment.md).

## Exploratory comparison

CV columns are arithmetic means of the same three outer training folds, not pooled
OOF scores or test results. Brier is lower-is-better. Validation uses the same 158
compounds; only the final training-selected candidate from each procedure reaches it.
Values below are rounded to six decimals; run JSONs retain full precision.

| Representation / model | CV AUROC | CV AP | CV Brier | Validation AUROC | Validation AP | Validation Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Morgan RF reference | 0.706945 | 0.810318 | 0.206516 | 0.743525 | 0.769629 | 0.196662 |
| Morgan logistic (hybrid-run control) | 0.710669 | 0.788547 | 0.212518 | — | — | — |
| MegaMolBART regularized logistic | 0.665913 | 0.753941 | 0.224213 | 0.651963 | 0.754420 | 0.263724 |
| Morgan + MegaMolBART feature-concatenation logistic | 0.699764 | 0.788802 | 0.222503 | 0.692732 | 0.733775 | 0.210923 |
| RF + MegaMolBART logistic late fusion | 0.715607 | 0.817375 | 0.205436 | 0.733500 | 0.771386 | 0.201682 |
| Morgan XGBoost (bounded grid; see note) | 0.616560 | 0.724113 | 0.234669 | 0.683793 | 0.735809 | 0.218228 |
| Morgan MLP | 0.704779 | 0.777824 | 0.223905 | — | — | — |
| MegaMolBART MLP | 0.678996 | 0.771618 | 0.245876 | 0.668839 | 0.761044 | 0.269211 |
| Morgan Tanimoto SVM | 0.723608 | 0.811506 | 0.196922 | 0.698747 | 0.737675 | 0.215428 |
| RF + Tanimoto SVM late fusion | 0.724246 | 0.810532 | 0.197052 | 0.715121 | 0.753521 | 0.208258 |

XGBoost scope note: eight configurations covered depth 2/4, 100/300 trees and
L2 penalty 10/1, with learning rate fixed at 0.05 and no early stopping. Final
selection chose depth 2, 100 trees, L2 penalty 1. This bounded search does not
establish the best achievable XGBoost performance; choosing the smallest tree
configuration alone establishes neither underfitting nor a faulty run. RF used
`class_weight=None` and XGBoost `scale_pos_weight=1`, so neither selected model
used class reweighting. RF's earlier search did consider class weights, unlike
this XGBoost grid; their tuning histories were not identical. RF received grouped
sigmoid calibration within each fitting subset, whereas XGBoost had no fitted
calibrator. Brier scores validly compare the complete pipelines, but do not
isolate algorithm differences under matched calibration. See the
[XGBoost protocol and results](dili_morgan_xgboost_experiment.md).

MLP rows report each representation's internally selected head. Joint MLP selection
chose Morgan in all outer folds, but MegaMolBART on full training; the latter alone
was evaluated on validation. Likewise, the hybrid procedure chose concatenation
in every outer fold and on full training; Morgan logistic has no separate validation
evaluation. These are selection procedures, not one identical fitted model across folds.

Representation coverage is limited: MegaMolBART embeddings were paired with linear
logistic and neural heads, not directly with RF or another tree ensemble. Late
fusion with Morgan RF is not an embedding-to-tree experiment. These results should
not be generalized to every predictor family using the same embeddings.

Validation operating points; confusion matrices are `[[TN, FP], [FN, TP]]`:

| Final candidate | Threshold | Sensitivity | Specificity | Confusion matrix |
| --- | ---: | ---: | ---: | --- |
| RF | 0.558199 | 0.736842 | 0.730159 | [[46,17],[25,70]] |
| MegaMolBART logistic | 0.665414 | 0.536842 | 0.761905 | [[48,15],[44,51]] |
| Feature-concatenation logistic | 0.583088 | 0.736842 | 0.666667 | [[42,21],[25,70]] |
| RF + MegaMolBART logistic | 0.493691 | 0.747368 | 0.698413 | [[44,19],[24,71]] |
| XGBoost | 0.660307 | 0.557895 | 0.777778 | [[49,14],[42,53]] |
| Selected MegaMolBART MLP | 0.866739 | 0.431579 | 0.841270 | [[53,10],[54,41]] |
| Tanimoto SVM | 0.458119 | 0.831579 | 0.555556 | [[35,28],[16,79]] |
| RF + SVM | 0.465756 | 0.831579 | 0.555556 | [[35,28],[16,79]] |

RF + MegaMolBART slightly exceeds RF validation AP, while AUROC and Brier worsen.
RF + SVM increases sensitivity but sacrifices specificity. Neither supports an
unqualified “better model” claim. Probability outputs are assessed with Brier and
reliability bins; these assessments do not establish clinical calibration. Reports
include nearest-training Morgan similarities/structure IDs, which are descriptive
applicability information, not confidence scores or validated acceptance cutoffs.

The final RF/SVM choice is 25% RF + 75% SVM, C=10; two outer folds selected pure
SVM. Fusion-minus-RF mean AUROC difference is +0.017301 (conditional 95% interval
[-0.014985, +0.042624]); AP +0.000214 [-0.027378, +0.022078]; Brier -0.009464
[-0.015477, -0.002144]. These paired whole-group bootstrap intervals condition on
the fitted models and omit fitting/selection variability, shared-training dependence
and repeated-search uncertainty. The Brier advantage does not persist on validation.
Full per-fold intervals and numerical-verification retries are documented in the
[RF/SVM card](dili_rf_svm_ensemble.md); v3 is the completed verified artifact.

The training OOF audit measured RF/SVM Pearson correlation of probability residuals
(`label - predicted probability`) at approximately **0.982**. This is consistent
with limited complementary information, not proof of why fusion failed or that
fusion cannot help. The audit also measured other arms' correlations with RF,
but not every possible arm pair; 0.982 applies specifically to RF/SVM. Shared
labels, probability calibration and pooled-fold composition affect this statistic.
It was descriptive evidence, not a rule for learning blend weights. See the
[training-error audit](dili_morgan_svm_error_analysis.md).

## Earlier test comparison and RF recovery

Separate historical experiment: fixed MegaMolBART logistic C=1, with the same 105
test compounds as the recorded RF. This is not the regularized candidate above.

| Model | Test AUROC | Test AP | Brier | Validation-selected threshold | Sensitivity | Specificity | Confusion matrix |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Recorded RF | 0.759808 | 0.880970 | 0.177186 | 0.558199 | 0.783784 | 0.548387 | [[17,14],[16,58]] |
| Fixed MegaMolBART logistic | 0.612467 | 0.805224 | 0.311026 | 0.491029 | 0.756757 | 0.258065 | [[8,23],[18,56]] |

Original RF weights remain unavailable locally. The scratch reproduction at
`artifacts/runs/rf-reproduction-dmd67bwk/dili_baseline_reproduced.joblib` matches
recorded AUROC 0.7598081952920662, AP 0.8809698642142693 and Brier
0.17718553883463067 exactly; threshold 0.5581990015219468 versus recorded
0.558199001521947 matches beyond ten significant digits, and confusion matrices
match exactly. See the adjacent `functional_verification.json`.
This is functional reproduction, not recovery of the original pickle. Nothing was
promoted to `artifacts/models/dili_baseline.joblib`; the teammate request remains
open and the original artifact is preferred if recovered and verified.

## Error audit and external-data status

Seven pre-fusion model arms shared 65 training OOF errors at a diagnostic 0.5
threshold (64 false positives, one false negative), but also made different errors.
This does **not** mean every model fails on exactly the same compounds; the newest
RF/SVM fusion was not included in that seven-arm count. No mapping mismatches were
found against the pinned enriched source for the 539 training labels. That check
is not clinical label adjudication and does not authorize relabeling.

External-source review found substantial overlap. Of 65 initially remaining TDC
records, 51 currently lack the identified overlap/disagreement flags (23 positive,
28 negative). They are **not an approved independent cohort**: identity/stereochemistry,
endpoint harmonization, shared provenance and licensing still need review. No
external scoring or automatic exclusions occurred. See the
[curation follow-up](dili_curation_followup.md) for the updated audit and limitations.

## Evidence map and reproduction

All run paths below are under ignored `artifacts/runs/`, ending in `report.json`:

| Run directory | Detail / implementation |
| --- | --- |
| `megamolbart_regularized_candidate_v1` | [Regularized candidate](dili_bionemo_regularized_candidate.md) |
| `bionemo_hybrid_v1` | [Feature-concatenation runner](../src/bionemo_hybrid.py) |
| `bionemo_ensemble_v1` | [RF/embedding fusion runner](../src/bionemo_ensemble.py) |
| `morgan_xgboost_v1` | [XGBoost card](dili_morgan_xgboost_experiment.md) |
| `bionemo_mlp_v2` | [MLP card](dili_bionemo_mlp_experiment.md), including convergence retry |
| `morgan_svm_v1` | [SVM and error-audit card](dili_morgan_svm_error_analysis.md) |
| `rf_svm_ensemble_v3` | [Fusion card](dili_rf_svm_ensemble.md), including v1/v2 verification retries |

Use the locked CPU environment in `toxicity/requirements-model.lock`; optional
XGBoost 3.0.5 uses `toxicity/requirements-xgboost.lock` and an isolated installation.
The following commands run from the repository root. Full experiment reproduction
requires the real checksum-verified embedding cache, trusted scratch RF and any
prior control artifacts pinned by the runner—not merely a fresh Git clone.

```bash
# Offline tests; the additional external-audit test is local evidence, not tracked source.
PYTHONPATH=artifacts/experimental_deps/xgboost-3.0.5:. toxicity/.venv/bin/python -m pytest toxicity/tests artifacts/external_audit/test_review65.py -q

# Read-only inspection of the fusion protocol and current helper regression tests.
toxicity/.venv/bin/python -m toxicity.src.rf_svm_ensemble --print-protocol
toxicity/.venv/bin/python -m pytest toxicity/tests/test_research_common.py -q

# Optional CPU reproduction: choose a NEW output directory each time.
toxicity/.venv/bin/python -m toxicity.src.rf_svm_ensemble --output-dir artifacts/runs/rf_svm_ensemble_handoff_reproduction_01
```

Individual cards provide the other reproduction commands. No test-set evaluation
rerun is needed for this handoff. GPU/live embedding regeneration is optional and
documented separately in the initial BioNeMo card; credentials remain outside the
repository and outputs. Load only trusted joblib artifacts. Use the fusion runner's
`predict_bundle` helper for deterministic RF probability/threshold behavior.

Pre-refactor offline verification on 2026-09-20: **154 passed, six skipped** (five tests need the
original RF artifact; one needs optional h5py). No live/GPU tests are included.

The subsequent [research-code refactor](model_update_refactor.md) passed **173 tests,
six skipped** with the same full command and preserved the reported results. The
historical standalone fusion verifier requires matching pre-refactor sources because
it checks their hashes; its rejection of changed sources must not be bypassed.
The refactor note records source preservation and separate behavior-compatibility checks.

## Candidate research directions — untested, subject to approval

These are hypotheses, not commitments, expected gains or reasons to reopen the
original test set. Each needs a bounded protocol and an appropriate independent
evaluation; none changes the recommendation to retain RF now.

- **Ordinal severity or auxiliary learning.** `SeverityClass` and `vDILI-Concern`
  are retained in `data/processed/dilirank2_enriched.csv`. The current binary target
  maps concern categories; it does not directly collapse the severity field.
  Severity, concern and confidence are not interchangeable, and Ambiguous concern
  is not an additional ordinal severity level. A severity endpoint needs a separately
  defined evaluation; an auxiliary severity objective could still be evaluated
  against the unchanged binary endpoint. Neither field may become an input feature
  that reveals the target. Confidence weighting would require a defensible confidence
  annotation, not a severity proxy. See the [FDA dataset definitions](https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-rank-dilirank-20-dataset).
- **Non-structural dose/exposure features.** Published work motivates investigating
  daily dose, but does not establish a gain for this cohort or pipeline. Dose is not
  an input to these models and would require external curation, harmonized units,
  route/regimen definitions and a missing-data policy. It must also be available at
  the intended prediction stage; a novel discovery compound may have no established
  clinical dose. See the [original dose/lipophilicity study](https://pubmed.ncbi.nlm.nih.gov/23258593/).
- **Abstention or a reliability layer.** Evaluate whether RF can decline predictions
  while reducing error among retained compounds. Report coverage, retained-cohort
  error and class-specific sensitivity/specificity, not just a better score after
  exclusions. The 64/1 shared-error count at diagnostic threshold 0.5 does not itself
  identify a successful abstention rule; nearest-compound similarity is not calibrated
  confidence. Conformal methods need a separate, appropriate calibration design and
  justified exchangeability/shift assumptions; scaffold separation alone does not
  supply a coverage guarantee. See the [conformal prediction reference](https://arxiv.org/abs/2107.07511).
- **Mechanism-derived features.** Target-context predictions, for example against
  a proposed liver-toxicity-relevant target such as BSEP/ABCB11, could be explored
  with the team's Boltz2 capability. They add target context and pretrained
  information, not an independent biological measurement: predicted binding affinity
  is not demonstrated functional inhibition, exposure or a DILI mechanism. Target
  suitability, assay-grounded validation and training-overlap review would precede
  any improvement claim. This is substantially larger than the completed comparisons;
  the [Boltz2 paper](https://www.biorxiv.org/content/10.1101/2025.06.14.659707v1)
  describes affinity prediction, not validation of this proposed toxicity workflow.

## Teammate review decisions

- Confirm retaining RF and keeping this research separate from the demo requirements.
- Keep the original-RF artifact request open; do not silently promote scratch weights.
- Decide whether to authorize a read-only internal tautomer-overlap audit. Preserve
  the frozen design and report any flags for review rather than silently repairing it.
- Agree the next objective before more searches: ranking, sensitivity at a specified
  specificity, or probability calibration, plus the minimum useful improvement.
- If pursuing external validation, approve identities, labels, independence and
  permitted data use before freezing the cohort and scoring a fixed model shortlist.
- Review source/tests/cards before authorizing a commit. Several research files are
  currently untracked, and ignored artifacts/caches are not delivered by Git. Decide
  how to share approved evidence with checksums and licence constraints; never secrets.

This handoff changes no shared BUILD_PLAN/README, source code, frozen inputs,
model artifacts, thresholds or contracts. It does not authorize commit, push,
model promotion or further model selection.
