# Human DILI model — Team B

Own data curation, features, training, evaluation and batch inference. DILIrank 2.0
acquisition and structure curation are implemented. The structure-only random forest,
frozen evaluation split, batch v2 inference and fragment attribution are now implemented.
See the [local MVP runbook](../docs/runbooks/team-b-local-mvp.md) and
[baseline model card](model_cards/dili_baseline_v1.md).

The optional BioNeMo comparison is implemented separately and does not replace the
baseline or change the v2 response contract. Its status and prespecified design are in
the [MolMIM compatibility audit](model_cards/dili_bionemo_molmim_experiment.md) and
[completed MegaMolBART experiment](model_cards/dili_bionemo_megamolbart_experiment.md).
MegaMolBART covered all 802 structures but did not outperform the RF on the frozen
test cohort (AUROC 0.612 versus 0.760). The RF remains the baseline.
The subsequent [train/validation-only diagnosis](model_cards/dili_bionemo_train_validation_diagnosis.md)
finds overfitting in the fixed logistic head. It does not evaluate new heads on the
test partition or change the deployed model.
An [experimental regularized candidate](model_cards/dili_bionemo_regularized_candidate.md)
is now saved separately, selecting C with training-only grouped CV. It is not a
production replacement and has no new test-set evaluation.

Model commands from the repository root:

```sh
toxicity/.venv/bin/python -m pip install -r toxicity/requirements-model.lock
toxicity/.venv/bin/python -m toxicity.src.baseline train
toxicity/.venv/bin/python -m toxicity.src.baseline evaluate
toxicity/.venv/bin/python -m toxicity.src.baseline predict --input demo/examples/dili_request.json --output artifacts/runs/dili_predictions.json
```

Frozen-split audit and completed MegaMolBART experiment (offline with cached output):

```sh
toxicity/.venv/bin/python -m toxicity.src.bionemo_experiment audit
toxicity/.venv/bin/python -m toxicity.src.bionemo_experiment import-megamolbart \
  --raw artifacts/embeddings/megamolbart_output.json \
  --cache artifacts/embeddings/megamolbart_dilirank2.json
toxicity/.venv/bin/python -m toxicity.src.bionemo_experiment evaluate \
  --cache artifacts/embeddings/megamolbart_dilirank2.json \
  --output artifacts/runs/bionemo_megamolbart_logistic_test.json
```

The optional live/GPU worker and reproducible commands are documented in the
MegaMolBART card. Keep NGC credentials outside the repository; the GPU worker needs
none after downloading the checkpoint. Generated caches and detailed experiment
reports remain under ignored `artifacts/`. MolMIM's adapter is retained, but its
128-token limit prevents this full-cohort comparison; do not drop long compounds.

The model consumes SMILES only. It does not use uploaded notes, dose or exposure fields.
Training artifacts are ignored locally; reports, split manifests and public demo
requests/results are shareable. No live external inference service is needed.

## Data setup and execution

Use Python 3.12. The ingestion environment was tested on macOS arm64 with Python 3.12.14 and RDKit 2025.09.6. Run from the repository root:

```sh
python3.12 -m venv toxicity/.venv
toxicity/.venv/bin/python -m pip install -r toxicity/requirements-data.lock
toxicity/.venv/bin/python toxicity/src/ingest_dilirank.py --stage all
```

`requirements-data.txt` records direct dependencies; `requirements-data.lock` pins the full environment. On this workstation, the available Python 3.12 executable is `/Users/scho/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`.

Acquisition needs network access to FDA and PubChem, without credentials. It uses at most two requests/second across four workers, finite retries, and atomic per-request caching. Re-running resumes from successful cached lookups; transient failures are retried. A PubChem 404 is cached as a genuine name-resolution miss. The first complete run may take 15–25 minutes depending on service latency.

The stages can also run independently:

```sh
toxicity/.venv/bin/python toxicity/src/ingest_dilirank.py --stage fetch
toxicity/.venv/bin/python toxicity/src/ingest_dilirank.py --stage curate
toxicity/.venv/bin/python -m pytest toxicity/tests -q
```

`curate` is strictly offline. Missing cached responses remain visibly unresolved, so partial acquisition can be inspected without inventing matches. Run `fetch` again before considering such a dataset complete. `--root /path/to/root` supports an alternate artifact root; ordinary execution defaults to this repository, regardless of the current directory.

## Outputs

