# Combined experience — Team A

This workspace contains Team A's offline integration path. It validates both v2 response envelopes, checks candidate and structure identity, and joins discovery and toxicity records without requiring live services or a GPU.

The researcher-facing Streamlit dashboard runs from the root `streamlit_app.py`.
Install `requirements.txt` from the repository root and run
`python3 -m streamlit run streamlit_app.py --server.address 127.0.0.1`.
See [the demo runbook](../docs/runbooks/streamlit-demo.md) for setup, imports,
presenter notes and verification. UI dependencies are isolated in the `demo` extra
and the tested `requirements-demo.lock`; the original CLI remains lightweight.

## Local setup

From the repository root:

```bash
python3 -m pip install -e app
```

## Combine the interface fixtures

```bash
toxoracle-combine combine \
  --request contracts/examples/request.valid.json \
  --discovery contracts/examples/discovery.not-run.json \
  --toxicity contracts/examples/toxicity.not-run.json \
  --config configs/triage-v1.json \
  --output artifacts/runs/combined.json \
  --html-output artifacts/runs/combined.html
```

The output is an identity-preserving joined record with comparison and priority results for each candidate. Numeric disagreement is emitted only for compatible assessed calibrated probabilities for the same endpoint and context. Other eligible pairs receive same-endpoint or cross-endpoint call disagreement; incomplete inputs receive an explicit unavailable reason.

The triage policy is currently marked provisional. Its applicability threshold is intentionally `null` until Team B and the biologist approve a method-specific value. With no approved threshold, the policy requests more safety evidence rather than treating a toxicity call as reliably supported. The optional HTML output is a self-contained offline report with a candidate summary, assessment details, comparison eligibility, limitations, structural evidence and recommended experiments. The example inputs are labelled `not_run` and contain no scientific results.

## Tests

```bash
PYTHONPATH=app/src python3 -m unittest discover -s app/tests -p 'test_*.py'
python3 -m unittest discover -s tests/integration -p 'test_*.py'
PYTHONPATH=app/src:. python3 -m unittest discover -s demo/tests -p 'test_*.py'
```
