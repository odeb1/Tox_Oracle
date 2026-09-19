# Team B demo assets

- `privacy_synthetic.json`: entirely synthetic identifiers and a software-flow molecule.
  Load it in the local privacy UI, scan, review, approve and run local DILI inference.
- `dili_request.json`: three public, held-out drug structures with v2 identities.
- `dili_response.json`: actual baseline outputs, including score, applicability,
  training membership and atom-mapped fragment evidence.

These examples do not establish a preclinical miss or individual clinical risk.
The public held-out cases are selected after evaluation by a fixed illustrative rule,
not chosen to claim unbiased performance. Report aggregate metrics separately.

See `docs/runbooks/team-b-local-mvp.md` for the complete walkthrough and recovery path.