| File | Content |
| --- | --- |
| `data/raw/dilirank_2.0.xlsx` | Original FDA workbook, including both versions; extraction uses **version 2** only |
| `data/cache/pubchem/` | JSON responses, query URLs, UTC retrieval times and HTTP status |
| `data/processed/dilirank2_enriched.csv` | All 1,336 FDA entries, original columns, labels, structure candidates, selected structures, provenance and eligibility |
| `data/processed/dilirank2_model_ready.csv` | One row per eligible standardised structure, with all source IDs retained |
| `data/processed/dilirank2_review.csv` | Unmatched, uncertain, unsupported and conflicting records; intentional label-only Ambiguous exclusions are omitted |
| `data/manifests/dilirank2_source.json` | FDA checksum, source schema/counts and access notes |
| `data/manifests/dilirank2_acquisition_report.json` | Coverage, exclusions, duplicate groups, class counts and CSV checksums |

CSV text is UTF-8; null labels/structures are blank. Array-valued cells such as `source_compound_ids` and `candidate_structures` are JSON. Raw data, caches and CSVs are ignored by Git. Manifests and aggregate reports are tracked. Source datasets and PubChem contributions retain their own rights; the repository licence does not relicense them. The FDA page asks downloaders to notify its support address; the pipeline does not send email.

## Identity and standardisation policy

Policy `dilirank_parent_v1`:

- Preserve original FDA names, categories and row numbers. Query cleanup only normalises Unicode compatibility characters and whitespace. Labels map Most/Less to 1, No to 0, and Ambiguous to null; severity and label-section annotations are never model features.
- Retrieve all PubChem candidates returned by complete-name lookup. Accept only one candidate with an exact normalised synonym. Preserve punctuation, stereo prefixes and salt names; missing synonym responses block acceptance. Check named sodium/potassium/calcium/magnesium/lithium and hydrochloride/hydrobromide forms for corresponding elements, and require disconnected halide salts. Organic names such as fumarate/citrate can describe covalent structures, so names alone do not establish that a counterion is missing. These are automated database matches, not a claim of manual chemical verification.
- Retain source SMILES, CID, source InChIKey, formula, synonyms and URLs separately from the standardised parent. Ambiguous candidates remain available in `candidate_structures` and the response cache.
- Parse and sanitise with RDKit, checking the retrieved SMILES against PubChem's source InChIKey. Remove only disconnected fragments in the explicit counterion/solvent list in the ingestion module. Identical repeated parents in stoichiometric salts collapse to one parent; distinct remaining components require review. Never choose the largest component blindly. Covalent esters and other modifications remain intact.
- Normalise functional groups and neutralise charges where possible. Preserve stereochemistry and isotopes. Do not enumerate or canonicalise tautomers. Permanently charged compounds may remain charged.
- The initial subset requires carbon and allows H/B/C/N/O/F/Si/P/S/Se/Cl/Br/I in the retained molecule, at most 100 heavy atoms and molecular weight at most 1,500 Da. Structures with at least 10 peptide-backbone matches are excluded. These are conservative MVP eligibility rules, not a universal definition of a small molecule. Unsupported entries remain in the master and review tables.
- Deduplicate by canonical isomeric parent SMILES. Preserve every source ID and original category. A positive/negative conflict excludes the whole group. An Ambiguous entry does not override an otherwise unambiguous label; its membership is retained.
- `structure_key` is the standardised parent InChIKey; `structure_id` hashes the policy version plus canonical isomeric SMILES. `connectivity_group` is an additional grouping hint for later split design. It does not establish that stereoisomers share a label. These are dataset identities; Team A's candidate IDs and shared atom mapping remain a later integration handoff.

The model-ready file contains `compound_id`, name, standardised SMILES, structure identities, original category, binary label, label/structure sources, CID, policy version, and all contributing source IDs/categories. Counts are calculated **after** matching, filtering and deduplication; 982 is only the source's non-ambiguous count.

Manual resolution must record the original LTKBID/name, a specific source identifier or structure, supporting URL, rationale and reviewer before changing eligibility. Do not edit generated CSVs: incorporate reviewed changes into the reproducible curation pipeline. Do not assume unresolved entries are negative.

Before training, reserve demonstration cases, resolve any remaining label conflicts intended for inclusion, and freeze compound/scaffold grouping and splits. This data task deliberately does not train or inspect a test-set result.

## External evaluation source audit

The [external DILI source audit](model_cards/dili_external_validation_audit.md)
checks FDA DILIst, TDC DILI and DILImap against the frozen cohort and available
full-source structures. None is approved as an independent test set. It includes
checksum-pinned offline commands and tests; no predictions or training occur.
Raw sources and record-level results remain ignored under `artifacts/external_audit/`.
