# Shared interface

The authoritative v2 schemas are `request.schema.json` and `response.schema.json`.
`combined-report.schema.json` validates the joined output. Follow BUILD_PLAN.md for
endpoint compatibility and calibrated comparison eligibility.

Team B provides computed held-out examples in `demo/examples/dili_request.json` and
`dili_response.json`. Candidate preparation assigns shared structures and atom maps;
both streams must preserve those identities. Privacy state is separate: raw sensitive
input must never enter this scientific handoff.
