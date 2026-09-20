# Static public demo

The public demo replays two reviewed ABL1 recordings with the existing Results
views. The live local app and teammate's Streamlit site remain separate and intact.
Implementation branch: `feat/static-public-demo`. Public URL: **https://toxoracle-demo.vercel.app**.
[Judging QR (PNG)](../assets/public-demo-qr.png) · [QR (SVG)](../assets/public-demo-qr.svg).

## Build and preview

Requires Node 22+; no npm dependencies or NVIDIA credentials:

```sh
node scripts/build-public-demo.mjs
python3 scripts/serve-public-demo.py --port 8771
```

Open http://127.0.0.1:8771. This preview serves files only and applies the same
security headers as Vercel. It does not run the scientific backend. The approximately
23 MB package includes all 22 available poses and molecule/feature SVG variants;
coordinates and feature variants load only when requested. The built `dist/` is
ignored; reviewed source exports are committed under `demo/public/studies/`.

Visitors can start with the recorded target-only question, use the public panel,
pause playback, revisit steps, or go straight to Results. Changed questions and
unmatched candidate data require an explicit return to the example. The optional
file input compares IDs and exact published SMILES, independent of row order;
it does not chemically canonicalize alternate SMILES. Files and questions stay in
memory. Only versioned example/step/event progress enters localStorage.
Refresh resumes paused. Reset walkthrough clears progress and inputs for the
current example. Example studies switches recordings without mixing their evidence.

Share the base URL for the main journey, `?example=supplied` for the supplied panel,
or `?example=generated&stage=results` for a direct Results entry. These links contain
only public example identifiers. No login, key, laptop connection or live inference
is required after deployment. This is not a service-worker offline installation;
loading previously unvisited assets still requires network connectivity.

## Deploy on Vercel

Log in to the intended Vercel account in your terminal:

```sh
npx vercel login
```

Deploy **only the built directory** to a dedicated project named `toxoracle-demo`:

```sh
node scripts/build-public-demo.mjs
npx vercel deploy dist --project toxoracle-demo --scope tox-oracle --yes
```

The dedicated `tox-oracle/toxoracle-demo` project already exists. For a different
account, create a new project first with `vercel project add` and use its scope.
Vercel automatically assigns a project’s first deployment to production; later
deployments are previews unless `--prod` is specified.

The build writes a standalone `dist/vercel.json` with no build/install command and
with security headers. Inspect the project prompts: use a new static project, not
the Streamlit project or another existing deployment. Keep account linkage in the
ignored `.vercel/` directory. No environment variables are needed.

Verify the returned preview URL, then publish the same package:

```sh
npx vercel deploy dist --project toxoracle-demo --scope tox-oracle --prod --yes
```

Share the stable project URL returned by Vercel, not an authenticated dashboard or
protected preview URL. Confirm a signed-out visitor can access it. If account-level
protection blocks public viewing, resolve it explicitly with the project owner.
Keep the previous deployment available for rollback in Vercel's project dashboard.
A Git-connected alternative uses root `vercel.json`: Other framework, Node 22+,
`node scripts/build-public-demo.mjs`, output `dist`. CLI deployment from `dist`
is preferred because only reviewed static files are uploaded.

## Complete-evidence demo cohort

The generated walkthrough now uses a derived 18-candidate cohort: only candidates
with successful discovery and toxicity assessments. Both original shortlisted
candidates, all ranks, scores and 18 poses are unchanged. The four Overview cards
show 18 assessed, 2 shortlisted, 2 prioritised for liver validation and 0 incomplete.
The incomplete count is a separate status, not a downstream shortlist outcome.

The original `generated/study.json`, `report.json`, `report.html` and assets remain
unchanged. `manifest.json` points the UI to `cohort-study.json`, `cohort-report.json`
and `cohort-report.html`. Source report and generation-ledger downloads remain in
Methods & setup. Original privacy approvals and verbatim agent notes refer to the
full 20-candidate source run; agent notes are labelled and collapsed in the cohort
walkthrough. Playback filters excluded candidate events and recalculates cohort
progress counters. Saved playback uses a new storage key to avoid restoring old
event offsets. This is a presentation export, not a new scientific run.

To rebuild the cohort from the reviewed source recording:

```sh
PYTHONPATH=app/src:discovery/src:. toxicity/.venv/bin/python scripts/export-demo-cohort.py
node scripts/build-public-demo.mjs
```

The full exporter also rebuilds the cohort after exporting both original recordings.

## Updating the recordings

The exporter is intentionally restricted to the two user-selected source runs:

- Main: `bf3e06a08c46441facc6e51def76b04d`, 20 generated, 18 discovery successes,
  two failures; Nemotron enabled; both frozen shortlist candidates held.
- Supplied: `d8ee241e77134215a8bfe0b3b6bcdc7a`, four drugs, complete; Nemotron enabled.

With their original local artifacts available:

```sh
PYTHONPATH=app/src:discovery/src:. toxicity/.venv/bin/python scripts/export-public-demo.py
node scripts/build-public-demo.mjs
```

This uses RDKit and validated contracts, makes no provider calls, and never reads
credentials. Missing/altered poses and unexpected stale files fail export. Review
export diffs before committing any new evidence. Do not copy `artifacts/`, a key
file, provider responses or model weights into the public package.

## Verification

```sh
PATH="$PWD/toxicity/.venv/bin:$PATH" ./scripts/check.sh
PYTHONPATH=app/src:discovery/src:. toxicity/.venv/bin/python -m pytest app/web_tests privacy/tests -q
node app/web_tests/test_study_navigation.cjs
node app/web_tests/test_public_demo.cjs
node scripts/build-public-demo.mjs
```

The public checks cover both reports, original-source numeric parity when source
artifacts are available, all assets and pose checksums, every feature/label variant,
invalid panels, missing/tampered assets, future-step gating and paused restoration.
Browser acceptance additionally checks both routes, all 22 WebGL poses, feature
controls, filtering, downloads, mobile layout and the local app after shared-view
changes. Live inference is intentionally not part of this static deployment check.

## Verified deployment (20 September 2026)

Production deployment `dpl_FvigLc2LXeqYchbZssFpSU12y8H5` serves the stable URL
above. Anonymous requests returned HTTP 200; all 567 checked scientific/UI assets
matched the tested local build byte for byte. All 22 available poses rendered in
Chrome; the hosted top shortlisted pose also rendered successfully. The existing
local API dashboard and pose viewer passed regression checks. Repository checks,
87 web/privacy tests and the Node public-source/replay tests passed.

Evidence: `evaluation/reports/static_public_demo_v1.json`. File chooser automation
was not exercised; the same exact-panel parsing is tested and the pasted-data UI
was exercised. No live provider inference was performed for this deployment.
