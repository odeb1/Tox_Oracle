# Repository map

The repository uses two team workspaces with a shared contract boundary. Team B also
owns the standalone `privacy/` gateway and its UI; `app/` remains the Team A combined
experience. Keep discovery independently runnable from the toxicity training stack.

```text
Tox_Oracle/
├── README.md                     Project entry point and implementation status
├── BUILD_PLAN.md                 Shared scope, contracts and milestones
├── AGENTS.md                     Persistent agent context
├── CONTRIBUTING.md               Team workflow and validation expectations
├── LICENSE                       Repository licence
├── .github/
│   └── pull_request_template.md  Review and handoff template
├── .editorconfig                 Consistent text formatting
├── .gitattributes                Text and binary handling
├── .gitignore                    Local data, artifacts and secrets exclusions
├── contracts/
│   └── examples/                 Shared schemas and small interface fixtures
├── discovery/                    Team A
│   ├── src/                      Tool adapters and orchestration
│   ├── prompts/                  Agent workflow and explanation instructions
│   ├── configs/targets/          Target preparation manifests
│   └── tests/                    Discovery component checks
├── toxicity/                     Team B
│   ├── src/                      Curation, features, training and inference
│   ├── configs/                  Reproducible model settings
│   ├── model_cards/              Versioned model documentation and artifact references
│   └── tests/                    Toxicity component checks
├── app/                          Researcher web workspace and Streamlit presentation
├── privacy/                      Independent local privacy gateway, UI and tests
├── configs/                      Shared integration and triage rules
├── data/
│   └── manifests/                Source, curation and split provenance
├── evaluation/
│   ├── src/                      Reusable evaluation code
│   └── reports/                  Reviewed, shareable metrics and figures
├── cases/                        Cited preclinical-miss evidence
├── demo/
│   ├── examples/                 Small permitted cached demo cases
│   └── pitch/                    Narrative, slide sources and claims audit
├── docs/
│   ├── repository.md             This map
│   ├── decisions/                Consequential architecture decisions
│   └── runbooks/                 Tested setup and recovery instructions
├── infra/                        Brev/container/deployment setup when selected
├── scripts/                      Thin repeatable operational entry points
├── tests/integration/            Cross-team contract and end-to-end checks
├── notebooks/                    Exploratory work
├── artifacts/                    Ignored local outputs; policy README is tracked
└── refs/                         Existing project sketches and literature
    └── papers/
```

## Placement decisions

| Item | Location |
|---|---|
| Predict request/response schema | `contracts/` |
| Synthetic malformed request | `contracts/examples/` |
| BioNeMo response adapter | `discovery/src/` |
| Workbench task instructions | `discovery/prompts/` |
| Advanced generation plan | `docs/decisions/target-only-generation-plan.md` |
| Target identity and preparation metadata | `discovery/configs/targets/` |
| DILI standardisation/feature/model code | `toxicity/src/` |
| Downloaded FDA data | `data/raw/` (local, ignored; ingestion creates it) |
| Cached source API responses | `data/cache/` (local, ignored) |
| Curated training tables | `data/processed/` (local, ignored) |
| Data download URLs, checksums and exclusions | `data/manifests/` |
| Model weights and full prediction runs | `artifacts/models/`, `artifacts/runs/` (local, ignored) |
| Source-backed historical assay evidence | `cases/` |
| Final shareable evaluation figures | `evaluation/reports/` |
| Large demo recording | External artifact storage; link from `demo/` |
| Browser/report rendering code | `app/` |
| Standalone web API and background jobs | `app/src/toxoracle_app/web.py`, `workspace_jobs.py` |
| Oxford Blue browser interface | `app/src/toxoracle_app/web_static/` |
| Optional verified Rosalind Responses adapter | `app/src/toxoracle_app/rosalind.py` |
| Approved local study runs | `artifacts/web/runs/` (ignored) |
| Web/privacy integration checks | `app/web_tests/`, `privacy/tests/` |
| Sensitive subject-level data | Outside the repository and external Workbench |

## Boundaries

Discovery and toxicity exchange versioned records through `contracts/`; neither should import the other's training or vendor implementation internals. The app joins these records and applies an explicit prioritisation rule. Evaluation consumes saved outputs and split manifests. The standalone privacy gateway executes locally and releases only reviewed, approved payloads.

The standalone web app extends the local gateway in process, preserving its exact
Host/Origin, launch-token, session expiry and approval-version checks. It reuses
`screen_cli.execute` and the existing v3 decision policy. The browser never receives
provider credentials, invokes shell commands or controls server artifact paths.
The gateway at port 8765 retains its independent UI and existing behaviour; the
research workspace uses port 8766. Streamlit at port 8501 remains a presentation app.

Add a dependency manifest and lockfile in each runnable workspace when its stack is selected. Do not add empty CI jobs, unused services or deployment manifests merely to fill the tree. A root shared package can be introduced later if actual code duplication warrants it.

`BUILD_PLAN.md` defines the product and interface. This file defines physical placement. Update both if the architecture materially changes.
