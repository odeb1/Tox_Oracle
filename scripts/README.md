# Repository utilities

Use for small repeatable bootstrap, data-fetch and artifact-management entry points. Keep scientific logic in its owning workstream. Scripts should document inputs, outputs and rerun behaviour.

`check.sh` is the general offline pre-push and CI entry point. It compiles the Python sources and runs the application, contract, demo and discovery test suites without external services or credentials.

`bash scripts/check-generation.sh` runs the target-only generation and supplied-panel
workflow tests with the scientific runtime installed. It requires the dependencies
in `toxicity/requirements-model.lock` and fails on missing dependencies, missing
tests or any skipped tests. The dedicated `generation-science` CI job runs this
check with Python 3.12; hosted responses and DILI outputs are synthetic, so it needs
no credentials, model weights or external inference calls.
