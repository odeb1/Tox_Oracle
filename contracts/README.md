# Shared interface

Advanced ABL1 requests use `design-request-v1.schema.json` with explicit `screen`
or `generate_screen` mode. `generation-result-v1.schema.json` describes generation
provenance, the proposal ledger and selected IDs. The outer workflow/report links
these artifacts to unchanged candidate/toxicity v2 and discovery/report v3 records.
Input provenance records a declaration; it is not a privacy scan. Target aliases
are limited to prepared human ABL1. Reference gating is recorded separately and
does not insert the reference into a generated shortlist.

The current screening command consumes `request.schema.json` (v2),
`discovery-v3.schema.json` (binding evidence) and `response.schema.json` (unchanged
Team B toxicity v2). It produces `screening-report-v3.schema.json`. Runtime
validation also checks nested toxicity v2 records, identities, ranking, and
follow-up consistency; the report schema alone is not the complete validator.
The discovery stream has no required toxicity assessment. Legacy v2 schemas and
the legacy combine command are retained for genuine toxicity comparisons.

The authoritative v2 schemas are `request.schema.json` and `response.schema.json`.
`combined-report.schema.json` validates the joined output. Follow BUILD_PLAN.md for
endpoint compatibility and calibrated comparison eligibility.

Team B provides computed held-out examples in `demo/examples/dili_request.json` and
`dili_response.json`. Candidate preparation assigns shared structures and atom maps;
both streams must preserve those identities. Privacy state is separate: raw sensitive
input must never enter this scientific handoff.
