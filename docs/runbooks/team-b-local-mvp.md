# Team B local MVP

The baseline and privacy gateway run locally. The gateway does not connect to Rosalind,
OpenAI APIs or NVIDIA endpoints. Its approved files are the handoff to Team A.

## Setup

Python 3.12 is required. From the repository root:

```sh
python3.12 -m venv toxicity/.venv
toxicity/.venv/bin/python -m pip install -r privacy/requirements.lock
toxicity/.venv/bin/python -m privacy.setup_model
```

The existing workstation Python 3.12 is also available at
`/Users/scho/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`.
The lock records the tested macOS arm64 environment. Model-only users can install
`toxicity/requirements-model.lock` instead. Privacy inference uses CPU; no GPU or API key is required.
Setup downloads approximately 3 GB of model weights plus dependencies. Downloads happen
before sensitive input is accepted, under ignored `artifacts/privacy/`. Keep these assets
locally for an offline demo. Never substitute an unverified model repository.

## Train and evaluate

```sh
toxicity/.venv/bin/python -m toxicity.src.baseline train
toxicity/.venv/bin/python -m toxicity.src.baseline evaluate
toxicity/.venv/bin/python -m toxicity.src.baseline predict --input demo/examples/dili_request.json --output artifacts/runs/dili_predictions.json
```

Training verifies the source manifest checksum, fixes scaffold/connectivity groups and
partitions, selects among eight random forests using validation average precision,
assesses sigmoid calibration, and freezes a validation-selected threshold. The test
partition is used only by `evaluate`. Do not adjust the configuration after inspecting
test results and then describe the same test set as untouched.

`prepare --input input.json --output request.json` accepts an envelope with `request_id`
and `compounds`, each containing `compound_id` and `smiles` (or `canonical_smiles`). It
creates shared molecular and atom identities. Inference validates supplied identities
and preserves valid atom maps. Existing Team A identities must follow the same documented
standardisation policy; mismatches require coordination, not silent rewriting.

Generated model artifacts are trusted local Python/joblib files. Do not load models
uploaded by users or obtained from untrusted sources. Outputs are drug-level DILI concern,
not patient incidence, injury severity, exposure response, efficacy or a safe dose.

## Privacy demo

```sh
toxicity/.venv/bin/python -m privacy.server
```

Open **http://127.0.0.1:8765** (use this exact host/port).

1. Load the synthetic example or paste text/CSV/JSON. Filenames are not sent to the service.
2. Click **Scan locally**. The initial checkpoint load is slower than subsequent requests.
3. Review the entire sanitized payload and findings. Edit the original to add masks or
   correct input, then rescan. A flagged scientific field can be retained only after
   chemical/identity validation and a separate checkbox acknowledgement that it contains
   no personal identifier. Unvalidated flags block release; free-text PII stays redacted.
4. Click **Approve reviewed payload**. Any edit or toggle change invalidates approval.
5. Download the sanitized content/audit, generate the v2 molecular request, or run local DILI inference.
6. Toggle the filter OFF to compare the unfiltered local preview. Export remains disabled.
7. Clear the session after the demo. Inactive sessions expire after 30 minutes.

Use synthetic inputs when presenting. The example molecule is a software-flow fixture,
not a nominated therapeutic candidate. `demo/examples/dili_request.json` supplies three
real held-out public compounds. Their outcome was not used to choose attractive examples:
selection is the first negative, first positive, and next remaining test record by the
fixed dataset ordering, after evaluation. They are retrospective illustrations.

Inputs are limited to English UTF-8 text, CSV and JSON: 1 MB, at most 1,000 records per
array, 6,000 characters per string value, 128 characters per key, and nesting depth 16.
PDF/Word/images are unsupported. No OCR is performed. Numeric assay fields remain
scientific context; the toxicity request excludes all non-molecular features.

The loopback API requires the per-launch token embedded in the locally served page,
an exact Host and Origin, and a per-tab session ID. Routes are `/api/session`, `/api/scan`,
`/api/invalidate`, `/api/approve`, `/api/export`, `/api/predict`, and `/api/reset`.
Approval/export/predict require the current `scan_id`; approval also requires the exact
set of acknowledged `retain_fields` IDs when scientific fields were flagged. Export
kinds are `sanitized` and `toxicity`. Unknown sessions, stale scans, detector failure, incomplete scans, and
blocked scientific fields fail closed. Raw values are not included in audit exports.

## Validation and recovery

```sh
toxicity/.venv/bin/python -m pytest toxicity/tests privacy/tests -q
toxicity/.venv/bin/python -m privacy.evaluate
node --check privacy/static/app.js
```

Ordinary tests are offline and use a clearly identified detector test double. The separate
privacy evaluation uses the real checkpoint, synthetic examples, blocked outbound socket
connections and the complete review/export/DILI path. It records character-level detection
metrics, scientific-value preservation and integration status. These synthetic metrics
are not a clinical privacy benchmark.

If the detector is unavailable or an asset checksum fails, export remains blocked.
Re-run the explicit setup command before accepting user data. There is no hidden cloud
fallback. If the DILI artifact is missing, train/evaluate again from the frozen dataset.
Cached demo requests/responses remain available for a disclosed offline illustration.

## Boundary and limits

The independent gateway uses an OpenAI-authored open-weight model locally; it does not
depend on an OpenAI-hosted filtering service. It cannot intercept data pasted directly
into other apps or guarantee anonymity. Clinical context and combinations of attributes
may identify people despite redaction. Review remains necessary.

Raw content is retained only in process/browser memory; it is not written to application
logs, telemetry or temporary upload files. This is not secure memory erasure or protection
against compromised devices, browser extensions, OS swap/crash dumps or other local users.
Only deliberately downloaded sanitized artifacts are persisted by the UI.

Sources: [OpenAI Privacy Filter](https://github.com/openai/privacy-filter), source revision
`f7f00ca7fb869683eb732c010299d901457f19c3`; checkpoint
`openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b`, Apache 2.0.

## Merge handoff to Team A

The authoritative contracts are `contracts/request.schema.json` and
`contracts/response.schema.json`; both streams now use these schemas. Team B outputs
`calibration.status: assessed`, a string attribution reference, and structured error
objects. Valid request identities are retained in failed records. The three cached
DILI outputs pass Team A's identity-aware validator and combined-report runtime.

`tests/integration/test_team_b_handoff.py` tests this using an explicitly not-run
conventional comparator. Missing conventional evidence produces unavailable comparison,
not an invented disagreement score. Team A must supply its real comparator next.

The user completed the local browser smoke test successfully. Team B's implementation
handoff is complete; improvement of model performance is deferred. Public CSVs are
tracked on main; weights are intentionally not committed. A fresh checkout can train
from the shared CSV using the commands above, or use the cached outputs immediately.
