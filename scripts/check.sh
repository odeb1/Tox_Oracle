#!/usr/bin/env bash
set -euo pipefail

python3 -m compileall -q app/src discovery/src demo
PYTHONPATH=app/src:. python3 -m unittest discover -s app/tests -p 'test_*.py' -v
python3 -m unittest discover -s tests/integration -p 'test_*.py' -v
PYTHONPATH=app/src:. python3 -m unittest discover -s demo/tests -p 'test_*.py' -v
python3 -m unittest discover -s discovery/tests -p 'test_*.py' -v
