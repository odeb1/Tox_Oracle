# Discovery source

Implement tool adapters and orchestration here. Preserve compound IDs and keep vendor response parsing separate from prioritisation logic.

`toxoracle_discovery.diffdock` is the first adapter. It uses the documented NVIDIA NIM DiffDock request fields, accepts an injectable HTTP transport for offline tests, and serialises only discovery evidence. The conventional toxicity comparator remains a separate Team A integration and must be selected before this evidence is promoted to the shared toxicity-assessment contract.
