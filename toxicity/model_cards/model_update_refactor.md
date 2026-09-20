# Research-code refactor verification

2026-09-20 · `model-update` · behavior-preserving cleanup, not a new model experiment.

## Scope

The XGBoost, MLP, Tanimoto SVM and RF/SVM runners now share
[`research_common.py`](../src/research_common.py) for Morgan development-data
extraction, development-boundary validation, positive-class probability checks
and exact-version environment checks. MLP/SVM/fusion no longer import the XGBoost
runner to obtain model-independent utilities. The historical XGBoost helper names
remain available as compatibility imports; the optional XGBoost package remains
lazy-loaded only by its model factory.

The refactor preserves row order, test-partition exclusion, binary-feature checks,
class order, probability normalization tolerance, dtype, error messages and callers'
threading controls. Each runner retains its own scientific procedure. There is no
new generic training framework and no change to grids, folds, seed handling,
calibration, ensemble selection, thresholds, report field names or the v2 interface.
Future run provenance now includes the shared module's source checksum.

Only these four research runners were refactored. Existing RF, embedding generation,
curation/audit logic, other experiments, dependency locks and teammate-owned demo
code were left unchanged. This is not a claim of a repository-wide refactor.

## Checks performed

- Before: 154 offline tests passed, six skipped, including the local external-audit
  tests and isolated optional XGBoost installation.
- After: **173 passed, six skipped** with the same command; 19 new shared-helper
  tests cover dependency isolation, legacy imports, version-lock failures, probability
  semantics and exclusion of test structures/labels.
- Without the optional XGBoost installation: **165 passed, seven skipped** for
  `toxicity/tests` alone. The extra skip is the optional real-XGBoost CPU test;
  the local external-audit tests are not included in this second command.
- Complete before/after reports from four reduced-grid **synthetic** builds
  (XGBoost, MLP, SVM, RF/SVM) matched exactly as canonical JSON hashes. This covers
  predictions, selections, fold memberships, thresholds, metrics and fusion intervals
  in those fixtures. It is not a rerun of the full scientific experiments.
- Retained functions other than runner orchestration, and all protocol declarations,
  were AST-identical to their pre-refactor versions.
- Existing checksum-verified SVM and RF/SVM artifacts reloaded successfully with
  the refactored code. Their validation probabilities and thresholded classes matched
  the recorded outputs exactly. No fitting, threshold selection or test scoring occurred.
- Frozen data/split, baseline source/reports, contracts, saved run reports/joblib
  artifacts and shared BUILD_PLAN/root README checksums remained unchanged.

The six expected skips are five tests requiring the absent original RF artifact
and one optional h5py test. No live/GPU tests ran.

Re-run offline checks from the repository root with the existing locked environment:

```bash
toxicity/.venv/bin/python -m pytest toxicity/tests/test_research_common.py -q
PYTHONPATH=. toxicity/.venv/bin/python -m pytest toxicity/tests -q
# Optional isolated XGBoost wheel and local external-audit test file required:
PYTHONPATH=artifacts/experimental_deps/xgboost-3.0.5:. toxicity/.venv/bin/python -m pytest toxicity/tests artifacts/external_audit/test_review65.py -q
```

## Historical provenance and sharing

Pre-refactor copies of the four changed sources and a protected-file checksum
manifest are preserved locally in
`artifacts/refactor_snapshots/model_update_shared_helpers_20260920/`.
Their source hashes were checked against the historical SVM/fusion reports.
Existing reports still correctly identify the old code; their hashes were not
rewritten to imply that this refactor produced the historical results.

The old `artifacts/runs/verify_rf_svm_ensemble.py` checks historical source hashes
against `toxicity/src`. It therefore needs the matching historical source tree;
running it directly against refactored sources will reject the source mismatch.
Do not disable that guard. Current-code behavior compatibility was checked
separately as described above. Full scientific retraining was not needed or run.

The snapshot, model weights, embedding cache and full reports remain ignored local
artifacts; a Git push does not distribute them. Review any evidence-sharing package
separately for provenance and licences. Research source/tests/cards remain pending
explicit staging and commit review. No commit, push, model promotion or shared-doc
update is performed by this refactor.
