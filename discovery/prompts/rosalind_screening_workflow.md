# ToxOracle: discovery-first ABL1 screening

Use this workflow for the frozen retrospective ABL1 demonstration. The researcher
interacts with Rosalind; execute the reproducible pipeline through the local shell.

1. Set the working directory to `/Users/scho/Tox_Oracle`. Read
   `docs/runbooks/rosalind-screening.md` and `demo/examples/abl1_experiment.json`.
2. Use only the frozen public request `demo/examples/abl1_request.json` and target
   `discovery/configs/targets/abl1.json` for this demonstration. Do not change
   candidates, identities, thresholds or the ranking rule based on DILI outputs.
3. Choose a new output directory beneath `artifacts/runs/`, including a timestamp.
   Run `./scripts/toxoracle-screen preflight` with `--request`, `--target` and
   `--output-dir`. For cached execution also pass `--cache-dir artifacts/cache/boltz2`
   to preflight; a complete verified cache does not require an API key. If needed
   credentials or permissions are missing, request setup through
   the supported permission flow. Never put keys in prompts, files or command text.
4. Run `./scripts/toxoracle-screen run` with the same arguments. Add
   `--cache-dir artifacts/cache/boltz2` only when cached execution is acceptable,
   and disclose cache reuse. This command verifies the reference, freezes discovery
   priorities, then runs the existing local DILI predictor and writes the report.
5. Read `run.json`, `summary.txt` and `combined.json`, and show `combined.html`.
   Exit 2 means partial results, not a successful complete experiment. Retain every
   failed or unranked record and its reason.
6. Explain the discovery-only shortlist and each follow-up change using source
   records. Affinity, binder likelihood, structural confidence, DILI probability
   and training similarity have different meanings; never subtract them.
7. Show training membership and validation warnings. Present structural fragments
   as model-attribution evidence, not causal mechanisms. Boltz-2 pose atom mapping
   is unavailable; do not invent ligand atom-to-residue contacts.
8. State that this is a retrospective, provisional workflow illustration. DILI
   flags concern; it does not predict patient-level or dose-specific outcomes,
   establish safety, or demonstrate a preclinical miss. Do not promise a particular
   ranking change before examining the actual report.

No model retraining or installation should occur implicitly during screening.
Sensitive inputs must first pass the separate local privacy gateway and approval.
