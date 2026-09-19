# Dataset manifests

Record source URL/version, retrieval date, checksum, licence/access conditions, schema, identity mapping, exclusions and split provenance. Record artifact locations rather than committing full datasets. Commit compound-level manifests only if their contents may be shared.

`dilirank2_source.json` identifies the downloaded FDA workbook and its version-2 sheet. `dilirank2_acquisition_report.json` records curation counts, duplicate/conflict groups and artifact checksums. Recreate local datasets with the commands in `toxicity/README.md`; raw files, PubChem caches and processed CSVs remain ignored by Git. Split manifests are not created during acquisition.
