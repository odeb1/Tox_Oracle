# ToxOracle

An agentic drug-discovery workflow with a separate human liver-toxicity assessment, built for the London AI × Bio Hackathon.

Rosalind coordinates existing BioNeMo discovery tools and a ToxOracle DILI predictor to help researchers prioritise candidates and choose follow-up experiments.

**Status:** The discovery-first workflow now screens a frozen public ABL1 panel with
BioNeMo Boltz-2, adds the existing local DILI model and produces a v3 before/after
report. A real reference check and four-compound terminal run succeeded, followed
by a verified desktop Rosalind replay using the exact-input cache. Team B's evaluated baseline,
privacy gateway and v2 handoff remain unchanged; a second toxicity predictor is not
required for this workflow. Legacy DiffDock and v2 comparison commands remain available.

Start with the [Rosalind screening runbook](docs/runbooks/rosalind-screening.md) and
`./scripts/toxoracle-screen preflight`. The policy is provisional and the demonstration
is retrospective; candidate training membership is displayed.

See the [Team B runbook](docs/runbooks/team-b-local-mvp.md) for reproducible training,
privacy setup and real cached DILI outputs. The user has passed the browser smoke test.

## Start here

- [Shared build plan](BUILD_PLAN.md): scope, ownership, contracts, milestones and demo acceptance criteria.
- [Repository map](docs/repository.md): directory tree and where each team works.
- [Contribution guide](CONTRIBUTING.md): handoffs, validation and artifact policy.
- [Team A integration runbook](docs/runbooks/team-a-integration.md): offline checks, report generation, handoffs and recovery.
- [Agent context](AGENTS.md): project history and confirmed architectural corrections.

## Team workspaces

| Team | Main directories | First handoff |
|---|---|---|
| A: Rosalind and discovery | `discovery/`, `app/` | Real discovery result with stable candidate IDs |
| B: human DILI | `toxicity/`, `data/manifests/`, `evaluation/`, `cases/` | Batch predictor using the shared interface |
| Joint integration | `contracts/`, `configs/`, `tests/integration/`, `demo/` | One complete discovery-to-toxicity report |

Small fixtures and reviewed evidence belong in Git. Downloaded datasets, weights and run outputs stay local or in artifact storage. See [data policy](data/README.md) and [artifact policy](artifacts/README.md).

This project estimates drug-level DILI concern for research prioritisation. Its outputs do not establish patient-level safety or clinical efficacy.
