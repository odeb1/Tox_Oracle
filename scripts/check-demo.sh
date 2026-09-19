#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=app/src:. python3 -m unittest discover -s demo/streamlit_tests -p 'test_*.py' -v
