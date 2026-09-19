# Standalone researcher workspace

ToxOracle owns prompt entry, target selection, candidate upload, local privacy
review/approval, workflow progress and the results dashboard. The initial target
is human ABL1 (2HYY chain A). This is a local application, binding only to
`http://127.0.0.1:8766`; the public Streamlit demo remains separate.

## Install and open

Run from the repository root. The interface and offline tests were verified with
Python 3.11 on macOS arm64; the production privacy environment uses Python 3.12
as documented in the [Team B setup](team-b-local-mvp.md).

```sh
python3 -m venv app/.venv
app/.venv/bin/python -m pip install -r app/requirements-web.lock -e app -e discovery
PYTHONPATH=app/src:discovery/src:. app/.venv/bin/python -m toxoracle_app.web
```

This opens the UI and report inspector without downloading weights. Before running
studies, restore the existing trusted model and privacy assets. Do not upload model
weights through the browser. No automatic training occurs.

| Dependency | Default location / configuration |
|---|---|
| Trained DILI artifact | `artifacts/models/dili_baseline.joblib` or `--model` |
| Original scientific interpreter | `toxicity/.venv/bin/python` or `--model-python` |
| Privacy checkpoint and integrity manifest | `artifacts/privacy/checkpoint/` |
| Privacy tokenizer cache | `artifacts/privacy/cache/tiktoken/` |
| Privacy runtime in the **web server's** environment | Pinned `opf` and dependencies from `privacy/requirements.lock` |
| NVIDIA credential for live mode | `NVIDIA_API_KEY`, `NVIDIA_BIONEMO_API_KEY` or `NGC_API_KEY` |
| Exact-input Boltz-2 cache for offline mode | `artifacts/cache/boltz2/` or `--cache-dir` |
| Approved inputs and generated results | `artifacts/web/runs/` or `--runs-dir` |

If the existing Python 3.12 privacy/science environment is already configured, run
the workspace in that environment so the scanner can import its pinned runtime:

```sh
PYTHONPATH=app/src:discovery/src:. toxicity/.venv/bin/python -m toxoracle_app.web
```

The existing privacy environment already includes FastAPI and Uvicorn. To create it
from scratch, follow Team B's setup (`privacy/requirements.lock` and the explicit
`privacy.setup_model` download) before accepting research inputs. This downloads
roughly 3 GB; startup never initiates that download. Keep the model's original
scientific environment for inference rather than assuming the UI environment is
an equivalent scientific environment. `--model-python` preserves venv symlinks.

## Researcher flow

1. Enter a question, choose ABL1 and upload/paste CSV or JSON. CSV requires
   `compound_id,smiles`; JSON accepts a list or an envelope with `compounds`.
   Files must be UTF-8, at most 1 MB, with 2–32 candidates. Include `LT00107` with
   the validated imatinib structure; **Use public ABL1 panel** supplies it.
2. Choose **Live NVIDIA screening** or **Verified cache · fully offline**. Live
   mode makes fresh vendor calls and can incur charges. Offline mode verifies
   every cache entry first and has a client that refuses all network fallbacks.
3. **Review privately** runs the existing local privacy scanner. Review the
   sanitized data and the prepared molecular request. Confirm each flagged but
   chemically valid scientific field separately. The target, execution mode and
   Rosalind choice are bound to this snapshot; any edit revokes approval.
4. **Approve & run** freezes the approved study. NVIDIA receives only the molecular
   structures and public protein sequence. The raw upload is not persisted.
   Request IDs, target, model digest and exact discovery artifacts remain local.
5. Follow real stage events. Imatinib must pass the existing reference gate before
   remaining candidates are screened. `discovery.json` is saved and hashed before
   local DILI inference. The dashboard uses the unchanged v3 decision policy.
6. Inspect shortlist transitions, candidate binding arrays, affinity, structural
   confidence, DILI score/call/threshold, training membership, applicability,
   uncertainty and recommended experiments. Scores are never fused or subtracted.
7. Export the v3 JSON or download frozen discovery during a run. Study runs can be
   reopened within the same tab session; saved `science/combined.json` reports can
   be imported after a restart. Imported reports are validated locally and never
   sent to providers. Consistency validation does not authenticate their origin.

