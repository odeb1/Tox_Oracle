# Complete researcher demo

Approved 20 September 2026. Implementation branch: `feat/researcher-demo-workflow`,
created from current main and integrating the existing researcher workspace commit.

## Outcome and design

Deliver a local, refined scientific workspace: Oxford navy, warm ivory, elegant
headings, locally rendered molecular structures and restrained accessible motion.
Five stages: Set up → Review privately → Run discovery → Assess liver concern → Results.
Preserve study identity and execution mode across all stages. Supplied candidates and
the public four-compound ABL1 panel are the first-release paths. Generation remains a
separate recorded example; the public Streamlit demo and scientific policies stay intact.

## Behavior

- Accept research prompt and CSV/JSON candidates; preview structures and row errors.
- Filter prompt and dataset locally; show reviewed contents and destinations, require
  per-field scientific retention and explicit approval. Edits revoke approval.
- Use NVIDIA Nemotron 3 Nano for validated structured planning and evidence-grounded
  explanations. A bounded tool requests the existing ABL1 workflow; backend controls
  reference gating, ranking, shortlist freeze, DILI inference and follow-up.
- Show actual model operations, candidate completion, elapsed time and source evidence.
  No invented progress percentages, model identities or reasoning transcripts.
- Preserve original discovery rank while revealing DILI and changed follow-up. Binding,
  affinity, confidence and DILI remain separate. Expose membership and limitations.
- Provide live execution and clearly labelled manual recorded walkthrough; retain
  cache-only computation without silently switching modes or contacting providers.
- Support idempotent submission, cancellation between operations, refresh recovery and
  explicit continuation with the fixed protocol after technical assistant failure.
- Export validated reports; keep secrets and raw uploads out of saved study records.

## Architecture

Retain FastAPI plus local HTML/CSS/JavaScript; no framework migration. Generalize the
assistant API and job state; preserve scientific v2/v3 envelopes. Bind to loopback.
Provider credentials come from process environment only. A hosted/local companion,
additional targets, model retraining and live generation UI are outside this iteration.

## Acceptance

Run existing repository, web/privacy, generation and dashboard checks. Cover approval
invalidation, frozen shortlist integrity, duplicate submissions, malformed assistant
output, rate limits, cancellation, partial failures, cache misses and offline replay.
Inspect every stage at 1440×900, 1280×720 and 390px; check keyboard access, contrast,
reduced motion and overflow. Complete a real four-compound web run with local privacy,
Nemotron, Boltz-2 and local DILI, recording live gates separately if credentials or
services prevent acceptance. Rehearse the full prompt-to-export presentation.

## Verified provider adjustment

During live acceptance on 20 September 2026, the originally planned
`nvidia/nemotron-3-nano-30b-a3b` returned HTTP 410. The catalog-listed
`nvidia/nemotron-nano-3-30b-a3b` returned HTTP 404. The staff-suggested
`nvidia/nemotron-3.5-lightning-30b-a3b` completed the greeting with the exact returned
model identity. Implementation therefore explicitly uses Nemotron 3.5 Lightning;
no silent per-request model fallback is implemented. NVIDIA's current example:
https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b
