# Shared interface

Joint ownership. Version JSON schemas here; keep runnable fixtures in `examples/`. The initial field meanings are in ../BUILD_PLAN.md, section 6. Coordinate changes across both teams before implementation.

- `request.schema.json` validates the shared batch input.
- `response.schema.json` validates either team's assessment envelope.
- `combined-report.schema.json` validates the joined comparison and priority output, including nullable-score rules for each comparison mode.
