# Contract examples

Small synthetic request/response fixtures only. Include successful, invalid, unsupported and failed cases. Mark illustrative predictions as not_run; never invent model results.

- `request.valid.json`, `discovery.not-run.json` and `toxicity.not-run.json` exercise the shared interface without scientific scores.
- `request.failure-cases.json` and `discovery.failure-cases.json` cover invalid input, unsupported chemistry and external-tool failure. Every failure keeps risk and call outputs unavailable and includes a machine-readable error.
