# Rosalind: ABL1 screening plus human DILI

This is the current discovery-first implementation. It supersedes the requirement
for a second toxicity assessment in the original Team A runbook. The legacy v2
comparison CLI is retained. The new v3 report does not manufacture a toxicity
disagreement score from binding predictions.

## Frozen experiment

`demo/examples/abl1_experiment.json` freezes four public ATP-site ABL1 inhibitors:
imatinib (reference), dasatinib, nilotinib and bosutinib. Structures come from the
curated repository dataset; the candidate request uses Team B's standardisation.
The target manifest records the 273-residue deposited polymer sequence for human
ABL1, PDB 2HYY chain A, source checksum and inference settings. Boltz-2 receives
sequence and ligand SMILES, not an experimental complex or docking pose. No
custom MSA, pocket constraint or template is supplied in this protocol.

Each compound is run separately through NVIDIA's hosted Boltz-2 NIM with affinity
enabled. Rank successful scored records by the arithmetic mean of all returned
`affinity_probability_binary` values, descending; exact ties use compound ID.
The top two form a provisional discovery shortlist. This is a relative
computational screening rubric, not a calibrated binding or efficacy criterion.
All affinity and confidence arrays are retained, along with the complete raw
response. A missing score leaves a compound unranked. Poses remain explicitly
unmapped to input atom IDs; do not infer atom-level contacts from them.

The panel is retrospective and may overlap DILI fitting/selection data. Report
membership and warnings for every compound. Do not change the panel, thresholds
or selection rule after seeing predictions to obtain an attractive outcome.

## Local setup

Use the scientific environment and model from `team-b-local-mvp.md`. The wrapper
uses `toxicity/.venv/bin/python` by default and adds the local application and
discovery packages to the import path; no package installation is required when
that environment already contains the locked scientific dependencies and
`jsonschema`. `TOXORACLE_PYTHON` can select another integration interpreter;
`--model-python` explicitly selects the scientific subprocess interpreter.

For an installed console command, install both editable packages into the same
environment: `python -m pip install -r app/requirements.lock -e app -e discovery`. Keep the repository
available: this workflow intentionally runs Team B's versioned CLI in a subprocess,
not through imports of its model implementation.

Configure an NVIDIA key in the execution environment outside Git and chat. The
client accepts `NVIDIA_API_KEY`, `NGC_API_KEY`, or `NVIDIA_BIONEMO_API_KEY`, in that
order. Preflight reports presence only; no secrets are written to outputs.
Pass `--cache-dir artifacts/cache/boltz2` to preflight as well as run when replaying:
a complete integrity-checked cache can run without credentials. Network entitlement
is only verified by a live request.

```bash
./scripts/toxoracle-screen preflight \
  --request demo/examples/abl1_request.json \
  --target discovery/configs/targets/abl1.json \
  --output-dir artifacts/runs/abl1-demo

./scripts/toxoracle-screen reference-check \
  --request demo/examples/abl1_request.json \
  --target discovery/configs/targets/abl1.json \
  --output-dir artifacts/runs/abl1-reference \
  --cache-dir artifacts/cache/boltz2

./scripts/toxoracle-screen run \
  --request demo/examples/abl1_request.json \
  --target discovery/configs/targets/abl1.json \
  --output-dir artifacts/runs/abl1-demo \
  --cache-dir artifacts/cache/boltz2
```

Each output directory must be new; earlier runs are never overwritten. Cache use
is explicit. Entries bind endpoint, protocol, target manifest and full compound
identity to a response checksum. Reused outputs are labelled `cached`; the current
hosted model version cannot be inferred from a cache. Omit `--cache-dir` for a
live-only run. Hosted versions absent from responses are recorded as unreported.

`run` always checks the reference first. It runs the remaining panel only when the
reference returns a usable mmCIF complex, binder likelihood and affinity value.
Requests have a 600-second timeout and are not automatically resubmitted. The
discovery snapshot is saved before local DILI inference begins. Per-compound
failures remain in the report. Exit 0 means complete, 2 means failed reference or
partial scientific results, and 1 means a setup/contract error.

