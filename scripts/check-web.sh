#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=app/src:discovery/src:. python3 -m pytest app/web_tests privacy/tests -q
node --check app/src/toxoracle_app/web_static/workspace.js
