# Data storage policy

Commit only small, permitted manifests and curated evidence. raw/, cache/ and processed/ are local ignored directories. cache/pubchem/ holds reusable source API responses for offline curation and auditing. Recreate these directories during ingestion as needed. Sensitive subject-level data belong outside the repository entirely. Source licenses and permissions are separate from the repository LICENSE.