Outputs include `request.json`, `target.json`, `run.json`, `discovery.json`,
`toxicity.json`, `combined.json`, `combined.html`, `summary.txt`, and raw Boltz-2
requests/responses plus predicted complexes. The manifest records input/model
checksums, times, Git revision and dirty-tree status. Outputs stay ignored locally.

## Desktop Rosalind integration

Rosalind's reported shell capability is the first integration mechanism; no
custom MCP is required. Open this repository as its working project, permit
writes to the chosen output location and allow NVIDIA network access when asked.
Use `discovery/prompts/rosalind_screening_workflow.md` as the workflow instruction.

Example prompt:

> In `/Users/scho/Tox_Oracle`, follow the Rosalind screening workflow instructions.
> Run the frozen ABL1 panel through BioNeMo Boltz-2 and our local DILI model.
> Show the discovery-only shortlist, how DILI changes follow-up decisions, and
> supporting structures, model limitations and training membership. Use a new
> output directory and report live versus cached execution honestly.

Only public or previously filtered/reviewed/approved inputs may be provided to
this command. It is not a privacy scanner. The standalone gateway remains the
boundary for sensitive inputs; its OFF mode never permits raw export.

Desktop completion requires an actual Rosalind invocation and readable report;
a terminal test alone is not evidence that this final interaction has occurred.

## Follow-up policy

The trained DILI threshold is unchanged. Shortlisted positive calls are held for
human-relevant hepatocyte concentration-response validation; shortlisted negative
calls continue target-binding validation alongside routine liver-safety testing.
Unavailable DILI results leave safety assessment incomplete. Other candidates
retain their discovery rank. A held candidate is not automatically replaced.

The policy stays provisional. Tanimoto similarity is displayed, without inventing
an applicability cutoff or confidence interval. Predictions do not establish safe
human exposure. Suggested experiments contain questions and readouts, not doses.

## Checks

Run `PATH="$PWD/toxicity/.venv/bin:$PATH" ./scripts/check.sh` for offline legacy and
new contract/report/transport checks. These use explicitly synthetic vendor
responses. Live reference and panel commands above are separate acceptance gates.

Sources: [RCSB 2HYY](https://www.rcsb.org/structure/2HYY),
[NVIDIA Boltz-2 inference](https://docs.nvidia.com/nim/bionemo/boltz2/1.8.0/inference.html).

## Verified implementation results, 19 September 2026

The NVIDIA reference call succeeded and the four-compound terminal pipeline
completed. The panel reused the imatinib reference response from the exact-input
cache; the other three predictions were live. Hosted model version was not reported.

| Compound | Discovery rank | Binder likelihood | DILI score | Training membership | Follow-up |
|---|---|---|---|---|---|
| Dasatinib | 1 | 0.9531 | 0.7128 | Included | Hold for liver validation |
| Nilotinib | 2 | 0.8203 | 0.8259 | Included | Hold for liver validation |
| Bosutinib | 3 | 0.8047 | 0.6087 | Excluded from fitting; used for model selection | Not shortlisted |
| Imatinib | 4 | 0.7578 | 0.8694 | Included | Not shortlisted |

All four DILI calls were positive. These are observed outputs of this retrospective
demonstration, not evidence that the ranking is correct or that a compound will
cause harm. Both shortlisted compounds were used in DILI model fitting. Bosutinib
was used for model selection and thresholding; none of the four is an unseen
evaluation case.

Local evidence: `artifacts/runs/abl1-reference-network/` and
`artifacts/runs/abl1-screen-network/`. An additional credential-free replay at
`artifacts/runs/abl1-cache-verification/` used all four verified cache entries and
completed successfully. The model artifact checksum was unchanged.

Desktop Rosalind invocation was confirmed by the user and its saved artifacts at
`artifacts/runs/abl1-rosalind-20260919T183712Z/`: exit 0, manifest complete, all four
Boltz-2 records cached and local DILI inference successful. Automated visual
inspection of the local HTML file was blocked by the browser tool's URL policy;
schema, policy, escaping and output-generation checks passed.
