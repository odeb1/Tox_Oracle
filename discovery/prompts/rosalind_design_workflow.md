# Advanced ABL1 design and screening

Use this instruction for the advanced branch, not the frozen hackathon demo.

1. Read `docs/runbooks/target-only-generation.md`. Use public inputs or files already
   filtered locally, reviewed and approved. Never paste sensitive raw content into
   hosted tools. The separate privacy gateway is not an automatic interceptor.
2. Interpret intent and write a JSON request matching
   `contracts/design-request-v1.schema.json`:
   - `screen`: supplied candidates, with molecular structures.
   - `generate_screen`: target-only generation, or supplied structures used as seeds.
   File presence alone does not distinguish the two. Ask for clarification when
   "find candidates" could mean retrieving known molecules, or seed/candidate intent
   is ambiguous. Missing candidates in screen mode are an input error.
3. Only human ABL1 (`ABL1` / `human_abl1_2hyy_A`) is prepared. Do not silently map
   mutants, other species or other targets to this manifest. Explain that default
   target-only generation uses documented imatinib fragments, not direct protein
   conditioning. Generation does not establish novelty, synthesis or efficacy.
4. Run `./scripts/toxoracle-design preflight --request REQUEST --output-dir NEW_DIR`.
   Add `--cache-dir artifacts/cache` when reuse is acceptable. Preflight checks local
   setup; cache integrity and service entitlement are checked during execution.
   Describe the resolved mode and budget; do not request redundant confirmation for
   an explicit request to generate/screen public molecules. Ask for missing access
   through the available secure channel. Never put credentials in files or logs.
5. Run `./scripts/toxoracle-design run` with the same arguments. The command enforces
   reference gating, generation limits, chemical validation, deterministic selection,
   and saving discovery priorities before local DILI inference. Do not bypass these
   steps by inventing structures/scores in the conversation or changing rules based
   on results. The reference is outside the generated shortlist.
6. Inspect `workflow.json`, `design-report.json`, `design-report.html`, and
   `summary.txt`. Explain the discovery shortlist and how the same candidates'
   follow-up changes after DILI. Zero changes is a valid outcome; never regenerate
   to manufacture an attractive story. No automatic substitution of held candidates.
7. Disclose live versus cached stages, failures and rejections, seed provenance,
   fitting/selection membership, chemical coverage, unassessed synthesis feasibility
   and unvalidated generalization to generated chemistry. Lower DILI is not safe
   human exposure. QED, binding scores, pose confidence and DILI have different
   meanings; never subtract or average them into a score.
8. Exit 0 means complete; 2 means partial; 1 means setup, contract or integrity
   failure. Use `--resume` only with the same inputs/configuration/model/source.
   It does not repeat completed or ambiguous external calls. Never delete failure
   records or present a cached run as live. Do not silently retry an interrupted
   or failed hosted request.

Final desktop acceptance requires running both modes from actual Rosalind prompts,
opening their reports, and confirming the explanation against saved artifacts.
A terminal test does not establish that integration gate.
