# Static public demo on Vercel — implementation plan

Status: implemented on `feat/static-public-demo`, 20 September 2026. Static build and local browser acceptance passed; deployed to https://toxoracle-demo.vercel.app. See `docs/runbooks/public-demo.md`.

## Outcome and boundaries

Keep the existing local researcher app for real execution. Publish a self-contained
interactive ABL1 walkthrough on Vercel, reusing the current visual design and Results
views. The hosted site must work with the laptop shut down, without Python services,
NVIDIA credentials, a job queue, visitor accounts or live-run codes. Leave the existing
Streamlit site intact. Brev deployment is deferred.

Use a new `feat/static-public-demo` branch from the completed researcher-demo branch
when implementation begins. The selected public presentation artifacts are an explicit,
reviewed export; never copy an entire artifacts directory into the site or repository.

## Visitor experience

- Workspace remains the entry point. The default example is target-only ABL1 generation;
  the optional candidate-data section offers the public four-compound supplied route.
  Provide Start walkthrough and Explore results now actions.
- Prefill the recorded question. If a visitor changes it, explain that this version can
  replay the prepared ABL1 study and offer an explicit Use example action. Do not attach
  the saved results to an unrelated question or pretend to interpret new prompts.
- Provide Use example dataset and a downloadable public CSV for the supplied route.
  Support browser-only CSV/JSON selection of that exact panel, comparing IDs and SMILES
  against the published fixture, independent of row order. Reject unmatched inputs with
  a useful example action. No uploaded bytes or typed questions are transmitted or saved.
- Retain the five Workspace steps, backward navigation and top-level Results. The review
  stage shows the saved sanitized inputs, privacy audit and destinations; Continue advances
  the walkthrough and does not assert a new privacy scan or outbound approval occurred.
- Replay real saved events in original order, compressed to approximately 45 seconds.
  Supply pause/resume, next-stage and skip-to-results controls. Use recorded event counts
  for progress. Preserve original timestamps/durations separately from playback time.
- A small persistent Recorded demo / real saved results badge identifies the mode. Keep
  technical details expandable. Name Nemotron only where the selected source run used it;
  do not imply Rosalind was invoked. Methods distinguishes the implemented local privacy
  workflow from the future local-to-hosted companion integration.
- Results retains separate binding and DILI signals, the frozen shortlist, follow-up,
  candidate features, evaluation context, source downloads and interactive 3D poses.
  Missing evidence remains visible. Lazy-load coordinate files on View 3D pose.
- Study runs becomes Example studies in the static site. Remember selected example,
  reached step and playback position in browser storage, with a schema version and reset
  action. Never store user input. Refresh restores the walkthrough without replaying it.

## Evidence selection and export

The user selected `bf3e06a08c46441facc6e51def76b04d` as the main source: an agent-enabled
live generation run with 20 candidates, 18 successful discovery results and two failures.
Preserve that run intact, including its recorded Nemotron planning and explanation. Do not
substitute the complete cached cohort or mix evidence between runs. No new recording or
NVIDIA inference is required for this implementation.

Use the complete agent-enabled supplied-panel run `d8ee241e77134215a8bfe0b3b6bcdc7a`
for the secondary example, subject to export validation. Preserve all source limitations,
model/data identifiers, calibration and training-membership disclosures.

Implement a deterministic local exporter using the existing validated report contracts
and shared RDKit molecule/feature renderer. Export only public approved questions and
inputs, a minimized privacy audit, actual execution events, validated scientific reports,
generation summary, saved assistant text, evaluation context and verified structure files.
Pre-render whole-molecule SVGs and every selectable feature with atom labels on/off;
no RDKit or model runtime is needed in visitors' browsers.

Produce a versioned manifest linking the exact source run to each asset, with SHA-256
checksums and recorded execution mode/status. Preserve numeric evidence and identities;
rewrite filesystem artifact references to packaged relative URLs. Remove local paths,
owner/session IDs, approval credentials, private prompts, raw provider payloads and any
secrets. Validate references, file sizes, checksums and report consistency before export.
Keep model weights, raw datasets and provider caches excluded. Fail export on a missing
required selected pose rather than publishing a broken link; genuinely unavailable
scientific results retain their unavailable status and have no View pose action.

## Implementation and hosting

Refactor presentation to use an explicit data-source interface: local API for the existing
app, immutable manifest/assets for the static demo. Separate session/approval/inference
controls from report rendering. Add an independent static entry point and replay controller;
do not emulate live POST endpoints or weaken the existing local privacy gateway.

Commit the small reviewed public export with its provenance so deployment is reproducible
without the author's ignored artifacts directory. The static build assembles existing UI,
vendored 3Dmol and the two exported bundles into `dist/`. Vercel serves only this directory.
Keep the Python exporter outside the deployed runtime; no Next.js rewrite or serverless
inference functions. Use same-origin assets, restrictive security headers and no analytics
that collect input content. Use independent data-source and replay-state tests.

Create a dedicated Vercel project and stable project `vercel.app` URL; use preview deployments
for review and promote the tested version for sharing. Retain prior deployments for rollback.
No domain purchase is required. Deployment requires the user's Vercel account connection,
which has not been inspected or established in this planning step. Deliver the final URL,
QR code, export/update commands and a brief maintainer runbook. Do not change the Streamlit
project or expose the laptop's local server.

## Acceptance

- Both routes complete from prepared inputs to Results; navigation, pause, skip and reload
  preserve the correct example and reached stages. Unmatched inputs never receive fabricated
  study-specific predictions. Switching examples clears the previous result context.
- All scores, ranks, shortlist membership, limitations and assistant identity/text match the
  selected source. Failed discovery rows stay unavailable and are not silently removed.
- Every packaged pose renders; candidate/pose switching, ligand focus, protein visibility,
  features, atom labels, filtering and report downloads work on desktop and narrow screens.
- Static-host smoke test passes with Python/local APIs unavailable and provider requests
  blocked. Browser requests are limited to published static assets, never localhost,
  NVIDIA or an external molecule viewer. No visitor input appears in URLs or requests.
- Export and package scans reject secrets, local paths and unwanted artifacts. Verify all
  manifest hashes and fixture identity checks; test tampered/missing assets with clear errors.
- Run `scripts/check.sh`, existing web/privacy tests, exporter/data-source tests and browser
  acceptance for the local app after the shared-rendering refactor.
- Verify the public preview in a fresh browser session without accounts, credentials or
  laptop connectivity before publishing the judging URL and QR code.
