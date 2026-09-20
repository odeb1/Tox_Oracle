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
2. Choose **Live run** or **Cached screening · local DILI**. Live
   mode makes fresh vendor calls and can incur charges. Offline mode verifies
   every cache entry first and has a client that refuses all network fallbacks.
3. **Review privately** runs the existing local privacy scanner. Review the
   sanitized data and the prepared molecular request. Confirm each flagged but
   chemically valid scientific field separately. The target, execution mode and
   assistant choice are bound to this snapshot; any edit revokes approval.
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

## NVIDIA assistant and structured planning

Start in the existing privacy/scientific environment with `./scripts/toxoracle-web`.
Keep `NVIDIA_API_KEY` in that terminal's environment, never in files, browser storage
or chat. The server must be restarted to inherit a newly configured key. If you already keep a
key in a local file, `./scripts/toxoracle-web --nvidia-key-file /path/to/existing-key`
reads it into process memory only. The app never creates or copies that key file.

In **Methods & setup**, verify the connection with a fixed greeting, then enable
**Use NVIDIA Nemotron planning** before review. The configured model is
`nvidia/nemotron-3.5-lightning-30b-a3b` on NVIDIA's chat-completions endpoint. Requested and
returned IDs are checked and retained. No Rosalind identity or invocation is claimed.
The old Rosalind adapter remains dormant for historical compatibility.

Approval covers the sanitized question, candidate IDs and computed evidence shared
with NVIDIA's assistant, as well as structures and the public sequence sent to Boltz-2.
The assistant requests one bounded `prepare_abl1_screening` operation, returning the
approved target, unchanged candidate IDs, support status and a brief explanation.
The backend validates the response and runs the fixed scientific protocol. Unsupported
questions pause for a revised study; malformed output or technical failure pauses
before screening and offers **Continue with approved fixed protocol**. This explicit
choice is recorded and cannot submit science twice. Explanation failure leaves validated
results available. No arbitrary commands or model-generated thresholds are executed.
Cached screening disables the assistant and never falls back to the network.

## Recorded walkthrough and presentation

The landing page's **Open recorded walkthrough** loads the bundled public ABL1 study
from `demo/examples/abl1_recorded_workspace`. File hashes and v3 consistency are checked
before display. Stage navigation is manual: no new privacy approval, inference or timed
progress is fabricated. The original study reused verified Boltz-2 responses and ran
local DILI. Repository-relative artifact pointers are provenance only; the large raw
vendor files are not bundled or served. All four drugs overlap model fitting/selection.

For a new study, use the public panel (or upload CSV/JSON), preview molecules and correct
row errors. Review privately, acknowledge each retained scientific field, then approve
and run. The activity panel shows actual operations and the currently invoked model;
elapsed time is wall-clock time, never an estimated completion percentage. A browser
refresh reconnects to active or paused jobs in the same session. Completed runs are
available under **Study runs**. Open a candidate, switch **Discovery only / With human
DILI**, then export the HTML report or source JSON. Recorded results export source JSON.

The five stages are **Set up → Review privately → Run discovery → Assess liver concern
→ Results**. Navy/ivory styling and molecule rendering are entirely local. Review at
1440×900, 1280×720 and 390px width; all controls remain keyboard accessible and motion
respects reduced-motion preferences. The public Streamlit app is unchanged.

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

## Validation and acceptance

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

Current acceptance results are recorded in
`evaluation/reports/researcher_demo_acceptance_v1.json`. Offline synthetic tests are
not scientific validation. The real cached web acceptance uses the actual privacy
filter, exact-input Boltz-2 cache and trained DILI model. Hosted Nemotron and fresh
Boltz-2 acceptance are separate gates; both passed on 20 September 2026 using the public panel. A key in the server environment is required to repeat them.
