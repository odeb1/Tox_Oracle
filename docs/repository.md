# Repository map

The repository uses two workspaces with a shared contract boundary. Keep components independently runnable so discovery integration does not depend on installing the toxicity training stack. READMEs preserve directories in Git and explain their responsibility; source subpackages should be introduced as implementation lands.

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
├── app/                          Combined report/UI, if needed beyond Workbench
├── privacy/                      Optional independent local input boundary
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
| Target identity and preparation metadata | `discovery/configs/targets/` |
| DILI standardisation/feature/model code | `toxicity/src/` |
| Downloaded FDA data | `data/raw/` (local, ignored; ingestion creates it) |
| Intermediate and curated training tables | `data/interim/`, `data/processed/` (local, ignored) |
| Data download URLs, checksums and exclusions | `data/manifests/` |
| Model weights and full prediction runs | `artifacts/models/`, `artifacts/runs/` (local, ignored) |
| Source-backed historical assay evidence | `cases/` |
| Final shareable evaluation figures | `evaluation/reports/` |
| Large demo recording | External artifact storage; link from `demo/` |
| Browser/report rendering code | `app/` |
| Sensitive subject-level data | Outside the repository and external Workbench |

## Boundaries

Discovery and toxicity exchange versioned records through `contracts/`; neither should import the other's training or vendor implementation internals. The app joins these records and applies an explicit prioritisation rule. Evaluation consumes saved outputs and split manifests. The optional privacy boundary executes locally and releases only permitted summaries.

Add a dependency manifest and lockfile in each runnable workspace when its stack is selected. Do not add empty CI jobs, unused services or deployment manifests merely to fill the tree. A root shared package can be introduced later if actual code duplication warrants it.

`BUILD_PLAN.md` defines the product and interface. This file defines physical placement. Update both if the architecture materially changes.
