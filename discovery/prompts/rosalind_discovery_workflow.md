# Rosalind discovery workflow — v0.1

Use the prepared target manifest and the canonical candidate list without changing
compound IDs, structure IDs, standardisation versions, or atom-map IDs.

1. Confirm the target manifest identifies the protein, PDB entry, chain,
   preparation version, intended biological action, and reference ligand.
2. Invoke the configured BioNeMo/DiffDock adapter with the prepared PDB and each
   candidate's canonical SMILES. Save raw service output and pose artifacts.
3. Report pose confidence only as the reliability of a predicted pose. Never call
   it affinity, efficacy, a safety score, or a toxicity prediction.
4. Return structured discovery evidence: tool/model provenance, input and output
   artifacts, confidence metrics, and any actual atom-to-residue interactions.
   If contacts or atom-map preservation have not been computed, say so explicitly.
5. Obtain Team A's conventional liver-toxicity assessment from its separately
   chosen comparator. Do not substitute docking confidence for that assessment.
6. Request the Team B DILI assessment through the shared v2 contract. Join only on
   the unchanged compound and structure IDs. If either assessment is unavailable,
   report why rather than treating it as lower risk.
7. Generate narrative solely from the structured records. Describe fragment
   highlights and predicted docking contacts as evidence for hypotheses, not proof
   of mechanism or causality.

The researcher-facing output must identify which uncertainty an experiment would
resolve. It must not claim patient-level safety, clinical efficacy, or confirmed
causal toxicity.
