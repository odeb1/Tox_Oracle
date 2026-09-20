# Training-error and external-cohort follow-up

Branch-only review, 20 September 2026. No model fitted or scored, no label changed,
and no evaluation cohort approved. BUILD_PLAN and READMEs are unchanged.

## Outcome and next decision

The 65 shared training errors are not 65 demonstrated label errors. All 539 frozen
training labels, including these cases, agree with the category-to-binary mapping
in the checksum-pinned enriched FDA snapshot. Most shared errors at the diagnostic
0.5 cutoff are false positives. This does not establish the cause of those errors
or warrant retuning a threshold from the audit.

The external remainder gained one additional identity-overlap flag: Acarbosum
versus acarbose. The 51 records without current flags remain an unapproved
curation queue, not an independent test set. Prioritize identity/endpoint review
and intended-use clearance before spending more time on model search.

## Training review

This audit uses the same 539 nested-OOF training compounds and seven model arms
as `training_error_audit_with_svm_v1.json`. No validation/test outcomes are used
for this analysis. Whole-file checks still validate the frozen source/split.

| Finding | Negative-labelled training compounds | Positive-labelled training compounds |
| --- | ---: | ---: |
| All training compounds | 200 | 339 |
| All seven models wrong at fixed 0.5 | 64 | 1 |
| Shared-error compounds marked New in source | 28 | 0 |
| All training compounds marked New in source | 60 | 29 |
| Shared-error compounds with opposite-labelled nearest outer-fitting neighbour | 42 | 1 |

For negatives, shared errors occur in 28/60 source-New compounds versus 36/140
other compounds. This is descriptive and post-hoc. New denotes the source's
addition status, not a measured approval date, exposure or causal explanation.
Source label sections, severity, categories and comments remain review metadata,
never predictive features. Selection by errors and calibration at 0.5 also limit
interpretation. The median nearest-fitting similarity is 0.2727 both for all
negative compounds and for the shared-negative-error subset; these summaries do
not establish a simple applicability explanation.

Three concrete review cases:

- Acarbose is the only shared false negative. The retained source maps it from
  Most-DILI-concern to 1, consistent with the current FDA table.
- Rifamycin sodium is No-DILI-concern in the retained/current FDA table, while
  its closest outer-fitting neighbour is positive-labelled rifampin, Tanimoto
  0.6931. Chemical similarity alone does not justify copying the neighbour's label.
- Amifampridine's deduplicated structure retains source rows 52 and 53: the free
  compound is No-DILI-concern; phosphate is Ambiguous-DILI-concern. The frozen
  policy retains label 0 from the nonambiguous member and preserves the ambiguous
  provenance. This is a review issue, not a binary-mapping implementation error.

Public spot-checks of acarbose, dichlorphenamide and rifamycin sodium agree with
the retained categories in the [FDA DILIrank2 table](https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-rank-dilirank-20-dataset).
The complete original FDA XLSX was absent locally. Its retrieval returned HTTP
404 after redirect to FDA's access-error page; it was not recovered or bypassed.
Consequently the full 539-row check is against **retained FDA columns in the
pinned enriched snapshot**, not an independent reinspection of that workbook or
clinical adjudication of every label. Each hard case retains its source ID,
recorded workbook row, category, mapping status and structure provenance.

## External review

All 65 original candidates' combined-table labels and underlying evidence rows
were checked against the checksum-verified ACS supplementary XLSX. Text versus
numeric CID cell storage is normalized for equality; structures, annotations and
labels are not rewritten. The prior 13 flagged records remain flagged.

For the former 52-record remainder, a narrowly defined diagnostic strips only
recognized trailing naming-authority tags, such as `[INN-Latin]`, from synonyms.
It does not remove salt, stereochemical, isotope or unknown qualifiers and does
not change the repository's identity policy. This adds one match:

| External record | Retained FDA identity | Evidence |
| --- | --- | --- |
| Acarbosum, CID 441184 | Acarbose, LT01034, CID 9811704, frozen training | External alias Acarbosum matches retained Acarbosum [INN-Latin] |

