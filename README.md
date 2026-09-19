# ToxOracle

An agentic drug-discovery workflow with a separate human liver-toxicity assessment, built for the London AI × Bio Hackathon.

Rosalind coordinates existing BioNeMo discovery tools and a ToxOracle DILI predictor to help researchers prioritise candidates and choose follow-up experiments.

**Status:** runnable [DILIrank 2.0 curation and DILI baseline](toxicity/README.md), held-out evaluation,
v2 batch predictions and a [standalone local privacy gateway](privacy/README.md).
Live discovery integration remains Team A work. Start with the
[Team B local MVP runbook](docs/runbooks/team-b-local-mvp.md).

## Start here

- [Shared build plan](BUILD_PLAN.md): scope, ownership, contracts, milestones and demo acceptance criteria.
- [Repository map](docs/repository.md): directory tree and where each team works.
- [Contribution guide](CONTRIBUTING.md): handoffs, validation and artifact policy.
- [Agent context](AGENTS.md): project history and confirmed architectural corrections.

## Team workspaces

| Team | Main directories | First handoff |
|---|---|---|
| A: Rosalind and discovery | `discovery/`, `app/` | Real discovery result with stable candidate IDs |
| B: human DILI | `toxicity/`, `data/manifests/`, `evaluation/`, `cases/` | Batch predictor using the shared interface |
| Joint integration | `contracts/`, `configs/`, `tests/integration/`, `demo/` | One complete discovery-to-toxicity report |

Small fixtures and reviewed evidence belong in Git. Downloaded datasets, weights and run outputs stay local or in artifact storage. See [data policy](data/README.md) and [artifact policy](artifacts/README.md).

This project estimates drug-level DILI concern for research prioritisation. Its outputs do not establish patient-level safety or clinical efficacy.
