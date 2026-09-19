# ToxOracle project context

Read this file at the start of each session and before working in this repository. It records the team's current intent and corrections to the reference documents. Update it when the user confirms a material change in direction.

## Purpose and scope

The current shared implementation guideline is `BUILD_PLAN.md`. Read it before implementation. The agreed first build uses two teams: Team A configures Rosalind with existing BioNeMo discovery tools; Team B trains or integrates one separate human DILI predictor. A separately trained preclinical toxicity model is not required for this MVP. Published preclinical assay evidence can support documented-miss case studies, with model training membership disclosed. The primary demonstration is how adding DILI prediction changes candidate priorities and recommended experiments.

The directory and ownership map is `docs/repository.md`; follow `CONTRIBUTING.md` for handoffs and artifact policy. The initial scaffold has no operational runtime or CI yet. Add tested commands and dependency pins as implementation lands.

ToxOracle is a London AI × Bio Hackathon project. It aims to identify drug candidates whose toxicity is underestimated by preclinical screening and predict potential human toxicity, starting with drug-induced liver injury (DILI).

The intended researcher workflow starts with a chemical structure (such as SMILES) and returns preclinical toxicity and human toxicity predictions, a discrepancy score, uncertainty, interpretable evidence, and recommendations for candidate prioritisation or further experiments such as 3D organoid or Liver-Chip validation. Structure-only inference is an important direction: researchers should not have to supply additional biological or human-exposure measurements to use the core workflow. Additional context may enrich predictions when available.

The broader concept pairs agentic early-stage drug candidate identification with a dedicated toxicity model to flag compounds that appear promising initially but could fail later in human studies.

## Sources and precedence

Follow explicit user instructions and corrections first, then this recorded context, then `refs/rough_actionable_plans.pdf`, then `refs/initial_sketch.pdf`. The initial sketch uses the older working name **LiverBridge**; the current name is **ToxOracle**. Reference documents describe proposals and illustrative outputs, not proof of implemented functionality or validated performance.

- `refs/rough_actionable_plans.pdf`: current narrative, architecture, schematic, and open decisions.
- `refs/initial_sketch.pdf`: original focused DILI concept, evaluation guidance, and illustrative demo.
- `refs/papers/`: relevant literature; consult the actual papers before making detailed claims about their methods, data, results, or suitability.
- Event: https://luma.com/87m4mw6b?tk=Cxss7a

## Corrected architecture

The user explicitly corrected two errors in the rough plan's schematic:

1. **“Risk–benefit agreement score” means preclinical–human toxicity discrepancy.** It is a typo, not an efficacy-versus-safety tradeoff metric. Any efficacy assessment is separate from this discrepancy.
2. **“Safety Filter (PPi)” means the independent privacy layer described in the text.** It is not a protein-interaction or compound-liability filter. This layer must keep subject-sensitive information local and prevent it from being transmitted to external providers. It must be independent of OpenAI, NVIDIA, and other third-party model functionality, regardless of its placement inside the workbench box in the drawing.

The intended system includes:

- A Rosalind Workbench interface/orchestration layer.
- NVIDIA BioNeMo AI agents and underlying BioNeMo models for relevant drug-discovery tasks.
- A dedicated toxicity model, with structure-only inference a key option.
- Comparison of preclinical and human toxicity predictions, with uncertainty and evidence-grounded interpretation.
- Prioritised candidates and recommendations for experimental validation.
- Optional post-MVP hallucination/reliability assessment; token efficiency is also an exploratory design consideration.

Exact model selection, training data, prediction targets, discrepancy definition, agent workflow, and interface remain open implementation decisions. The diagram is conceptual, not a fixed technical specification.

## Available hackathon resources

The user reports full access to:

- Codex (Astra).
- GPT-Rosalind / Rosalind Workbench.
- NVIDIA BioNeMo AI agents and all BioNeMo models.
- NVIDIA Brev GPUs.

Do not assume that lack of access to these resources constrains the project. Distinguish the team's access from the tools, credentials, and integrations actually connected in a particular session. Never store credentials in this file or the repository.

IMPORTANT: If you need API keys or any authorization details, ask instead of assuming it is not available.

The user's current understanding is that **Rosalind Workbench wraps NVIDIA BioNeMo AI agents, which in turn wrap BioNeMo models**. Treat this as a working integration hypothesis; verify the concrete interfaces when implementing it.

## Literature and data direction

Available papers:

- `refs/papers/Eltahir(2026).pdf`
- `refs/papers/Seal(2024).pdf`
- `refs/papers/Bergen(2025).pdf`
- `refs/papers/Ewart(2022).pdf`
- `refs/papers/Xu(2025).pdf`

The user identifies Eltahir (2026) and Seal (2024) as newer additions describing toxicity models that require only chemical structure as input. They motivate removing the need for additional user-supplied input data. This description is user-provided context; read the papers before choosing or reproducing their architectures. Distinguish inference inputs from training labels and auxiliary training data.

The rough plan proposes FDA-labelled DILI annotations (called “FDA DILI 2.0” in that document) and in vitro exposure/viability data. Confirm the exact dataset identity, label definitions, availability, and compound overlap before implementation. These are proposed data sources, not an assertion that data have already been acquired or models trained.

## Scientific and implementation principles

- Separate quantitative toxicity prediction from agent-generated explanation. Explanations must be grounded in model outputs and traceable evidence.
- Do not equate structure-only prediction with measured in vitro toxicity. Define the target and supervision of each prediction branch explicitly.
- Treat a difference between model scores as a discrepancy/discordance measure, not automatically as a validated translational gap. Define and evaluate the comparison against the available evidence.
- Keep all measurements, doses, and replicates for a compound in the same evaluation split. Evaluate generalisation to unseen compounds and consider scaffold splits where appropriate.
- Assess calibration, uncertainty, relevant classification metrics, and the value of experimental prioritisation. Clearly label illustrative numbers and demo thresholds.
- Distinguish implemented results, literature evidence, hypotheses, and future work. Do not repeat draft pitch claims as completed achievements without verification.
- Keep the hackathon MVP focused and demonstrable while preserving the broader architecture as context.
