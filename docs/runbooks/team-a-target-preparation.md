# Team A target preparation

## Proposed discovery task

Status: **proposed, pending the team's and biologist's selection**. This is a
concrete preparation package for review, not a completed target freeze.

Use human PPARgamma agonism as the biological objective and docking pose
plausibility as the initial computational readout. [PDB 7AWC](https://www.rcsb.org/structure/7AWC)
contains one human PPARgamma ligand-binding domain (UniProt P37231), author chain
A, with rosiglitazone. It is an unmutated, 1.74 Å X-ray structure. The
[structural study of PPARgamma agonists](https://pubmed.ncbi.nlm.nih.gov/31611383/)
provides a common-target rationale for rosiglitazone, pioglitazone, and
troglitazone. These are historical compounds already present in the project's
model-ready dataset; their use is a retrospective illustration, and training
membership must be checked with Team B.

| Role | Compound | Shared ID |
| --- | --- | --- |
| Candidate | Rosiglitazone parent, sourced from its maleate entry | `LT00140` |
| Candidate | Pioglitazone parent, sourced from its hydrochloride entry | `LT00134` |
| Candidate | Troglitazone | `LT00168` |
| Separate experimental binding/reference control | S-rosiglitazone, CCD BRL, chain A residue 501 | `RCSB_7AWC_BRL_A501` |

The three candidates retain their existing `canonical_smiles`, `structure_id`,
and `standardization_version` from `data/processed/dilirank2_model_ready.csv`.
Preparation adds positive, unique atom maps in the parsed canonical-SMILES atom
order. It performs no new salt stripping, neutralisation, or stereoisomer
assignment. DILI labels are excluded from the request files.

All three source candidate structures contain unspecified stereocentres. The
[CCD BRL reference](https://www.rcsb.org/ligand/BRL) specifies the S enantiomer,
so it has a separate identity and control request. Its atom count and
stereochemistry were checked. The deposited ligand PDB retains its experimental
coordinates; it is not an idealised or generated pose. A source-validated
negative-binding control has not been selected.

## Prepared files

Small, versionable records live in `discovery/configs/targets/pparg-7awc/`:

- `target.proposed.json`: target identity, relative artifact paths, preparation
  choices, and checksums.
- `candidates.v2.json`: three shared candidate records.
- `reference-control.v2.json`: one separate structural reference record.
- `selection.proposed.json`: sources, candidate metadata, control roles,
  stereochemical uncertainties, and remaining decisions.

The downloaded source PDB and generated structures live under ignored
`artifacts/targets/pparg_7awc/`. The prepared receptor contains 2,169 atoms in
271 residues. Preparation selects chain A, resolves the equal-occupancy alternate
locations to A, and clears their alternate-location flags while preserving
coordinates, occupancies, serials, and residue numbers. It removes the bound
BRL, five glycerol molecules, and 195 waters from the receptor. The BRL coordinates
are saved separately with their internal connectivity records.

The source's missing residues A264–A269 and missing LEU A270 atoms CG/CD1/CD2
remain unresolved and are recorded in `preparation-report.json`. No protonation,
loop/side-chain repair, hydrogen addition, or minimisation is performed. The
cofactor-free preparation policy is specific to this proposal and should not
be reused for a metal/cofactor-dependent target.

## Reproduce preparation

Run from the repository root in a Python environment with RDKit 2025.9.2. The
`discovery[chemistry]` package extra declares that dependency. Schema tests use
the existing `tests/integration/requirements.txt` requirements.

The public source URL is `https://files.rcsb.org/download/7AWC.pdb`. The script
requires SHA-256
`f1678df596916a7da38842bd50002fbf61fc38a36e8adf43006940cb944f6b1f`
and fails if the downloaded source changes.

The tested preparation command was:

```bash
.venv/bin/python infra/prepare_pparg_demo.py \
  --source-pdb artifacts/targets/pparg_7awc/7AWC.pdb \
  --artifact-directory artifacts/targets/pparg_7awc/prepared \
  --config-directory discovery/configs/targets/pparg-7awc
```

Use new artifact and config directories for another run; existing preparations
are preserved. The script is entirely offline and makes no NVIDIA requests.

Validation command:

```bash
.venv/bin/python -m unittest discover -s discovery/tests -v
```

All 17 tests passed on 2026-09-19 with chemistry and schema dependencies
installed. The generated requests passed the shared v2 schema and atom-map
checks; source identities and file checksums were verified. Local verification
details are in `artifacts/targets/pparg_7awc/prepared/verification.json`.

## Decisions before the target-specific batch

The team and biologist still need to confirm this target, candidate/control set,
and preparation choices, including the missing residues/atoms and handling of
unspecified stereochemistry. Record the agreed choice in the selection record
and target manifest before describing the target as frozen. If a different
target was already selected, retain these files as a proposal and prepare the
selected structure separately.

Candidates remain unranked: pose confidence is pose reliability, not affinity,
efficacy, or a toxicity measurement. The conventional toxicity comparator is a
separate pending task.