The question adds research context to the fixed workflow. It cannot execute arbitrary
commands or select unvalidated protocols. Only ABL1 currently has a validated target
manifest, reference and follow-up policy; adding a dropdown item alone is insufficient
to support another target.

## Rosalind interface and verification

The adapter uses the documented [Responses API](https://developers.openai.com/api/docs/guides/text)
at `https://api.openai.com/v1/responses`, with `store: false`, bounded output and no
tools, shell execution, automatic retries or alternate-model fallback. The Workbench
launcher is never invoked. Server-side `OPENAI_API_KEY` supplies the credential;
`TOXORACLE_ROSALIND_MODEL` can choose an allowlisted account-visible Rosalind ID.

**Verification on 20 September 2026:** `/v1/models` exposed
`gpt-rosalind-5.5-260602`, `gpt-5.5-rosalind-260602`, `gpt-5.5-rosalind`, and
`gpt-rosalind-research`. Short greeting calls to `gpt-5.5-rosalind` and
`gpt-rosalind-5.5-260602` completed but reported `gpt-5.5-2026-04-23`. A greeting
check to `gpt-rosalind-research` did not succeed. These observations establish that
some aliases are callable, **not** that their reported identity confirms Rosalind.
No research data was sent during these checks.

The UI's **Verify API connection** sends a fixed greeting. Notes remain disabled
unless a completed response reports a Rosalind identity. Resolve the alias/identity
contract with the provider or the organization's API administrator before enabling
the feature; do not relabel general GPT output as Rosalind. Both requested and returned
model IDs are retained for successful notes. Verification is per server process.

If verification succeeds, the researcher can opt in **before** privacy review.
Approval then covers the sanitized prompt, candidate IDs and computed evidence
summary shared with OpenAI. Rosalind supplies an advisory plan note and result
explanation. The backend controls execution and the frozen policy; generated prose
cannot modify either. Optional assistant failure does not discard scientific results.
Fully offline mode disables Rosalind, regardless of API configuration.

## Execution and recovery

- Only one run executes at a time; at most 32 jobs are retained per server process.
  Repeating submission of the same approved scan returns its existing job, including
  after a lost HTTP response. A new paid run needs a newly scanned and approved study.
- Cancellation stops **between** operations. It cannot recall an already submitted
  NVIDIA request. A remote call may take up to 600 seconds and a local model subprocess
  up to 300 seconds. Completed artifacts remain available; no partial result is called
  complete. Failed DILI inference preserves the discovery shortlist and marks DILI
  unavailable.
- The browser stores only the session identifier in tab storage. Inputs, review
  snapshots and tokens are not saved in browser storage. After successful submission,
  raw editor contents are cleared. Sessions expire after 30 minutes of inactivity.
- Approved jobs continue if a tab closes. A server restart does not automatically
  resume or repeat inference. Inspect saved artifacts and start a new reviewed run
  if needed. A hard crash can leave an on-disk job marked running; that is an
  interrupted historical run, not a live worker. Report import is the recovery path.
- The shared gateway enforces loopback Host/Origin, a launch token, session ownership,
  body limits, approval versions, no-store responses and a same-origin content policy.
  No cloud-hosted browser entry point is provided for raw inputs. A hosted product
  needs an authenticated local companion and a reviewed handoff architecture.

## Validation and remaining live acceptance

```sh
PATH="$PWD/app/.venv/bin:$PATH" bash scripts/check-web.sh
PATH="$PWD/app/.venv/bin:$PATH" bash scripts/check.sh
PATH="$PWD/.venv/bin:$PATH" bash scripts/check-demo.sh
```

Web tests use explicitly injected synthetic detectors, vendor responses and model
outputs; there is no production test-mode switch. They cover approval, invalidation
races, immutable settings, reference identity, idempotency, session ownership,
cache-only execution, cancellation, errors, imports and assistant identity checks.
The independent privacy tests also run unchanged.

This checkout did not contain the trained DILI artifact, local privacy checkpoint,
privacy runtime or Boltz-2 cache when implementation began. The app's UI, API and
offline tests can be verified; a real end-to-end web study remains an acceptance
step once these existing assets are restored. Previous terminal/desktop scientific
runs are documented in the [screening runbook](rosalind-screening.md), and are not
represented as a newly completed web run.
