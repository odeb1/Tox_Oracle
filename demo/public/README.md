# Reviewed public recordings

This directory is the explicitly approved public export for the static demo. It is
an exception to the default generated-artifact exclusion, not permission to publish
other runs. The main recording is the original Nemotron-enabled live generation
study (18 successful discovery results out of 20); the secondary recording is the
complete four-drug supplied panel. Do not replace failed discovery with another run.

`studies/index.json` pins each manifest. Each manifest records the source run,
original report hash, execution mode, status, and hashes/sizes for every public asset.
The export preserves scientific values and original agent prose. Its report rewrites
pose URIs to packaged files and raw-response URIs to non-resolving content hashes.
Raw responses, credentials, owner/session state, model weights and private inputs
are not included. Original reports are not authenticated merely by their rewritten
export hash; their original checksum is recorded separately.

Molecular SVGs are rendered by the existing RDKit evidence helper. Coordinate files
are byte-for-byte copies checked against the original report. NVIDIA model outputs
and third-party material retain their original terms; the repository licence does
not supersede those terms. 3Dmol's separate licence is distributed with the viewer.

Re-export only with the two original local recordings present. See
[the runbook](../../docs/runbooks/public-demo.md). Ordinary builds require Node 22+
and these committed assets only; no Python runtime, API key or local server is used
by the deployed app.