The current [PubChem Acarbosum record](https://pubchem.ncbi.nlm.nih.gov/compound/441184)
also links its moved annotation to acarbose CID 9811704. The public JSON response
is cached with URL, timestamp and SHA256 under
`artifacts/external_audit/followup_sources_v2/pubchem_441184.json`.
This strengthens an identity/provenance warning; it does **not** prove that every
stored stereochemical/ring form is interchangeable. No SMILES was substituted.

Among the 51 remaining unapproved records:

- 23 positive and 28 negative labels.
- 30 exact standardized full-InChIKey agreements with cached PubChem structures;
  21 connectivity-only agreements with stereochemical differences.
- Three still lack cached PubChem titles: CIDs 9052, 9346 and 6323490. Missing names
  remain unresolved rather than being inferred from structures or model outputs.
- 21 have evidence only in NCTR S1.1/S1.2 tables (18 no-concern, three Most-concern).
  The other 30 use HH/NE and/or Positive/Negative annotations in S1.3/S1.4.
  Numerical label agreement across sources is not endpoint harmonization or
  independent clinical replication. Our frozen positive class also includes Less
  concern. None of these 51 has been clinically adjudicated in this review.

These are overlapping review categories, not automatic exclusion criteria.
All 65 records are preserved in the new report, including all flags and original
annotations; no approved manifest or filtered modeling dataset was created.

## Reuse terms and remaining decisions

The [publisher-hosted supplementary dataset](https://acs.figshare.com/articles/dataset/Deep_Learning_for_Drug_Induced_Liver_Injury/2054931)
lists CC BY-NC 4.0. [TDC's DILI documentation](https://tdcommons.ai/single_pred_tasks/tox/#dili-drug-induced-liver-injury)
still presents unspecified-license wording adjacent to a CC BY 4.0 link. A fresh
public Dataverse dataset-metadata request returned HTTP 403. No access control
was bypassed, and no contacts were emailed. These findings are not legal clearance.

Before external scoring:

1. Confirm intended noncommercial research/demo versus possible commercial use
   and review source-specific reuse terms; do not assume the repository license
   covers upstream data.
2. Have a qualified reviewer adjudicate identities and a compatible DILI endpoint
   while blind to external predictions. Preserve unknowns and disagreements.
   If independent compounds/evidence cannot be established, seek a new curated or
   temporal source; the current queue is not a substitute for one.
3. Approve a frozen external manifest and one locked comparator pair, thresholds
   and uncertainty procedure before any scoring. No selection from external labels
   or repeated original-test evaluation.

RF remains the reference. This review neither establishes that RF is globally
optimal nor supports a new ensemble or BioNeMo improvement claim. Compound-level
DILI concern is not patient incidence or proof of safety.

## Reproduction and checks

New source: `toxicity/src/curation_followup.py`; offline tests:
`toxicity/tests/test_curation_followup.py`. No existing source module was edited.
The spreadsheet-audit workflow kept raw sources read-only and source facts separate
from interpretation. Generated record-level evidence stays ignored under artifacts.

```bash
# Existing pinned audit/source caches required; no network, credentials or GPU.
# Choose a fresh output path; the command refuses to overwrite prior evidence.
toxicity/.venv/bin/python -m toxicity.src.curation_followup --output artifacts/runs/curation_followup_reproduction_02.json
toxicity/.venv/bin/python -m pytest toxicity/tests/test_curation_followup.py -q
PYTHONPATH=artifacts/experimental_deps/xgboost-3.0.5:. toxicity/.venv/bin/python -m pytest toxicity/tests artifacts/external_audit/test_review65.py -q
```

The completed report is `artifacts/runs/curation_followup_v1.json`, SHA256
`05341e7836b44c6abe27713be93bdcba4201a165526c04235d4b53ca01332b1c`.
A separate offline reproduction produced byte-identical JSON. Input/source hashes
were rechecked; frozen inputs, all labels, models, thresholds and contracts remain
unchanged. No commit, push, model promotion or external predictions.

Verification: 13 new offline tests passed. Combined toxicity and prior external
evidence tests: 141 passed, six skipped (five require original production RF
weights, one optional h5py). No live/GPU tests were run.
