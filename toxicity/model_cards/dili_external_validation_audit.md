# External DILI evaluation source audit

Audit date: 2026-09-19. **No external evaluation cohort approved or scored.**

## Decision

None of the three investigated sources can be used unchanged as an independent
test set. The most practical next curation target is a **65-row TDC remainder**
(33 positive / 32 negative), not a ready-to-use benchmark. Its identity, original
label evidence, endpoint compatibility and licensing require review before a
new evaluation protocol is approved. This audit does not establish independence
or justify a BioNeMo improvement claim.

The existing 802-compound cohort, scaffold/connectivity split, RF, embedding cache,
candidate, validation threshold, original test reports and v2 interface were not
changed. No fitting, calibration, feature selection or model predictions occurred.
The spreadsheet audit workflow preserved raw source labels and files; unknowns
remain unknown rather than being converted into negatives.

## Sources and observed overlap

Counts below are computed from the pinned downloads, not borrowed benchmark scores.
Overlap columns are overlapping flags and must **not** be added together.

| Source | Source rows | Standardized structures | Exact parent match to frozen 802* | Connectivity match | Nonempty scaffold match | No detected frozen structure overlap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FDA DILIst | 1,279 | Not supplied | Not assessable | Not assessable | Not assessable | Not assessable |
| TDC DILI | 475 | 459 | 187 | 290 | 338 | 96 |
| DILImap validation metadata | 51 compounds | 40 | 37 | 39 | 37 | 1 |

\* Union of canonical isomeric SMILES and full standard InChIKey matches. Canonical
SMILES alone matched 185 TDC and 36 DILImap records. Standard InChI can equate some
representations that canonical SMILES does not; neither test proves absence of all
tautomer, mixture, metabolite or identity-related overlap.

### FDA DILIst

The [FDA source page](https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-severity-and-toxicity-dilist-dataset)
states that DILIst augments DILIrank with four literature datasets. It is therefore
not an independent label source by default. The downloaded workbook has 768 positive
and 511 negative labels, names and administration routes, but no structures.

Evidence range: original `dilist.xlsx`, sheet `DILIst`, header A1:D1, records
A2:D1280. Conservative normalized name/PubChem-synonym matching flagged 555 rows
against the complete DILIrank2 source, including 390 against model-ready identities.
The remaining names are **unresolved**, not certified novel compounds. The audit
does not assign our stored structures to those external names automatically.
JSON structural-overlap counts are zero because no source structures were assessed,
not because the sources are chemically disjoint.

### TDC DILI

