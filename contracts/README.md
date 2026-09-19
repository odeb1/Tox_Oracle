# Shared interface

Joint ownership. Version JSON schemas here; keep runnable fixtures in `examples/`. The initial field meanings are in ../BUILD_PLAN.md, section 6. Coordinate changes across both teams before implementation.

`assessment-request-v2.schema.json` and `assessment-response-v2.schema.json` formalize
the existing v2 handoff. Candidate preparation generates molecular/atom identities once;
inference preserves and validates them. Both streams use the same core envelope.
Runnable public held-out examples are in `demo/examples/dili_request.json` and
`dili_response.json`. They are computed Team B results, not mock predictions.

Privacy scan/approval state is separate from these scientific records. Raw patient fields
must never be inserted into this contract. Similar 0–1 scores do not establish comparison
eligibility; follow the endpoint and calibration checks in BUILD_PLAN.md.
