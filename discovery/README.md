# Discovery workflow — Team A

The primary demo now uses **BioNeMo Boltz-2** for a frozen human ABL1 panel. It
returns binder likelihood, predicted affinity and complex structures, then the
application adds Team B's DILI assessment. See
[the current runbook](../docs/runbooks/rosalind-screening.md). Discovery v3 does not
require a second toxicity predictor. The DiffDock implementation below remains a
legacy supplementary-evidence adapter.

Own Rosalind orchestration, BioNeMo adapters, target preparation and structured discovery evidence. Runtime code is in `src/`, agent instructions in `prompts/`, and public target configuration is in `configs/targets/`.

The first adapter is an offline-testable client for NVIDIA's DiffDock NIM service. It preserves compound IDs, saves returned pose artifacts, and labels pose confidence correctly as pose reliability—not affinity, efficacy, or toxicity. See [the Team A DiffDock runbook](../docs/runbooks/team-a-diffdock.md) for setup, live execution requirements and known integration boundaries.

The current adapter produces `stream: discovery_evidence`, not the final shared `stream: discovery` toxicity-assessment envelope. Team A must first freeze the target and separately select a conventional liver-toxicity comparator; no docking metric may fill that role.
