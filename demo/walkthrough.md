# ToxOracle demo walkthrough

This walkthrough covers the researcher-facing comparison without assuming live services are available. Final demo cases must contain genuine, shareable outputs. Interface-only fixtures remain under `contracts/examples/` and must not be presented as scientific results.

## Case readiness

Each directory under `demo/examples/` must contain:

```text
manifest.json
request.json
discovery-response.json
toxicity-response.json
```

The manifest must validate against `demo/case.schema.json`, be marked `ready`, identify live versus cached execution, disclose training membership and record tool versions, provenance and limitations. A final case uses `result_class: real`. The runner rejects `interface_fixture` cases unless the explicit dry-run flag is supplied.

Do not select demonstration compounds after looking at model test predictions. Team B freezes the evaluation split and intended cases before fitting or tuning. Shared preprocessing must add atom mappings to the selected canonical structures before either stream runs.

## Preflight

From the repository root:

```bash
python3 -m pip install -e app
PYTHONPATH=app/src python3 -m unittest discover -s app/tests -p 'test_*.py'
python3 -m unittest discover -s tests/integration -p 'test_*.py'
PYTHONPATH=app/src:. python3 -m unittest discover -s demo/tests -p 'test_*.py'
```

Confirm that the selected case contains one discovery result and one toxicity result for every requested candidate, with unchanged candidate, structure and atom-map identifiers.

## Generate a cached report

```bash
PYTHONPATH=app/src python3 demo/run_case.py demo/examples/CASE_ID \
  --config configs/triage-v1.json \
  --output-dir artifacts/runs/CASE_ID
```

The runner writes `combined-report.json`, `combined-report.html` and `run-metadata.json`. The metadata records SHA-256 checksums for every input and generated report.

## Presenter sequence

1. Introduce the candidate list and agreed therapeutic discovery objective.
2. Show the discovery-only evidence and original priority. Name the discovery metric, its units, direction and limitations.
3. Show the conventional toxicity assessment separately from therapeutic docking evidence.
4. Reveal the human DILI assessment, its score meaning, threshold and applicability indicator.
5. Show the comparison mode. Explain why the result is numeric, call-only or unavailable.
6. Compare original and revised priorities for the same candidate IDs.
7. Open one candidate detail view and trace each fragment, interaction or artifact to its source. Do not describe attribution as causation.
8. State which uncertainty the recommended experiment is intended to resolve and which readouts are proposed.
9. Disclose whether the case is held out, included in training or of unknown membership.

## Live-service failure fallback

If a live discovery or toxicity call fails, show the failure as an incomplete assessment; never reuse an old score inside a newly labelled live run. Switch to a pre-generated case directory whose manifest says `execution_mode: cached`, rerun the command above, and disclose that the output is cached.

## Final acceptance check

- Candidate and structure identities match across request and both responses.
- No mock or `not_run` score is presented as a result.
- The comparison mode and nullable outputs follow the eligibility rules.
- Lower predicted concern is not described as safety.
- Every structural claim and artifact has a traceable source.
- Training membership and applicability limitations are visible.
- The cached case regenerates both reports offline.
- Three permitted cached cases and a backup recording are available before the final demonstration.
