# Team A integration runbook

## Purpose and current boundary

This runbook covers the offline Team A integration path: validate shared v2 requests and responses, preserve molecular identity, compute only eligible comparisons, apply the versioned triage policy, and render JSON and HTML reports.

The NVIDIA DiffDock adapter currently emits `stream: discovery_evidence`. It is supplementary discovery evidence, not the final `stream: discovery` conventional-toxicity assessment. Do not pass docking confidence into the toxicity comparison. The final discovery envelope requires a separately selected conventional liver-toxicity comparator.

## Requirements

- Python 3.11 or newer for the integration and demo tooling.
- No GPU, external service, network access or credentials for offline checks.
- `NVIDIA_API_KEY` only for the separately documented live DiffDock command. Never place the value in Git, fixtures, reports or shell history.

## Setup

From the repository root:

```bash
python3 -m pip install -e app
```

The editable install provides the `toxoracle-combine` command and installs the JSON Schema dependency. The discovery adapter's offline transport tests use the standard library. Its optional RDKit structure-mapping path and live NVIDIA call are outside the default CI environment.

## Run every offline check

```bash
./scripts/check.sh
```

This command compiles the Python sources and runs:

- Application validation, comparison, prioritisation and report tests.
- Shared contract and fixture tests.
- Demo manifest, path-safety and reproducibility tests.
- Discovery/DiffDock transport and artifact tests.

The same command runs in `.github/workflows/ci.yml`. CI intentionally does not make external API calls or claim that GPU execution, RDKit pose mapping, a conventional toxicity comparator or the human DILI model has run.

## Generate an interface-only report

The committed `not_run` fixtures exercise the integration shape without scientific results:

```bash
toxoracle-combine combine \
  --request contracts/examples/request.valid.json \
  --discovery contracts/examples/discovery.not-run.json \
  --toxicity contracts/examples/toxicity.not-run.json \
  --config configs/triage-v1.json \
  --output artifacts/runs/interface-check/combined.json \
  --html-output artifacts/runs/interface-check/combined.html
```

Expected behavior:

- Candidate and structure identity is preserved.
- Comparison is `unavailable` with an explicit reason.
- Revised priority is `assessment_incomplete`.
- No fixture is presented as a scientific prediction.

Generated outputs under `artifacts/` are ignored by Git.

## Validate real handoffs

Before generating a real report, obtain the following files using the same shared request:

1. A final `stream: discovery` v2 response containing the selected conventional toxicity assessment and supplementary discovery evidence.
2. A final `stream: toxicity` v2 response containing Team B's DILI result, applicability information, provenance and training-membership disclosure.

Then replace only the two response paths in the command above. Do not edit identifiers to force a join. The validator must reject missing, duplicate, extra or structurally mismatched records.

The triage policy remains `provisional` while `credible_minimum` is `null`. An `approved` policy must have a method-specific threshold agreed with Team B and the biologist.

## Discovery-evidence wrapping checklist

First normalize a saved Person 2 result:

```bash
toxoracle-combine normalize-discovery \
  --request path/to/candidates.v2.json \
  --evidence artifacts/runs/diffdock/run.json \
  --output artifacts/runs/diffdock/normalized-evidence.json
```

This step preserves request order and molecular identity, normalizes supplementary metrics, graph/pose artifacts, protein-contact fields and error codes, and excludes artifacts whose origin or atom-mapping reference is not declared. Its output is labelled `normalized_discovery_evidence`, deliberately omits `assessment`, and cannot be passed to the final join as a discovery response.

When the conventional comparator is selected, the adapter that wraps DiffDock evidence into the shared discovery response must:

- Change the final stream to `discovery`; retain raw `discovery_evidence` as supplementary provenance.
- Populate the common assessment from the conventional toxicity comparator, never from docking confidence.
- Preserve `compound_id`, `structure_id`, canonical SMILES, atom-mapped SMILES and standardisation version.
- Add the agreed `discovery_priority` supplementary metric with its rule and source.
- Normalize errors to `code` and `message`.
- Normalize protein contacts to the shared interaction field names.
- Ensure every structure artifact has `origin` and `atom_mapping_ref`.
- Return one record for every submitted candidate, including failures.

## Failure recovery

| Failure | Required response |
|---|---|
| Schema or identity validation fails | Correct the producing adapter; do not hand-edit scientific outputs to bypass validation. |
| Discovery or toxicity service fails | Keep the failed status and error; comparison and priority remain incomplete. |
| Live service is unavailable during the demo | Switch to a genuine cached case whose manifest says `execution_mode: cached`. |
| Only interface fixtures are available | Demonstrate software integration only and state that scientific inference has not run. |
| Applicability threshold is not approved | Keep the policy provisional and recommend gathering safety evidence. |
| Candidate is outside supported space | Preserve the result as unsupported or unreliable; never convert it to low risk. |

## Real demo cases

Use `demo/run_case.py` only after both real response files exist and the case manifest records provenance, versions and training membership. Follow `demo/walkthrough.md`. Final acceptance requires three permitted cached cases; interface fixtures are rejected by the runner unless the explicit dry-run option is used.

## Current external dependencies

- Person 2 and the biologist: target, prepared PDB, reference ligand, discovery criterion and conventional toxicity comparator.
- Team B: frozen split, trained or verified pretrained model, threshold, applicability method and v2 response.
- Both teams: shared atom mappings, comparison mode and reviewed triage/claim language.
