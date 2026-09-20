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
mmCIF poses have an interactive local 3D viewer, downloads and provenance. Imported reports cannot instruct the server to read local
structure paths; they can load a user-selected local file only after a SHA-256
match to the selected candidate artifact. Importing also does not authenticate the supplied science.

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

## Workspace step history and 3D poses

The Workspace stepper now navigates reached steps. Selecting a prior step changes
only the view; polling and job completion retain that selection. Previous/Next
and Return to current step controls are provided. Once a study is submitted,
inputs and privacy approval are read-only records loaded from the owned run's
`approved.json`; editing requires a new study and fresh review. Unavailable
original records in imported or recorded results are explicitly identified.

Discovery lab uses locally vendored 3Dmol.js 2.5.5 (BSD-3-Clause, package integrity
and browser-build checksum recorded in `web_static/vendor/README.md`). It draws
the selected candidate's saved Boltz-2 coordinates with protein cartoon and ligand
sticks, rotation/zoom, Fit complex, Focus ligand and protein visibility controls.
No structure is fetched from an external viewer, and no new pose is generated.

Owned artifacts remain session-gated and checksum/containment verified. The
recorded public study can also load its original local artifacts through its
verified server-side manifest, restricted to that source run. Missing files fail
visibly. Imported reports can select a matching local structure file, validated
in the browser without upload. Pose atom mapping to DILI features is unavailable;
visualization does not imply causal attribution or experimentally measured binding.

Acceptance for the additional features: 85 web/privacy tests passed, plus the
Node navigation-state checks (future-step gating, polling, completion, backtracking
and reset). Chrome verified backward navigation from DILI to discovery, pre-run
input/review navigation, post-run read-only approval, and the protein/ligand viewer
with ligand focus and protein visibility. A fresh real cached four-compound run
completed through privacy review and DILI without provider calls; its session-owned
pose rendered successfully and its study reopened after a page reload. Public
recorded pose rendering was also verified. Local coordinate file selection remains
subject to the previously documented browser-extension upload permission; no
automated file-chooser acceptance is claimed.
