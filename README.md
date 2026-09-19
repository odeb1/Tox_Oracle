# ToxOracle

An agentic drug-discovery workflow with a separate human liver-toxicity assessment, built for the London AI × Bio Hackathon.

The researcher workspace coordinates existing BioNeMo discovery tools and a ToxOracle DILI predictor to help researchers prioritise candidates and choose follow-up experiments. Optional Rosalind notes require a verified callable API and explicit sharing approval.

**Status:** The discovery-first workflow now screens a frozen public ABL1 panel with
BioNeMo Boltz-2, adds the existing local DILI model and produces a v3 before/after
report. A real reference check and four-compound terminal run succeeded, followed
by a verified desktop Rosalind replay using the exact-input cache. Team B's evaluated baseline,
privacy gateway and v2 handoff remain unchanged; a second toxicity predictor is not
required for this workflow. Legacy DiffDock and v2 comparison commands remain available.

Start with the [Rosalind screening runbook](docs/runbooks/rosalind-screening.md) and
`./scripts/toxoracle-screen preflight`. The policy is provisional and the demonstration
is retrospective; candidate training membership is displayed.

**Target-only generation:** supplied-candidate and target-only ABL1 modes are
available through `./scripts/toxoracle-design`. GenMol proposes
fragment-derived molecules, Boltz-2 supplies discovery evidence, and the unchanged
DILI baseline adds liver concern. See the
[advanced runbook](docs/runbooks/target-only-generation.md) for commands and acceptance
status. This does not change the frozen MVP demonstration above.

See the [Team B runbook](docs/runbooks/team-b-local-mvp.md) for reproducible training,
privacy setup and real cached DILI outputs. The user has passed the browser smoke test.

## Researcher web app

The standalone Oxford Blue workspace owns study input, local privacy review and
approval, background execution, progress, and the discovery/DILI results dashboard.
Binding and DILI remain separate. The top-two discovery shortlist is frozen before
local DILI inference, making changes in follow-up visible.

```bash
python3 -m venv app/.venv
app/.venv/bin/python -m pip install -r app/requirements-web.lock -e app -e discovery
PYTHONPATH=app/src:discovery/src:. app/.venv/bin/python -m toxoracle_app.web
```

Open **http://127.0.0.1:8766**. This starts the interface and local report viewer.
Executing studies additionally requires the existing trained DILI artifact,
scientific environment and verified local privacy checkpoint/runtime. See the
[research workspace runbook](docs/runbooks/research-workspace.md) for full setup.
Missing privacy assets block submission. No models are trained or downloaded at startup.

Rosalind API aliases were callable in a connection test but returned a GPT-5.5
identity, so the app does **not** claim verified Rosalind inference. Its optional
adapter stays disabled until API access and response identity pass verification.
The Workbench launcher is not used as a backend API.

## Streamlit presentation demo

```bash
python3 -m pip install -r requirements.txt
python3 -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Open **http://127.0.0.1:8501**. The dashboard opens on **Target-only discovery**:
the recorded ABL1 generation study, from 40 GenMol proposals to 29 acceptable unique
molecules and 20 screened candidates. Switch between discovery-only and human DILI
views to see why both frozen shortlisted candidates were held for liver validation.
Download example requests and the recorded evidence. This page presents aggregate
results; individual generated molecules and their scores are not bundled.

The other pages include candidate comparison,
interactive molecular feature highlights, a rotatable saved NVIDIA docking pose,
model evaluation, study imports and HTML/CSV/JSON exports. The bundled public results
work offline without API credentials or model weights. The demo makes no live
generation or screening calls, and the public DILI examples remain separate from
the generated ABL1 study.

Complete discovery/toxicity case folders are picked up from `demo/examples/` and
`artifacts/runs/`, or can be opened as ZIP bundles in **Load a study**. Use
`TOXORACLE_DEMO_CASE=/path/to/case` to select another local case. The UI reuses the
existing validation, comparison and triage code; it does not train models or
change scientific results. See the [presentation guide](docs/runbooks/streamlit-demo.md).

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
