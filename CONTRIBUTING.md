# Contributing

Read [BUILD_PLAN.md](BUILD_PLAN.md) and the [repository map](docs/repository.md) first. Team A owns discovery and presentation; Team B owns toxicity and the optional local privacy boundary. Contracts, triage rules and integration checks are shared.

## Working together

Use short-lived branches such as `discovery/tool-adapter`, `toxicity/dili-baseline`, or `shared/prediction-contract`. Keep pull requests focused, with a concrete description and the checks actually run. Coordinate shared-interface changes with the other team's integration contact before merging.

Add dependency manifests and lockfiles alongside each independently runnable component when its stack is chosen. Document tested setup and execution commands. Do not duplicate scientific logic in notebooks, scripts and application handlers.

## Files and artifacts

- Commit source, configuration without secrets, small fixtures, provenance and reviewed reports.
- Keep datasets in ignored local data directories, except the explicitly shared DILIrank 2.0 CSV snapshot documented in `data/README.md`. Keep generated weights/outputs under `artifacts/` and sensitive subject-level data outside the repository entirely.
- A `.gitignore` is an accident-prevention aid, not access control; it does not protect files already tracked by Git.
- Preserve source licences and attribution for third-party datasets, papers and models. The root licence does not override their terms.

## Validation

Test meaningful behaviour as it is implemented: input validation, compound grouping, preprocessing consistency, contract compatibility and error handling. Keep ordinary tests offline; mark external-service and GPU tests explicitly. Model changes need appropriate held-out evaluation in addition to software checks.

The repository now has an offline integration runtime and automated checks in `.github/workflows/ci.yml`. Run `./scripts/check.sh` before pushing changes to the shared contracts, application, demo tooling or discovery adapter. Live external-service, GPU, RDKit pose-mapping and model-evaluation checks remain outside the default CI job and must be documented separately when run.
