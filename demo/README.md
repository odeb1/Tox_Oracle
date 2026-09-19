# Demo delivery

Keep small permitted cached examples in `examples/`, the pitch in `pitch/`, and the reproducible process in `walkthrough.md`. Store videos and large artifacts outside Git with links/checksums. Label cached execution and never mix mocks with actual results.

Launch the interactive presentation with `python3 -m streamlit run streamlit_app.py`
from the repository root after installing `requirements.txt`. It includes the three
real public DILI examples and an independent cached NVIDIA docking example. The
[Streamlit runbook](../docs/runbooks/streamlit-demo.md) documents the presentation
sequence and complete-case imports. UI regression tests live in `streamlit_tests/`.

Each final case has a `manifest.json` conforming to `case.schema.json`. Run a ready case from the repository root with:

```bash
PYTHONPATH=app/src python3 demo/run_case.py demo/examples/CASE_ID \
  --config configs/triage-v1.json \
  --output-dir artifacts/runs/CASE_ID
```

The runner validates the manifest and both v2 response envelopes, enforces shared molecular identity, applies the comparison and triage policies, and writes JSON, HTML and checksum metadata. It rejects interface-only fixtures by default.