[TDC's task documentation](https://tdcommons.ai/single_pred_tasks/tox/)
describes a 475-drug binary DILI endpoint and cites Xu et al. (2015). The download
identified by the [official TDC metadata](https://github.com/mims-harvard/TDC/blob/main/tdc/metadata.py)
is Harvard Dataverse datafile 4259585. Its labels are 236 positive / 239 negative;
no compound-name column is supplied. Drug_ID values are retained without assuming
that they are verified PubChem identifiers.

The unchanged parent policy rejects 16 rows: 11 unresolved multicomponent
structures, two inorganic structures, one outside size scope, one without a
supported organic parent and one peptide outside scope. Among 459 accepted rows,
no within-source canonical-parent or connectivity duplicates were found.

Twenty-five exactly matched rows disagree with the frozen DILIrank2 binary labels.
These disagreements are recorded, not relabeled to favor either source. They
demonstrate why label harmonization cannot be assumed.

Of 96 rows with no detected structure/scaffold overlap against all 802 model-ready
compounds, **65 remain** after also screening against the available standardized
structures in the complete DILIrank2 source: 33 positive / 32 negative. That source
contains 1,336 rows, of which 1,104 have canonical structures; absent or unresolved
source structures cannot be ruled out. The TDC file has no names, so the additional
name screen is unavailable. The 65 are a curation queue, not independent test data.

### DILImap

The [DILImap study](https://www.nature.com/articles/s41467-025-65690-3)
and [authors' public data-access code](https://github.com/Cellarity/DILImap/blob/main/dilimap/s3.py)
lead to the public `validation_data_pathways.h5ad` file. Only metadata under `obs`
was read; expression matrices and models were not loaded. Its 210 dose/observation
rows collapse to 51 compounds after checking that labels and structures agree
across replicates: 33 positive, 14 negative and four unknown.

Forty compounds have SMILES; 39 overlap the frozen cohort by connectivity. The
remaining structure-resolved compound, almotriptan, is negative. A single negative
cannot support AUROC or sensitivity estimation. Eleven compounds lack SMILES in
this file: seven have known labels (five positive / two negative), four are unknown.
Those structures could be curated separately, but this is not yet an adequate
independent evaluation cohort. No missing structures or labels were inferred.

The broader `compound_DILI_labels.csv` was inspected for source/schema context but
was not substituted for the validation panel or used to fill its missing metadata.
Its SHA256 is `1a62b46207bc48d538c0f7b9b565b75926b6d3993ef81070f8a51addb4a9ca08`.

## Audit method and limitations

- Validate the existing dataset and frozen split checksums before reading sources.
- Reuse `dilirank_parent_v1` under RDKit 2025.9.6 without relaxing exclusions.
- Compare canonical SMILES, full InChIKey, connectivity block and nonempty Bemis–Murcko
  scaffold against train, validation and test. Empty scaffolds never form one group.
- Repeat available structural screening against all 1,336 source rows, including
  ambiguous/excluded compounds. Names use the existing conservative normalization
  and stored PubChem synonyms; a name hit is a review flag, not proven identity.
- Preserve source labels, row indices, missing values, rejected structures,
  duplicate/conflicting-label groups and per-partition overlap evidence in JSON.
- No prediction-based exclusions, external threshold selection or external calibration.

Training-overlap checks here concern supervised DILI data. MegaMolBART representation
pretraining overlap with ZINC15 remains unknown. Tautomer/metabolite relationships,
unresolved mappings, chemical similarity short of identical scaffolds, label source
dependence and clinical evidence dates remain additional review items. Scaffold
novelty alone does not prove independent labels or generalization.

Licensing/redistribution has **not** been cleared. Raw downloads and record-level
audit results remain ignored under `artifacts/`; no new dataset is committed.
The FDA page asks downloaders to notify its support address; no email was sent.
Review source-specific permissions rather than assuming a code repository's license
also covers every underlying dataset.

## Blockers and smallest credible next experiment

1. Review the 65 TDC candidate identities and original label evidence while blind
   to model predictions. Do not resolve conflicting evidence based on model output.
   If endpoint compatibility or independence cannot be established, obtain a new
   independently curated/temporal cohort instead.
2. Obtain the **original trusted RF artifact** from Team B. The local
   `artifacts/models/dili_baseline.joblib` is absent. Published aggregate RF metrics
   are not enough for a paired external comparison; do not silently retrain it.
3. Explicitly review and freeze a new external manifest, inclusion/unknown-label
   policy, dataset/source hashes, two model artifacts and existing validation-selected
   thresholds before scoring. Decide which already-trained BioNeMo logistic candidate
   is being tested; do not choose among them using external results.
4. Verify both models cover the same finalized cohort and acquire only missing
   real embeddings under the existing cache contract. Include nearest-training Morgan
   similarity and representation-pretraining overlap uncertainty.
5. Run one paired external evaluation: AUROC, AP, sensitivity, specificity, confusion
   matrices, frozen validation thresholds, Brier/reliability for probability outputs,
   and uncertainty intervals that respect compound/scaffold dependence. Do not fit
   a calibrator on external labels. Define uncertainty calculations before scoring.

The original held-out result currently does not support BioNeMo improvement. Even
a new exploratory subset cannot retroactively make the prior development independent.
Outputs describe compound-level DILI labels, not patient incidence or proof of safety.

## Reproduction

Run from the repository root with the existing data/model environment. Public source
downloads are optional network operations, not part of offline tests:

```sh
mkdir -p artifacts/external_audit/sources
curl -fL --retry 2 'https://www.fda.gov/media/160597/download?attachment=' -o artifacts/external_audit/sources/dilist.xlsx
curl -fL --retry 2 'https://dataverse.harvard.edu/api/access/datafile/4259585' -o artifacts/external_audit/sources/tdc_dili.tab
curl -fL --retry 2 'https://dilimap.s3.amazonaws.com/public/data/validation_data_pathways.h5ad' -o artifacts/external_audit/sources/dilimap_validation.h5ad
```

The audit pins source SHA256 values in `external_validation_audit.SOURCES` and refuses
changed downloads. Core offline audit (no HDF5 reader required):

```sh
toxicity/.venv/bin/python -m toxicity.src.external_validation_audit --output artifacts/external_audit/core_reproduction.json
toxicity/.venv/bin/python -m pytest toxicity/tests/test_external_validation_audit.py -q
```

Optional DILImap metadata reader is isolated from the modeling environment. Its
installation needs network access; subsequent audit/tests are offline and CPU-only:

```sh
toxicity/.venv/bin/python -m pip install --no-deps --target artifacts/external_audit/deps h5py==3.15.1
PYTHONPATH=artifacts/external_audit/deps toxicity/.venv/bin/python -m toxicity.src.external_validation_audit --include-dilimap --output artifacts/external_audit/full_reproduction.json
PYTHONPATH=artifacts/external_audit/deps toxicity/.venv/bin/python -m pytest toxicity/tests/test_external_validation_audit.py -q
```

Use a new output path on every run; the command refuses an existing output file.
The completed full audit is `artifacts/external_audit/report_v2.json` (ignored).
The earlier `report.json` is an intermediate frozen-cohort/name-only audit, superseded
by `report_v2.json`'s additional all-source structural screen; it is retained unchanged.
No NVIDIA API key or GPU is needed for this audit. No commit or push was performed.

Verification: nine new audit tests passed with the optional HDF5 reader installed;
the complete toxicity suite passed 56 tests, with five RF-artifact-dependent tests
skipped because the original weights are absent. Both staged and unstaged
`git diff --check` passed. Frozen dataset and split hashes still match their pins.
