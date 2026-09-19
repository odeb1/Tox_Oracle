# Cross-team integration tests

Joint ownership. Cover both contract producers, ID-preserving joins, failures, cached playback and recommendation rules as implementation lands. Ordinary checks must not require live APIs or GPU access.

## Contract checks

Install the test dependency and run the current offline contract checks from the repository root:

```bash
python3 -m pip install -r tests/integration/requirements.txt
python3 -m unittest discover -s tests/integration -p 'test_*.py'
```

The tests validate both schemas, the initial interface-only fixtures, request/response identity preservation and important failure constraints. The `not_run` fixtures contain no model results and do not indicate that either scientific workflow has executed.
