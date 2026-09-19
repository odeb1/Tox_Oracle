# Combined experience — Team A

This workspace contains Team A's offline integration path. It validates both v2 response envelopes, checks candidate and structure identity, and joins discovery and toxicity records without requiring live services or a GPU.

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
  --output artifacts/runs/combined.json
```

The current output is an identity-preserving joined record. Comparison, prioritisation and report rendering are added in later milestones. The example inputs are labelled `not_run` and contain no scientific results.

## Tests

```bash
PYTHONPATH=app/src python3 -m unittest discover -s app/tests -p 'test_*.py'
python3 -m unittest discover -s tests/integration -p 'test_*.py'
```
