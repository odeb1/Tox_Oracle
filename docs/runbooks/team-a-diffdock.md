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

The component uses only the Python standard library. From `discovery/`:

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
  an authenticated in-session check. This environment has neither an NVIDIA API
  key nor an enabled Workbench browser surface, so no live call is claimed.
