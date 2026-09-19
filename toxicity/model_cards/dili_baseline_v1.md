# ToxOracle DILI random forest v1

**Status:** trained and evaluated local baseline; exploratory research triage only.

## Data and target

FDA DILIrank 2.0 with curated PubChem structures, dataset SHA256
`997ad736dc1d282c2a0b3b4a7f9fca2d05740eacb7c6ec9d7cdf7919f312d750`.
802 unique structures: 508 positive (Most/Less concern), 294 negative (No concern).
Ambiguous and unsupported/unresolved structures are excluded, with provenance retained
by the curation pipeline. Drug labels are not patient outcomes or incidence estimates.

Standardisation: `dilirank_parent_v1`, RDKit 2025.09.6. Features: Morgan radius 2,
2,048 binary bits, chirality enabled. Labels, names, source URLs, severity and clinical
notes are not model inputs. Structure-only inference requires no exposure measurements.

## Training and evaluation

Related scaffold/connectivity groups stay together. Five grouped stratified folds,
seed 42: fold 0 test, fold 1 validation, remaining folds training. Acyclic molecules
group by connectivity. This yielded 539 training, 158 validation and 105 test compounds.
Uneven counts reflect scaffold grouping. Exact membership is in the split manifest.

Eight fixed 500-tree random forests were compared on validation average precision.
Sigmoid calibration used three grouped training-side folds and was retained because
validation Brier improved from 0.19865 to 0.19666. Threshold 0.558199 was selected on
validation balanced accuracy, with sensitivity breaking ties. The selected artifact
does not refit on validation or test data. A fingerprint logistic model is a reference.

| Test metric | Selected RF | Logistic reference |
|---|---:|---:|
| AUROC | 0.7598 | 0.6430 |
| Average precision | 0.8810 | 0.8010 |
| Sensitivity | 0.7838 | 0.8243 |
| Specificity | 0.5484 | 0.3548 |
| Brier score | 0.1772 | 0.2360 |

Test counts: 74 positive and 31 negative; positive prevalence 0.7048 is the relevant
no-skill average-precision reference. RF confusion matrix: TN 17, FP 14, FN 16, TP 58.
Calibration did not improve test Brier (raw RF: 0.1762); the validation-selected choice
is retained without tuning on test outcomes. Calibration is assessed, not guaranteed.
See the reliability plot and machine-readable reports in `evaluation/reports/`.

## Outputs and explanations

V2 scores/calls include the threshold, calibration status and nearest-training-compound
Tanimoto similarity. Similarity is not a confidence probability. No uncertainty interval
is implemented. Training membership includes compounds used to fit the model; validation
membership is separately warned because those compounds influenced selection.

TreeSHAP explains the raw forest positive-class output using training tree-path counts.
The response shows the ten strongest **present** fingerprint bits mapped to all matching
environments. It omits absent-bit contributions and is not a complete additive fragment
decomposition. Collision/repeated-environment contributions must not be added together.
Attribution is not a causal mechanism or an explanation of the calibrated score itself.

## Limitations

Small retrospective, selected small-molecule dataset with imperfect labels and chemical
coverage. Modest specificity; 14/31 negatives were flagged on this test set. No prospective,
patient-level, exposure-aware or clinical validation. No claim of superiority to published
DILI systems on different splits. Never interpret a negative prediction as proof of safety.
Scaffold grouping reduces structural leakage but does not remove all analogue similarity.

The three saved demo cases are chosen after evaluation by a fixed illustrative rule;
they are not a prespecified clinical validation cohort or documented preclinical misses.
Third-party dataset rights remain with their sources. Model artifacts are ignored locally.
