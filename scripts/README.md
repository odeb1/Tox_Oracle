# Repository utilities

Use for small repeatable bootstrap, data-fetch and artifact-management entry points. Keep scientific logic in its owning workstream. Scripts should document inputs, outputs and rerun behaviour.

`check.sh` is the single offline pre-push and CI entry point. It compiles the Python sources and runs the application, contract, demo and discovery test suites without external services or credentials.
