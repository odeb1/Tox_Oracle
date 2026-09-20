#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
export PYTHONPATH="$project_root/app/src:$project_root/discovery/src:$project_root${PYTHONPATH:+:$PYTHONPATH}"

python3 - <<'PY'
"""Run offline generation checks with the required scientific runtime present."""
import importlib
import sys
import unittest

for module in ("rdkit.Chem", "numpy", "sklearn", "joblib", "shap", "jsonschema"):
    importlib.import_module(module)

suite = unittest.TestSuite()
for directory, pattern in (
    ("app/tests", "test_design.py"),
    ("discovery/tests", "test_generation.py"),
):
    tests = unittest.TestLoader().discover(directory, pattern=pattern)
    if not tests.countTestCases():
        raise SystemExit(f"No generation tests found in {directory}/{pattern}")
    suite.addTests(tests)

result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped:
    print("Scientific generation checks must run without skipped tests.", file=sys.stderr)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
PY
