# Unified results and shared demo

20 September 2026. Implemented on `feat/researcher-demo-workflow`.

## Confirmed direction

The user chose **current run with teammate's views**. Results is a top-level
workspace destination beside Workspace, Study runs, and Methods & setup.
Completing a run, opening a recorded walkthrough, or importing a validated v3
report opens the same Results dashboard. Merely switching tabs does not start
inference or replace the current report.

The dashboard adapts the teammate's repository implementation in `demo_ui.py`:

| View | Current-run implementation |
| --- | --- |
| Overview | Frozen shortlist, before/after follow-up, separate DILI scores and each candidate's recorded threshold |
| Candidate explorer | Binding, confidence, DILI, applicability, training membership, recommended experiment, source record, selectable fingerprint evidence and mapped atoms |
| Discovery lab | Actual Boltz-2 predictions and structure metadata; checksum-verified downloads for session-owned runs; generation ledger and execution history when available |
| Model & provenance | Reference held-out evaluation, confusion matrix, training split, checksums and method/data compatibility disclosure |

`molecular_evidence.py` is shared with the Streamlit visualizations. Hashed
fingerprint contributions are grouped once per source feature; all matching atom
environments remain visible. They are not causal explanations or additive
contributions to a differently calibrated score. The scientific models, selection
rules and v3 contracts are unchanged.

The hosted Streamlit site is not embedded or synchronized. Its unrelated saved
DiffDock example is not evidence for a current ABL1 candidate. Current Boltz-2
mmCIF poses have downloads and provenance; interactive 3D pose viewing remains a
separate enhancement. Imported reports cannot instruct the server to read local
structure paths. Importing also does not authenticate the supplied science.

## Sharing: recommendation and alternatives

A shareable URL does not require switching to Streamlit. Keep the current web
interface to preserve its visual design. Deploy a separate hosted application and
worker (for example on the team's Brev infrastructure), backed by durable run and
artifact storage. Do not expose the current loopback privacy gateway with a tunnel
or relax its origin/session protections.

A Streamlit frontend is feasible, but requires porting the prompt/review/progress
interaction into Streamlit and connecting it to the same durable job service.
Streamlit Community Cloud has resource limits and hibernation; it should not be
the sole owner of a long inference job or its only record of progress. Its
session state must not be used as the durable job queue.

Two explicitly different privacy boundaries are possible:

1. **Public hackathon demo:** accept only the public ABL1 protocol and public
   candidate inputs, with clear disclosure that processing runs on the server.
   Retain prompt interpretation, generation, screening, DILI and current-run
   results. Do not claim filtering took place on the visitor's laptop. Private
   uploads remain disabled until a local companion is implemented.
2. **Researcher workflow:** the local companion performs filtering, review and
   approval before submitting a sanitized signed/authorized job to the hosted
   service. Original raw uploads never reach that service. This retains the
   intended privacy architecture but requires local installation.

Recommended next implementation for the judges is option 1, with the researcher
workflow shown locally until the companion is ready. This recommendation is not
permission to change the existing privacy promise or publish the local service.

## Concrete hosted acceptance gates

- Public-demo input boundary and hosting destination agreed; NVIDIA credentials
  stored in the host's secret manager, never Git, browser payloads or chat.
- Jobs created idempotently, owned by a session/account, queued with bounded
  concurrency and provider usage. Persist events, candidate progress, frozen
  discovery and final artifacts independently of the web process.
- Reconnect using an opaque recovery credential: browser disconnection must not
  cancel the worker; a worker restart must restore known progress without claiming
  a lost provider response succeeded or silently repeating chargeable work.
- HTTPS, isolation between visitors, restricted uploads and retention policy.
  Keep secrets and filesystem paths out of public reports.
- Verify one live public generation run, one cached replay, two isolated visitors,
  a disconnected browser, process restart recovery, and final current-run Results.
- Publish only after these checks. No deployment or hosted job persistence is part
  of the local Results change.

Official hosting references (checked 20 September 2026):
- [Streamlit app resources and hibernation](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
- [Streamlit hosted secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)

## Local verification

- 84 web/privacy tests passed, including current-run evidence validation, shared
  fingerprint grouping, model/data mismatch disclosure, and artifact ownership,
  containment and checksum checks.
- Real saved 20-generated-candidate report: import validation and all 20 candidate
  evidence API responses passed offline; two missing discovery records preserved.
- Chrome visual checks passed for empty Results, recorded-study navigation,
  Overview, mapped feature selection with atom labels, Discovery lab metadata and
  held-out evaluation. Automated file-chooser import was blocked by the browser
  extension's file-access permission; this is not claimed as a completed UI check.
- JavaScript syntax and Git whitespace checks passed. No new NVIDIA inference was
  needed for this presentation-only change.
