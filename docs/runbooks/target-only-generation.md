# Advanced ABL1 generation and screening

This branch adds `toxoracle-design`; the frozen `toxoracle-screen` MVP is unchanged.
The implementation plan is `docs/decisions/target-only-generation-plan.md`.
Use the pinned scientific environment from `team-b-local-mvp.md`. No new model is
trained. The wrapper uses `toxicity/.venv/bin/python`, or `TOXORACLE_PYTHON`; the
DILI subprocess uses `--model-python`. Both need the existing locked scientific
packages. The restricted single-cut SAFE encoder uses RDKit and verifies exact
seed reconstruction; no general SAFE encoder or extra model dependency is needed.

## Entry modes

Target-only example (`demo/examples/abl1_design_request.json`):

```json
{
  "schema_version": "1.0",
  "request_id": "my_abl1_design",
  "mode": "generate_screen",
  "target": "ABL1",
  "input_provenance": "public",
  "count": 20
}
```

For supplied candidates use `mode: "screen"` and `compounds` with `compound_id`
and `smiles`, or complete v2 identities. See
`demo/examples/abl1_supplied_design_request.json`. Do not include `count` or `seeds`
in screen mode. Supplied panels are limited to 20 entries. Invalid and duplicate
inputs stay visible in the ledger and make the result partial.

For analogue generation, add `seeds` (one to five similarly formatted structures)
to `generate_screen`. The seeded strategy chooses a deterministic single BRICS
cut: retain 8–30 heavy atoms, remove at least three, prefer retained size nearest
20, then break ties by serialized fragment and atom indices. Unsupported seeds
fail before external submission. The explicit target-only default uses imatinib's
amide C–N cut specified in `discovery/configs/generation/abl1-imatinib.json`.
It retains the aminopyrimidine/pyridyl-containing fragment and records its attachment.
All template encodings must reconstruct the original seed exactly.

Only the prepared human ABL1 domain is supported. A named mutant, other species,
or another target requires new preparation rather than silent substitution.
Sensitive inputs must pass local filtering, review and approval before they reach
Rosalind or NVIDIA. `input_provenance` records the handoff declaration; it does not
perform scanning or grant permission to disclose proprietary structures.

## Commands

Configure `NVIDIA_API_KEY`, `NGC_API_KEY` or `NVIDIA_BIONEMO_API_KEY` in the execution
environment. Never write credentials to requests or the repository.

```bash
./scripts/toxoracle-design preflight \
  --request demo/examples/abl1_design_request.json \
  --output-dir artifacts/runs/my-abl1-design \
  --cache-dir artifacts/cache

./scripts/toxoracle-design run \
  --request demo/examples/abl1_design_request.json \
  --output-dir artifacts/runs/my-abl1-design \
  --cache-dir artifacts/cache
```

A new run requires a new output directory. Cache use is opt-in, separated into
`genmol/` and `boltz2/`. Omit `--cache-dir` for a fresh live experiment. Each cached
batch retains its own generation index and exact template/settings; the same
payload at another index is a distinct draw. A complete cache needs no key;
missing entries require credentials. Preflight does not promise cache completeness.

Use the same command with `--resume` to verify/reuse saved stages. Inputs, model,
implementation and configuration must match; every saved artifact is checked.
Completed/partial runs are reported without making new calls. A pending call with
unknown outcome, uncheckpointed output or stale `.run.lock` stops recovery for
manual inspection. Do not remove these safeguards to automatically resubmit an
expensive request. Preserve the interrupted run and make any new attempt explicit.

Exit 0: complete. Exit 2: partial scientific result. Exit 1: input/setup/integrity
error. Provider failures are not automatically retried. Reference failure prevents
both generation and panel scoring. Missing candidate binding leaves it unranked;
DILI failure leaves safety assessment incomplete.

## Frozen protocol v1

- Default 20 unique acceptable candidates (request `count` can be 1–20).
- At most five requests of 20 proposals each, 100 requested slots total. Generation
  calls replenish insufficient acceptable structures without feedback optimization.
- GenMol: temperature/noise `"1.0"`, step size 1, QED output score, unique false;
  masked fragment range 15–25. QED never ranks the discovery shortlist.
- Reject invalid/multicomponent/unsupported/radical structures. Accept 8–70 heavy
  atoms for candidate preparation. Preserve unspecified stereochemistry warnings;
  never invent stereoisomers. Standardization uses the existing DILI CLI.
- Enforce the retained fragment and an external bond at the recorded attachment.
  Remove exact seed and frozen-panel matches from generated candidates, with ledger
  entries. Deduplicate standardized identities. Novelty claims are limited to that
  explicitly named comparison, not a global database search.
