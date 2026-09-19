# Team B verification

`baseline_selection.json` records training/validation counts, the eight candidate
configurations, selected parameters, calibration choice and validation metrics.
`baseline_test.json` and `baseline_reliability.png` report the untouched test partition.
The random forest achieved AUROC 0.7598, sensitivity 0.7838 and specificity 0.5484 on
105 compounds. Modest specificity and small-sample calibration limits remain material.

`privacy_synthetic.json` records the real local privacy model plus supplemental rules
on ten synthetic fixtures. Character-level precision was 0.9677 and recall 1.0; all
listed scientific values survived. The seven false-positive characters came from the
repeated-name/email example. These are fixture results, not a general privacy claim.
The full local scan/review/approval/export/DILI path passed with outbound socket
connections and DNS lookup patched to fail.

The official privacy model also flagged valid held-out SMILES as names/secrets and
an FDA compound ID as an account number. The gateway does not silently suppress these
findings. Scientific validation makes those fields eligible for explicit, individual
retention acknowledgements; absent acknowledgements block approval. This exception
was explicitly approved by the user and is exercised in the integration evaluation.

Ordinary offline tests cover curation, split integrity, identity and atom-map checks,
failure records, output schemas, redaction formats, invalid input, expiry, host/origin
checks, approval invalidation, concurrent edits and scientific retention. The final
targeted baseline/privacy suite passed 25 tests; the unchanged curation tests also
passed in the preceding 50-test full run. One additional invalid-ID regression accounts
for the current total of 51 tests.

Live loopback HTTP verification passed for the served UI assets, real synthetic scan,
approval, sanitized export, local DILI prediction and reset. JavaScript syntax and Python
compilation checks pass. The user completed the browser smoke test successfully after the server was started
for them. Browser smoke verification is complete (user-reported).

Merge verification: all 57 Team A offline checks passed with RDKit installed, including
the new real cached Team B handoff test. Team B's 51-test suite passed before the final
shared-schema regression addition; the seven-test baseline suite then passed, bringing
the current Team B test count to 52. No model retraining or score tuning occurred.

The MolMIM embedding comparison is prepared but has no tracked result. Its live/GPU
embedding cache and initial report are intentionally ignored under `artifacts/`. A
tracked result must identify the exact deployed model/version, preserve the checked-in
split checksum and include the stated unknown ZINC15 pretraining-overlap limitation.
The real deployment passed a smoke test on 2026-09-19, but full-cohort acquisition is
blocked: 11 frozen structures exceed the deployed checkpoint's 128-token limit.
No compounds were excluded and no candidate evaluation was run; see the
[experiment card](../../toxicity/model_cards/dili_bionemo_molmim_experiment.md).

The subsequent [MegaMolBART experiment](../../toxicity/model_cards/dili_bionemo_megamolbart_experiment.md)
completed on all 802 structures with the unchanged split. Its fixed logistic head
scored test AUROC 0.612467 and AP 0.805224, below the published RF's 0.759808 and
0.880970. No improvement is supported. Detailed predictions, reliability observations,
nearest-training structures and checksums remain in ignored
`artifacts/runs/bionemo_megamolbart_logistic_test.json`. That original evaluation is
unchanged. A later user-requested
[train/validation-only diagnosis](../../toxicity/model_cards/dili_bionemo_train_validation_diagnosis.md)
examines regularization without scoring new candidates on the test partition;
it is explicitly exploratory, not additional held-out improvement evidence.
