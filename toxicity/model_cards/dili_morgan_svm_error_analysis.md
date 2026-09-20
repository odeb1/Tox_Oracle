# Morgan Tanimoto SVM and training-only error audit

Branch-only exploratory research, separate from the team delivery plan.

Outcome: the SVM has modestly better nested-training mean AUROC/Brier than the
fixed RF, nearly tied AP, and worse validation AUROC/AP/Brier. This does not
establish superiority or justify replacing RF. No new ensemble was fitted.

## Pipeline status

Completed: RF functional reproduction; real BioNeMo embedding/LR comparison;
hybrid and RF/BioNeMo blend experiments; external-data overlap/provenance audit;
bounded XGBoost and small MLP comparisons; now training-only error analysis and
one bounded similarity-kernel SVM comparison.

Next recommended step: review the training hard-case queue and resolve an
independent external cohort's labels, overlap and licensing. Do not automatically
expand model search or promote any research artifact. The external audit has
not yet approved a clean independent evaluation cohort.

## Frozen inputs and fitting procedure

- Existing DILIrank2 cohort: 802 standardized structures, 539 training, 158
  validation, 105 test. Most/Less concern = 1, No concern = 0; existing exclusions
  and `dilirank_parent_v1` preprocessing remain unchanged.
- Dataset SHA256:
  `997ad736dc1d282c2a0b3b4a7f9fca2d05740eacb7c6ec9d7cdf7919f312d750`.
- Split SHA256:
  `e3d14890336c92e8428e83382092ef6577b20b9651e5a69e8ec245f21020938e`.
- Same scaffold/connectivity union groups, chiral radius-2 2048-bit Morgan
  fingerprints, no new features/scaling/feature selection or changed cohort.
- Tanimoto callable kernel uses float64 intersection/union to avoid byte overflow.
  Empty/empty similarity = 1; empty/nonempty = 0.
- Fixed C grid: 0.01, 0.1, 1, 10, 100. Select maximum arithmetic mean inner-fold
  probability AP; exact ties favor smaller C. No adaptive grid expansion.
- Three outer grouped training folds and three inner folds; shuffled
  StratifiedGroupKFold, seed 42. Each selected procedure is evaluated on its
  outer holdout, not on data used for hyperparameter selection.
- Every SVM fit uses fixed sigmoid calibration from three further grouped folds
  wholly inside that fitting subset, including inner tuning fits. Calibration
  uses `ensemble=False`, with the final base estimator refitted on that subset.
  SVC `probability=False` disables its implicit probability CV.
- SVC tolerance 0.001, maximum iterations 100000, shrinking enabled, no class
  weights. Convergence warnings or nonzero fit status abort rather than silently
  exclude a candidate. CPU only; existing model dependency lock is sufficient.
- Budget: 64 calibrated SVM fits / 256 underlying SVC fits. RF uses its fixed
  existing recipe, with grouped calibration refitted inside each outer fit.
- Only the final training-selected SVM sees validation. Validation selects its
  threshold using balanced accuracy, then sensitivity, then lower-threshold ties.
  RF retains its original stored threshold. No new test/external predictions.