- Choose the lowest structure ID first; iteratively maximize minimum Morgan
  radius-2, 2048-bit, chiral Tanimoto distance to selected structures. Break ties by
  structure ID then compound ID. Generated IDs derive from structure identity.
- Score at most 20 candidates plus the separate reference with frozen Boltz-2
  settings. The top two by mean binder likelihood form the provisional shortlist.
  Supplied imatinib can itself be a candidate; in generated mode the reference is
  never eligible. Save discovery before DILI and do not replace held candidates.

## Artifacts and interpretation

`workflow.json` contains state, checksums, timestamps, call attempts and failures.
`resolved.json` freezes protocol, target, seed and model/source hashes.
`generation.json` records templates, batches, proposal ledger, selected identities,
validity counts and diversity/seed similarity. `input-ledger.json` records supplied
input decisions. The raw responses and prepared structures remain available.
`request.json`, `discovery.json`, `toxicity.json` and `combined.json` use the existing
v2/v3 contracts. The outer `design-report.json`/`.html` includes generation and
failure context; use it even when no candidate survives. `summary.txt` is the
text handoff to Rosalind. Outputs and generated datasets are ignored by Git.

Generated structures have no measured outcome labels. Their DILI predictions are
not an unseen-compound evaluation. Show overlap and similarity, without a validated
applicability cutoff or invented confidence interval. Synthesis feasibility is
unassessed. DILI flags drug-level liver concern, not dose-specific safe exposure.

## Verification

```bash
PATH="$PWD/toxicity/.venv/bin:$PATH" ./scripts/check.sh
```

New ordinary tests use synthetic vendor responses; RDKit-dependent tests are
skipped in the lightweight CI environment and run in the scientific environment.
Live validation is separate and must record all attempts, including rejected
outputs. Cached replay must reproduce the selected structures and scientific
results, while labelling replay as cached. Visually inspect the HTML report.

Use `discovery/prompts/rosalind_design_workflow.md` in desktop Rosalind. Ask once to
screen a supplied panel and once to generate candidates for ABL1. Inspect the saved
reports and verify that the explanation preserves model limitations and unchanged
or changed follow-up honestly. Actual desktop invocation remains a distinct gate.

## Verified results, 20 September 2026 (London)

The offline suite passed 109 tests in the scientific environment. The frozen MVP
command, target, panel, schemas and model artifact were not changed.

- `artifacts/runs/abl1-design-live-v1/`: complete. Two live GenMol batches returned
  40 proposals. All parsed as supported structures; four failed retained-attachment
  checks and seven were duplicates. Of 29 acceptable unique structures, the fixed
  diversity rule selected 20. All 20 received live Boltz-2 predictions; the separate
  reference reused its verified cache. Local DILI inference succeeded for all 20.
  Total runtime was approximately 548 seconds.
- All 20 DILI calls were positive. The top-two discovery candidates were held for
  liver validation; no replacements were made. All 20 were excluded from model
  fitting, but their outcomes are not measured and this is not an evaluation cohort.
- `artifacts/runs/abl1-design-cache-verification-v1/`: complete, without credentials.
  Both generation batches and all 21 discovery records were cached; local DILI was
  rerun. Candidate identities, selection, ranks and follow-up decisions matched
  exactly. Numeric DILI outputs matched within absolute tolerance `1e-12` (one
  probability differed by approximately `2e-16`). Runtime was about 155 seconds.
  All saved artifact checksums passed, and `--resume` returned the completed result
  without new calls. This replay uses the final report/provenance implementation.
- `artifacts/runs/abl1-design-supplied-v1/`: complete for the original four public
  candidates, using cached discovery and fresh local DILI inference. Dasatinib and
  nilotinib remained the discovery shortlist and were held for liver validation.

Preliminary template smoke attempts are preserved separately. A high-number SAFE
closure returned detached fragments; every output was rejected before screening.
The smallest-free-single-digit closure corrected the encoding and was fixed before
the full experiment. These engineering checks did not use DILI feedback.

Machine-readable evidence: `evaluation/reports/generation_workflow_v1.json`.
No credential was persisted in source or run artifacts. Hosted model versions were
unreported. These results verify software execution, not candidate efficacy or safety.

The user subsequently opened the HTML report and confirmed the displayed
`not_shortlisted` and `hold_for_liver_validation` categories. Full layout checks
and invocation of both modes from desktop Rosalind remain unverified. Automated
visual inspection was blocked by browser URL policy; computer-use policy prohibited
access to the ChatGPT/Codex desktop app. No workaround was attempted.
