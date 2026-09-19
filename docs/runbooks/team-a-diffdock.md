# Team A DiffDock runbook

## Purpose and scope

This is the first Team A discovery-tool adapter. It targets NVIDIA's public
DiffDock NIM endpoint, documented as a molecular-docking service accepting a
protein PDB plus SMILES/SDF/Mol2 ligand input. It returns pose-confidence values
and pose artifacts. Pose confidence is a predicted-pose reliability measure, not
affinity, efficacy, or liver-toxicity evidence.

The adapter intentionally emits `stream: discovery_evidence`; it does **not**
manufacture the required conventional liver-toxicity assessment. Team A must
choose and document that comparator before wrapping both outputs in the shared
v2 `stream: discovery` envelope.

Official source: [NVIDIA DiffDock NIM reference](https://docs.api.nvidia.com/nim/reference/mit-diffdock-infer).

## Verified public smoke test

On 2026-09-19, the public 8G43/ZU6 example completed against the hosted route
`https://health.api.nvidia.com/v1/biology/mit/diffdock` using
`NVIDIA_BIONEMO_API_KEY`. NVIDIA returned HTTP 200, vendor status `success`, one
ligand pose, and pose confidence `0.004754878580570221`. The request ID was
`e5518f23-54c4-47cd-871b-ff539991d567`; the served model version was not reported.
This verifies authenticated inference and artifact export. The example is not
the project's frozen therapeutic target, a toxicity assessment, or an accuracy
benchmark.

From the repository root, with the key already in the environment:

```bash
python3 infra/diffdock_smoke.py \
  --api-key-env NVIDIA_BIONEMO_API_KEY \
  --output-directory artifacts/runs/nvidia-bionemo-smoke
```

Use a new output directory for each run; the script preserves earlier attempts.
`--api-key-env` takes an environment-variable name, never a credential value.
It defaults to `NVIDIA_API_KEY` for compatibility, so select the BioNeMo variable
explicitly when the two contain different keys.

The successful local run is in
`artifacts/runs/nvidia-bionemo-live-20260919-04/`. It contains `run.json`, the
request and raw response, source and prepared inputs, `evidence.json`, the pose
SDF, and `verification.json`. RDKit 2025.09.2 verified one pose with 21 heavy
atoms, finite 3D coordinates, and the same structure and stereochemistry as the
reference ligand. All eight referenced file checksums matched. Atom-map
identity, contacts, and biological activity were not assessed.

The hosted response uses `ligand_positions` and `position_confidence`; the
adapter supports these alongside `docked_ligand` and `pose_confidence`. At the
time of this check, the API reference's
`/v1/molecular-docking/diffdock/generate` route returned HTTP 404 on the public
host. The successful run above uses the verified hosted route instead.

## Inputs to freeze before a live run

1. Copy `discovery/configs/targets/target-manifest.template.json` to a
   target-specific, non-template JSON file. Record target identity, PDB entry,
   chain, intended action, reference ligand, preparation choices, and the SHA-256
   checksum of the prepared PDB. Relative `protein_pdb_path` values are resolved
   from the target manifest's own directory.
2. Prepare the canonical candidate request using the shared v2 fields:
   `compound_id`, `canonical_smiles`, `atom_mapped_smiles`, `structure_id`, and
   `standardization_version`.
3. Set `NVIDIA_API_KEY` in the execution environment. Do not add it to a file,
   notebook, command history, artifact, or Git.
4. Confirm the enabled Workbench connector or use the command below as the
   documented file-handoff path. Record the actual model/service version from its
   response or service metadata alongside the resulting artifacts.

## Setup and offline check

The HTTP client and smoke script use only the Python standard library. Optional
shared-structure validation uses RDKit. From `discovery/`:

```bash
python3 -m unittest discover -s tests -v
```

## Live invocation

Run only after the target file is fully prepared and the API key is available:

```bash
PYTHONPATH=src python3 -m toxoracle_discovery.cli \
  --request path/to/candidates.v2.json \
  --target configs/targets/your_target.json \
  --output artifacts/runs/diffdock/your_run.json \
  --artifact-directory artifacts/runs/diffdock/poses
```

The response JSON preserves candidate IDs and adds model provenance, pose
confidence metrics, and locally saved vendor pose artifacts. It leaves
atom-mapping verification and protein-contact extraction unavailable until those
steps are explicitly implemented. A failed or invalid candidate emits a visible
status and error; it is never treated as a low-risk result.

## Pending Team A decisions

- The biologist must nominate the target, prepared PDB/chain/cofactors, reference
  ligand, and biological action.
- Team A and the biologist must select the conventional liver-toxicity comparator
  and its endpoint/conditions.
- The Workbench tool inventory and custom-tool connection mechanism still require
  an authenticated in-session check. The successful hosted API smoke test above
  does not establish Workbench integration.
