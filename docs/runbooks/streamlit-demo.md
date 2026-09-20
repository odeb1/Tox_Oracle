# ToxOracle Streamlit demo

## Start the demo

Use Python 3.11 or newer. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Open http://127.0.0.1:8501. If the virtual environment already exists, omit the
first command. The dependency lock records the tested Streamlit, Plotly and RDKit
versions. The app uses local assets and saved results; the presentation needs no
NVIDIA/OpenAI credentials, model weights, retraining or remote scientific calls.

For Streamlit Community Cloud, use branch `main`, entry point `streamlit_app.py`,
and Python 3.11. The root `packages.txt` supplies `libxrender1`, which RDKit needs
to draw the molecular structures on the Linux host.

## Presentation sequence

1. **Target-only discovery** is the opening page. Introduce the prepared human
   ABL1 target and imatinib-derived fragment, then follow the recorded
   **40 proposals → 29 acceptable unique molecules → 20 screened candidates**.
   Switch **Evidence shown** from **Discovery only** to **With human DILI**:
   the same two shortlisted candidates are held for targeted liver validation,
   with no automatic replacements or combined binding/toxicity score. Open the
   candidate journey, example input requests and source evidence tabs. The page
   uses `evaluation/reports/generation_workflow_v1.json`; individual generated
   structures and scores are not included. The **Active study** selector is
   disabled here because this recorded study is independent of imported cases.
2. **Overview:** introduce the selected study and show the candidate scores. The
   dot shows the saved score; the vertical tick marks its recorded threshold. Select a table row
   and choose **Inspect**, or use **Explore a candidate**.
3. **Candidate explorer:** choose Amoxicillin for a compact molecular view. Select
   a fingerprint feature and optionally turn on atom-map IDs. Inspect the model
   call, reference category, applicability and training membership.
4. **Decision & next step:** for a complete case, show discovery-only versus
   revised priority, comparison eligibility and the proposed experiment. The
   built-in DILI-only study explicitly describes the missing discovery stream.
5. **Discovery lab:** rotate the saved NVIDIA 8G43/ZU6 pose. This is an independent
   public service example, not docking evidence for the three DILI candidates.
   When a complete study is active, this page instead shows its own discovery
   metrics, structural artifacts, recorded interactions and comparator assessment.
6. **Model & provenance:** show the held-out aggregate evaluation, confusion
   matrix, provenance and limits. The three illustrated cases were selected after
   evaluation; their performance is not a substitute for the full test set.
7. Return to **Overview** and download the HTML report, candidate CSV or source
   JSON. The report opens without Streamlit and includes the underlying evidence.

The sidebar **Presenter notes** switch adds a short talk track to each main view.
The dashboard never claims a live Rosalind call: it presents recorded science.
The public DILI examples and saved docking pose are separate studies, not
candidate-level evidence for the generated ABL1 panel.

## Load the team's final cases

Use the same case directory as `demo/run_case.py`, with a ready `manifest.json`
conforming to `demo/case.schema.json`, `result_class: real`, and matching v2 request,
discovery and toxicity envelopes. Case filenames come from the manifest.
The importer accepts these v2 case bundles; it does not import v3 generation run
directories. The target-only opening page reads its bundled aggregate summary.

```text
my-study/
  manifest.json
  request.json
  discovery-response.json
  toxicity-response.json
  policy.json
  display.json
  poses/
```

Place it directly under `demo/examples/` or `artifacts/runs/` to make it appear in
the sidebar. Alternatively, point to the existing output folder:

```bash
TOXORACLE_DEMO_CASE=/path/to/my-study .venv/bin/python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Or ZIP the directory and open it in **Load a study**. ZIPs are parsed in memory,
without extraction, and limited to 100 files and 20 MB uncompressed. Imported
studies stay in the browser session's server-side Streamlit state and are not
written to disk or shared with external scientific services. Upload only public
or approved molecular outputs; use the existing local privacy gateway for raw
sensitive inputs before creating the case.

`policy.json` is optional; when absent, the existing `configs/triage-v1.json` is
used. Its provisional status is retained. The app does not choose or tune
applicability thresholds. A case originally run live is always labelled as a
cached replay when loaded from files.

Optional `display.json` adds readable names without changing compound identity:

```json
{
  "title": "Our discovery study",
  "compound_names": {
    "candidate_001": "Candidate A"
  }
}
```

Include artifacts at the relative paths recorded in their response and retain
their SHA-256 checksums. Local reads stay inside the case folder; artifacts outside
it are not served. External HTTP(S) artifacts can be opened explicitly through a
link. The viewer does not fetch arbitrary URLs on load. No interface fixture is
accepted as a scientific study.

## What the visualizations mean

- DILI scores, thresholds and calls come directly from the supplied assessment.
  Missing or failed assessments are unavailable, never zero risk.
- The target-only page preserves the frozen discovery shortlist when revealing
  the recorded DILI decision. Positive DILI calls indicate predicted concern,
  not established toxicity in humans; exclusion from model fitting does not make
  generated candidates a labelled evaluation set.
- The molecular drawing uses the supplied atom-mapped molecule. Every matching
  environment of an ambiguous fingerprint bit is highlighted. The bar chart
  counts each source feature once rather than summing duplicate environments.
- Fragment contributions use the source's attribution scale. The baseline's
  TreeSHAP values explain its raw forest output, not its calibrated DILI score.
- 3D docking uses the saved SDF coordinates and a Cα backbone trace. Pose
  confidence remains pose reliability; no affinity or toxicity is inferred.
- Complete-case comparisons and recommendations are generated by the existing
  `combine_responses` implementation. Scientific code, schemas and policy are
  unchanged.

## Verification

```bash
PATH="$PWD/.venv/bin:$PATH" ./scripts/check.sh
PATH="$PWD/.venv/bin:$PATH" bash scripts/check-demo.sh
```

The ordinary checks cover case import, identity mismatch rejection, artifact
containment/checksums, export escaping and reconciliation of the generation counts.
The Streamlit suite visits every page, checks the target-only landing page and
evidence switch, follows its link to the separate public study, switches candidates,
selects atom highlights and verifies the saved 3D pose.
Both run offline. The dedicated CI job installs the locked demo dependencies.

For browser review, check the target-only page at desktop and narrow widths, switch
the DILI evidence view, open its tabs and follow **Explore DILI examples**. Check
the overview, change the candidate and highlighted feature, rotate the docking
pose, open provenance and download a report. Leave the browser tab on
**Target-only discovery** for the presentation.
