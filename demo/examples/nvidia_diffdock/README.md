# Cached NVIDIA docking example

These small public artifacts are copied from the verified live NVIDIA DiffDock run
`nvidia-bionemo-live-20260919-04`, completed on 19 September 2026. The SDF and prepared
PDB coordinates are unchanged; their original SHA-256 checksums are retained in
`run.json`. That file is a presentation summary of the original run metadata, with
portable filenames instead of local absolute paths. `verification.json` records
the checks performed on the original live run.

- Input structure: [RCSB PDB 8G43](https://www.rcsb.org/structure/8G43).
- Ligand: [RCSB chemical component ZU6](https://www.rcsb.org/ligand/ZU6).
- Example: [NVIDIA DiffDock](https://build.nvidia.com/mit/diffdock/deploy).
- Model: [NVIDIA DiffDock API reference](https://docs.api.nvidia.com/nim/reference/mit-diffdock-infer).

This is a public connectivity and pose-generation demonstration, separate from the
three DILI compounds. Pose confidence is not affinity, efficacy, or toxicity. The
Streamlit viewer displays the supplied coordinates and a protein Cα backbone trace;
it does not calculate or claim molecular contacts. Cached playback makes no API call.
