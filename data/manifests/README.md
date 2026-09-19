# Dataset manifests

Record source URL/version, retrieval date, checksum, licence/access conditions, schema, identity mapping, exclusions and split provenance. Record artifact locations rather than committing full datasets. Commit compound-level manifests only if their contents may be shared.

`dilirank2_source.json` records the FDA workbook identity and version-2 sheet. `dilirank2_acquisition_report.json` records curation counts, duplicate groups, version hashes and checksums for the three shared CSVs in `data/processed/`. See `data/README.md` for the snapshot's labels, curation rules and sharing exception. Raw downloads and PubChem caches remain local. No split manifest has been created.