Protocol, source/dependency/runtime checksums are saved before fitting. The
[SVC documentation](https://scikit-learn.org/1.7/modules/generated/sklearn.svm.SVC.html)
describes callable kernels and implicit probability CV;
[calibration documentation](https://scikit-learn.org/1.7/modules/calibration.html)
describes explicit cross-validation and `ensemble=False`.

## Results

Mean of the same three nested-training outer holdouts (not original test scores):

| Metric | RF | Tanimoto SVM |
| --- | ---: | ---: |
| AUROC | 0.7069451025222556 | 0.7236080524727693 |
| Average precision | 0.8103182142158131 | 0.8115057240960875 |
| Brier, lower is better | 0.20651620829628722 | 0.19692237862711495 |

Outer-fold selected C values were 1, 10, 1; final full-training selection chose 10.
SVM-minus-RF AP differences by fold were +0.0111816763548891,
+0.0219215115005584, -0.0295406582146243. This is not a consistent foldwise AP gain.
No uncertainty interval or statistical-superiority test is claimed.

Validation on identical 158 compounds (95 positive / 63 negative):

| Metric | Existing RF reproduction | Selected SVM |
| --- | ---: | ---: |
| AUROC | 0.7435254803675857 | 0.6987468671679199 |
| Average precision | 0.7696285308220074 | 0.7376754409202397 |
| Brier | 0.19666174846635165 | 0.2154275274285880 |
| Validation-selected threshold | 0.5581990015219468 | 0.4581189896500881 |
| Sensitivity | 0.7368421052631579 | 0.8315789473684211 |
| Specificity | 0.7301587301587301 | 0.5555555555555556 |
| Confusion matrix, [[TN, FP], [FN, TP]] | [[46, 17], [25, 70]] | [[35, 28], [16, 79]] |

Higher SVM sensitivity comes with lower specificity at these thresholds; it is
not a general improvement. Threshold-dependent validation metrics are optimistic
because thresholds were selected there. Validation is development evidence, not
a fresh confirmatory test, and must not drive further tuning.

Five quantile-bin reliability summaries are saved for both models and pooled OOF
predictions. SVM validation mean-prediction/observed-positive-fraction pairs are
0.2222/0.2813, 0.4435/0.5161, 0.5821/0.6875, 0.7344/0.7742, 0.8754/0.7500.
These assess probability behavior; sigmoid calibration does not establish
clinical calibration. All 158 validation compounds have nearest-training
structure IDs and Morgan Tanimoto similarities in the report; no applicability
cutoff is fitted or asserted.

## Training-only error audit

The audit aligns all 539 nested-OOF training predictions by structure ID, checks
identical outer-fold memberships and RF probabilities, rejects duplicates or
foreign IDs, and verifies dataset/split hashes. No validation or test outcomes
are used by the audit. A fixed 0.5 cutoff is diagnostic only, not an operating
threshold or a criterion for selecting model weights.

| Alternative | RF mistakes corrected | New mistakes relative to RF | Residual correlation with RF |
| --- | ---: | ---: | ---: |
| XGBoost | 50 | 73 | 0.9437 |
| Morgan MLP | 51 | 41 | 0.8878 |
| BioNeMo MLP | 60 | 81 | 0.8523 |
| BioNeMo LR | 23 | 48 | 0.9726 |
| Existing RF/BioNeMo blend | 18 | 24 | 0.9927 |
| Tanimoto SVM | 42 | 31 | 0.9820 |

SVM corrects 35 RF negative-class errors but introduces 11; for positives it
corrects 7 and introduces 20. Thus aggregate counts conceal sensitivity tradeoffs.
Probability calibration and this fixed cutoff affect the counts; they do not
supersede threshold-free ranking metrics or demonstrate a learnable routing rule.

Before adding SVM, all six audited models missed 67 compounds at 0.5. Including
SVM, all seven miss 65 (64 negatives, one positive). The saved hard-case queue
contains these training compounds, model probabilities, and nearest compounds
from each query's outer fitting fold, excluding the query's whole group. Consensus
mistakes flag scientific review, not incorrect labels: no relabeling or exclusions.

Recommendation: no automatic new blend. SVM residuals remain highly correlated
with RF and its mean nested-CV AP gain is only 0.00119. The Morgan MLP's differing
errors are a hypothesis, not proof of useful blending. Any future approved blend
needs weights and all base-model tuning/calibration nested entirely within
training, followed by genuinely independent confirmation. Do not select blend
weights from this pooled OOF audit or validation results.

## Outputs, reproduction and verification

Completed outputs (ignored research artifacts):

- `artifacts/runs/morgan_svm_v1/{protocol.json,report.json,svm.joblib}`.
- `artifacts/runs/training_error_audit_v1.json` (six-model audit).
- `artifacts/runs/training_error_audit_with_svm_v1.json` (seven-model audit).

Report SHA256:
`daae863ee3fb9756897ce1bde3ad933f711e5b77b1d3f34e8497db5439133595`.
Model SHA256:
`a59a3a81c2cbed5b99789b40dff47dec1984f14735558a234958c20715b0221c`.
Pickle checksums identify this artifact, not a requirement for reproducing metrics.

From the repository root, with the verified baseline environment and existing
scratch RF reproduction (never unpickle an untrusted downloaded artifact):

```bash
toxicity/.venv/bin/python -m toxicity.src.morgan_svm --print-protocol
toxicity/.venv/bin/python -m toxicity.src.morgan_svm --output-dir artifacts/runs/morgan_svm_reproduction_01
toxicity/.venv/bin/python -m toxicity.src.training_error_audit --svm-report artifacts/runs/morgan_svm_reproduction_01/report.json --output artifacts/runs/training_error_audit_reproduction_01.json
toxicity/.venv/bin/python -m pytest toxicity/tests/test_morgan_svm.py toxicity/tests/test_training_error_audit.py -q
PYTHONPATH=artifacts/experimental_deps/xgboost-3.0.5:. toxicity/.venv/bin/python -m pytest toxicity/tests -q
```

Output paths must be fresh; overwrite is refused. The audit additionally requires
the completed XGBoost, MLP-v2 and RF/BioNeMo-blend reports at its documented default
paths. It does not refit those models. No live/GPU tests or credentials are needed.

Verification: 24 new offline tests passed; full suite 121 passed, six skipped
(five require the absent original production RF, one optional h5py). Independently
recomputed per-fold/validation metrics, threshold, confusion matrices and reliability;
checked nested group/calibration boundaries, nearest-fold membership and hashes;
reloaded the SVM in a separate process and reproduced validation probabilities
exactly. The callable kernel is serialized under its importable module name.

Existing RF, frozen data/split, baseline reports and dependencies were hash-checked
unchanged. No source/contract from the existing implementation was edited; this
work adds two modules, two test files and this model card. BUILD_PLAN and READMEs
remain untouched. No commit, push or promotion. The original teammate RF remains
preferred if recovered; this experiment uses the verified scratch reproduction.

Prior test inspection and repeated development analysis limit all conclusions.
Scaffold/connectivity groups do not remove every analogue/tautomer relationship;
BioNeMo pretraining overlap remains unknown in the prior models. These are
compound-level DILI-concern models, not patient incidence or proof of safety.
