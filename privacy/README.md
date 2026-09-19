# Local privacy gateway — Team B

Standalone loopback service and browser UI using the official OpenAI Privacy Filter
checkpoint locally. Supports text/CSV/JSON, review and approval of sanitized exports,
and a molecular-only handoff to the local DILI baseline. No external AI clients or
provider calls are made by the gateway. Raw sensitive inputs stay in session memory.

Run `toxicity/.venv/bin/python -m privacy.server` from the repository root, then visit
http://127.0.0.1:8765. Install and download weights first using the
[Team B runbook](../docs/runbooks/team-b-local-mvp.md).

The filter defaults ON. OFF is an unfiltered **local preview**, not an export bypass.
Approval is bound to the scan; edits require rescanning. Detection and review are aids,
not a guarantee of anonymity. This component cannot filter input pasted into other apps.

The model sometimes flags legitimate SMILES/compound IDs. Validated scientific fields
can be retained only through explicit per-field review and acknowledgement; the audit
records the retention count. Unvalidated flags block export and free-text PII stays masked.

Ordinary tests: `toxicity/.venv/bin/python -m pytest privacy/tests -q`.
Real checkpoint evaluation: `toxicity/.venv/bin/python -m privacy.evaluate`.
