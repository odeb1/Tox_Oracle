# Shared DILIrank 2.0 dataset

The curated snapshot is checked into `main` so both teams can use it immediately. It was acquired on 19 September 2026 from [FDA DILIrank 2.0](https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-rank-dilirank-20-dataset), with structures resolved through [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest).

| File | Contents |
| --- | --- |
| [processed/dilirank2_model_ready.csv](processed/dilirank2_model_ready.csv) | 802 unique eligible standardised structures: 508 positive and 294 negative labels |
| [processed/dilirank2_enriched.csv](processed/dilirank2_enriched.csv) | All 1,336 FDA entries, original metadata, structure candidates, selected structures, provenance and exclusions |
| [processed/dilirank2_review.csv](processed/dilirank2_review.csv) | 232 unresolved or unsupported entries requiring review before possible inclusion |

Use `dilirank2_model_ready.csv` for the initial modelling dataset. `compound_id` is the representative FDA LTKBID, `canonical_smiles` is the standardised parent structure, and `dili_label` is **1 for Most/Less DILI concern** and **0 for No DILI concern**. Ambiguous labels are blank in the master table and excluded from the modelling subset. All 354 original Ambiguous entries remain in the master table.

CSV encoding is UTF-8. Cells such as `source_compound_ids`, `source_original_categories`, `candidate_structures` and `synonyms` contain JSON arrays. `source_compound_ids` preserves all records contributing to a deduplicated structure. Source columns such as severity and label section must not be used as predictive features.

## Curation and limitations

- 1,213 source entries have a unique accepted PubChem synonym match; 1,104 pass the initial structural standardisation rules. Automated matches are database identity evidence, not manual verification of every molecule.
- Policy `dilirank_parent_v1` uses RDKit 2025.09.6. Source SMILES/CIDs/InChIKeys are retained separately from standardised structures. Named elemental salt forms and retrieved SMILES/InChIKey consistency are checked.
- Only explicitly recognised disconnected counterions/solvents are removed. Repeated identical parents in stoichiometric salts collapse to one parent; distinct remaining components are excluded for review. Covalent modifications, stereochemistry and isotopes are preserved. Functional groups are normalised and charges neutralised where possible; tautomers are not canonicalised.
- The initial subset requires carbon, allows H/B/C/N/O/F/Si/P/S/Se/Cl/Br/I in the retained structure, and limits structures to 100 heavy atoms and 1,500 Da. Structures with at least 10 peptide-backbone matches are excluded. These are MVP scope rules, not universal small-molecule definitions.
- Deduplication uses canonical isomeric parent SMILES. Conflicting positive/negative labels would exclude the group; none were observed in this snapshot. Ambiguous membership is retained without overriding a non-ambiguous label.
- `structure_key` is the parent InChIKey. `structure_id` hashes the policy version and canonical isomeric SMILES. `connectivity_group` is an additional hint for grouping related chemical forms before evaluation splitting; it does not imply identical labels across stereoisomers.
- The source snapshot is unchanged; Team B now supplies a separate frozen split manifest and evaluated baseline (see `toxicity/README.md`). These drug-level labels are not patient-level event probabilities.

## Provenance and integrity

[Source manifest](manifests/dilirank2_source.json) records the FDA workbook checksum, source sheet, download URL and access notes. [Acquisition report](manifests/dilirank2_acquisition_report.json) records class coverage, exclusions, duplicate groups, pipeline/dependency hashes and SHA-256 checksums for all three CSVs.

Source datasets and PubChem contributions retain their own rights and attribution requirements; the repository licence does not relicense them. FDA asks downloaders to notify its support address; no notification was sent by the ingestion pipeline.

## Storage policy

These three public-data CSVs are an explicit exception to the repository's local-dataset policy. Other processed files, raw downloads, `cache/pubchem/` responses, legacy intermediate files and private data remain ignored. Keep credentials and sensitive subject-level data outside the shared dataset. Future snapshot updates must refresh the provenance report and checksums together with the CSVs.
