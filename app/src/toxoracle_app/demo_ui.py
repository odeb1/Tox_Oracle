"""Streamlit research demo. All displayed scientific results come from saved records."""

from __future__ import annotations

import json
import os
from base64 import b64encode
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st

from .demo_data import (
    ROOT, Study, artifact_bytes, candidate_rows, export_csv, export_html,
    load_baseline, load_case_directory, load_case_zip, read_json,
)
from .demo_visuals import (
    confusion_chart, feature_chart, molecule_svg, pose_chart, score_chart, unique_features,
)

PAGES = ["Overview", "Candidate explorer", "Discovery lab", "Model & provenance", "Load a study"]
CALL_LABELS = {"positive": "Elevated predicted concern", "negative": "Lower predicted concern", "unavailable": "Unavailable"}


def text(value: object) -> str:
    return escape(str(value), quote=True)


def svg_image(svg: str, description: str, *, class_name: str = "") -> str:
    """Render generated SVG as an image: st.html removes inline SVG elements."""
    encoded = b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img class="{text(class_name)}" src="data:image/svg+xml;base64,{encoded}" alt="{text(description)}">'


def pretty(value: object) -> str:
    return "Unavailable" if value is None else str(value).replace("_", " ").capitalize()


def number(value: object, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def navigate(page: str) -> None:
    st.session_state["page"] = page


def hero(kicker: str, title: str, description: str, *, accent: str = "") -> None:
    ending = f'<br><span>{text(accent)}</span>' if accent else ""
    st.html(f'<div class="hero"><div class="eyebrow">{text(kicker)}</div><h1>{text(title)}{ending}</h1><p>{text(description)}</p></div>')


def study_hero(study: Study) -> None:
    specimen = ""
    # A labelled molecule from the active study, never decorative invented science.
    result = next((r for r in study.results if r["compound_id"] == "LT00507"), study.results[0])
    try:
        svg = molecule_svg(result["structural_evidence"]["atom_mapped_smiles"])
        specimen = (
            '<div class="specimen"><div class="eyebrow">A molecule in this study</div>'
            f'<div class="specimen-art">{svg_image(svg, study.name(result["compound_id"]) + " molecular structure")}</div><div class="specimen-label">'
            f'<strong>{text(study.name(result["compound_id"]))}</strong>'
            f'<span>{text(result["compound_id"])}</span></div></div>'
        )
    except (ImportError, ValueError, RuntimeError):
        pass
    st.html(
        '<div class="hero hero-study"><div><div class="eyebrow">Candidate intelligence</div>'
        '<h1>The evidence.<br><span>A clearer perspective.</span></h1>'
        '<p>Explore your candidates and read each liver-toxicity result in context, '
        'from molecular features to its source evidence.</p>'
        f'</div>{specimen}</div>'
    )


def section(title: str, detail: str = "") -> None:
    st.html(f'<div class="section-title"><h2>{text(title)}</h2><span>{text(detail)}</span></div>')


def note(message: str) -> None:
    st.html(f'<div class="note">{text(message)}</div>')


def pair(label: str, value: object) -> None:
    st.html(f'<div class="detail-pair"><span>{text(label)}</span><span>{text(value if value is not None else "Unavailable")}</span></div>')


def plot(figure: object, key: str) -> None:
    st.plotly_chart(figure, width="stretch", theme=None, key=key,
                    config={"displaylogo": False, "scrollZoom": False, "responsive": True})


def presenter(message: str) -> None:
    if st.session_state.get("presenter_notes"):
        with st.expander("Presenter notes", expanded=True):
            st.write(message)


def downloads(study: Study) -> None:
    left, middle, right = st.columns(3)
    stem = "toxoracle-study"
    left.download_button("Download report", export_html(study), f"{stem}.html", "text/html",
                         width="stretch", icon=":material/download:", key="report_download")
    middle.download_button("Candidate table", export_csv(study), f"{stem}.csv", "text/csv",
                           width="stretch", icon=":material/table_view:", key="csv_download")
    payload = {"study": study.metadata, "request": study.request,
               "toxicity": study.toxicity, "discovery": study.discovery,
               "combined": study.combined, "policy": study.policy}
    right.download_button("Source evidence", json.dumps(payload, indent=2, allow_nan=False),
                          f"{stem}.json", "application/json", width="stretch",
                          icon=":material/data_object:", key="evidence_download")


def overview(study: Study) -> None:
    study_hero(study)
    results = study.results
    assessed = [r for r in results if r["status"] == "ok"]
    elevated = sum(r["assessment"]["call"] == "positive" for r in assessed)
    attributed = sum(r["structural_evidence"]["attribution_status"] == "available" for r in assessed)
    with st.container(key="overview_metrics"):
        columns = st.columns(4)
        for col, label, value in zip(columns,
                                    ["CANDIDATES", "ASSESSED", "ELEVATED DILI CALLS", "FRAGMENT EVIDENCE"],
                                    [len(results), len(assessed), elevated, attributed]):
            col.metric(label, value)
    st.write("")
    left, right = st.columns([1.9, 1], gap="large")
    with left, st.container(key="landscape_panel"):
        section("Candidate landscape", "Human DILI assessment")
        st.html('<div class="chart-legend"><span><i class="legend-dot"></i>Recorded score</span><span><i class="legend-tick"></i>Decision threshold</span></div>')
        if any(r["assessment"]["risk_score"] is not None for r in assessed):
            plot(score_chart(results, study.names), "overview_scores")
            st.caption("Each marker is a saved model result. Hover to inspect the score, call and calibration type.")
        else:
            st.info("This study has no completed numeric scores. Assessment status remains visible below.")
    with right:
        st.html(f'<div class="insight"><div class="eyebrow">A closer look</div><div class="number">{elevated:02d}<small>/ {len(results):02d}</small></div><h3>Candidates with an elevated call</h3><p>Explore their molecular features and applicability before interpreting the predicted concern.</p></div>')
        with st.container(key="study_details"):
            section("Study context")
            pair("Execution", "Cached results")
            pair("Discovery comparison", "Available in this case" if study.combined else "Separate study not attached")
            pair("Training membership", pretty(study.metadata.get("training_membership", "unknown")))
        st.button("Explore a candidate", icon=":material/arrow_forward:", type="primary",
                  width="stretch", on_click=navigate, args=("Candidate explorer",))
    section("Candidate review", "Select a row to inspect its evidence")
    frame = pd.DataFrame(candidate_rows(study))
    event = st.dataframe(frame, hide_index=True, width="stretch", key="candidate_table",
                         on_select="rerun", selection_mode="single-row",
                         column_config={
                             "DILI score": st.column_config.NumberColumn(format="%.3f"),
                             "Training similarity": st.column_config.NumberColumn(format="%.3f"),
                         })
    if event.selection.rows and event.selection.rows[0] < len(frame):
        chosen = frame.iloc[event.selection.rows[0]]["Compound ID"]
        st.session_state["candidate"] = chosen
        st.button(f"Inspect {study.name(chosen)}", on_click=navigate, args=("Candidate explorer",), key="inspect_selected")
    if study.combined:
        section("How the decision changes")
        for record in study.combined["results"]:
            with st.expander(study.name(record["compound_id"])):
                priority_panel(record)
    else:
        note("The built-in study presents saved human DILI results. Load a complete study to see conventional toxicity comparisons and discovery-to-toxicity priority changes.")
    section("Keep the complete picture", "Reports & source evidence")
    downloads(study)
    presenter("Start with the research question, then show the candidate scores. Open one candidate to connect its prediction to the underlying molecule. In a complete study, show the original and revised priorities before discussing the next experiment.")


def priority_panel(record: dict) -> None:
    priority, comparison = record["priority"], record["comparison"]
    st.html('<div class="priority-flow"><div><small>Discovery only</small><strong>' + text(pretty(priority["original_priority"])) + '</strong></div><span>→</span><div><small>With toxicity evidence</small><strong>' + text(pretty(priority["revised_priority"])) + '</strong></div></div>')
    st.write(priority["recommendation"])
    pair("Policy", f"{priority['policy_version']} · {priority['policy_status']}")
    pair("Comparison", pretty(comparison["comparison_mode"]))
    st.caption(comparison["reason"])
    if comparison["signed_disagreement"] is not None:
        st.metric("Signed disagreement", f"{comparison['signed_disagreement']:+.3f}")
    elif comparison["call_disagreement"] is not None:
        pair("Assessment calls", "Disagree" if comparison["call_disagreement"] else "Agree")
    experiment = priority["proposed_experiment"]
    if experiment:
        st.markdown("**Next experiment**")
        st.write(experiment["question"])
        pair("Assay", experiment["assay"])
        st.write("Readouts: " + ", ".join(experiment["readouts"]))
    for limitation in priority["limitations"]:
        st.caption(limitation)


def candidate_explorer(study: Study) -> None:
    hero("Molecular evidence", "The detail behind the signal.",
         "Move from a candidate’s prediction to its molecular features, source records and next decision.")
    ids = [r["compound_id"] for r in study.results]
    if st.session_state.get("candidate") not in ids:
        st.session_state["candidate"] = ids[0]
    chosen = st.selectbox("Candidate", ids, format_func=lambda value: f"{study.name(value)} · {value}", key="candidate")
    result = next(r for r in study.results if r["compound_id"] == chosen)
    assessment, evidence = result["assessment"], result["structural_evidence"]
    complete = result["status"] == "ok"
    top = st.columns(3)
    top[0].metric("HUMAN DILI SCORE", number(assessment["risk_score"] if complete else None))
    top[1].metric("DECISION THRESHOLD", number(assessment["threshold"]))
    top[2].metric("TRAINING SIMILARITY", number(assessment["applicability"]["value"] if complete else None))
    call = assessment["call"] if complete else "unavailable"
    note(f"{CALL_LABELS[call]} · {pretty(assessment['score_kind'])} · {pretty(result['provenance']['training_membership'])} from model training")
    tabs = st.tabs(["Molecule & features", "Assessment & context", "Decision & next step", "Source record"])
    with tabs[0]:
        groups = unique_features(evidence["fragments"]) if complete else []
        left, right = st.columns([1.2, 1], gap="large")
        with left:
            section("Structure explorer")
            options = ["All atoms"] + [g["source"] for g in groups]
            selected = st.selectbox("Highlight a model feature", options, key=f"feature_{chosen}",
                                    format_func=lambda item: "Unhighlighted molecule" if item == "All atoms" else item.replace("Morgan_bit_", "Fingerprint feature "))
            feature = next((g for g in groups if g["source"] == selected), None)
            labels = st.toggle("Show atom-map IDs", key=f"atom_labels_{chosen}")
            try:
                svg = molecule_svg(evidence["atom_mapped_smiles"], sorted(feature["atom_map_ids"]) if feature else [],
                                   positive=not feature or (feature["contribution"] or 0) >= 0, labels=labels)
                st.html('<div class="molecule">' + svg_image(svg, study.name(chosen) + " molecular structure") + '</div>')
            except (ImportError, ValueError, RuntimeError) as error:
                st.info(f"Molecule view unavailable: {error}")
            if feature:
                st.caption(f"Source: {feature['source']} · atom maps: {', '.join(map(str, sorted(feature['atom_map_ids'])))}")
                if feature["ambiguous"]:
                    note("This fingerprint feature maps to multiple environments. All supplied matching atoms are highlighted; they do not identify a unique causal fragment.")
            st.caption("Coral: positive contribution. Blue: negative contribution. Highlights describe model attribution, not causal toxicity.")
        with right, st.container(key="feature_panel"):
            section("What influenced the model", "Top recorded features")
            if groups:
                plot(feature_chart(groups, feature["source"] if feature else None), "feature_chart")
                st.caption(f"Attribution target: {evidence['attribution_target']} · scale: {evidence['attribution_scale']}")
                st.caption("Repeated environments share a feature contribution and are counted once in this chart. The displayed features do not reconstruct the calibrated DILI score.")
            else:
                st.info("No fragment attribution is supplied for this assessment.")
        with st.expander("Molecular identity"):
            st.code(evidence["canonical_smiles"], language=None)
            pair("Structure ID", result["structure_id"])
            pair("Standardization", evidence["standardization_version"])
            st.code(evidence["atom_mapped_smiles"], language=None)
    with tabs[1]:
        left, right = st.columns(2, gap="large")
        with left, st.container(border=True):
            section("Human DILI assessment")
            for label, value in (("Status", result["status"]), ("Endpoint", assessment["endpoint_id"]),
                                 ("Call", CALL_LABELS[call]), ("Score type", pretty(assessment["score_kind"])),
                                 ("Evidence", pretty(assessment["evidence_type"])),
                                 ("Positive definition", assessment["positive_definition"]),
                                 ("Calibration", pretty(assessment["calibration"]["status"])),
                                 ("Uncertainty", pretty(assessment["uncertainty"]["method"]))):
                pair(label, value)
        with right, st.container(border=True):
            section("How to read this result")
            st.write("The score describes the model’s drug-level DILI endpoint. Training similarity measures structural proximity to training compounds; it is not a confidence interval.")
            pair("Applicability method", assessment["applicability"]["method"])
            pair("Training membership", pretty(result["provenance"]["training_membership"]))
            if chosen in study.references:
                pair("Recorded DILIrank category", study.references[chosen])
                st.caption("Reference annotation from the shared DILIrank dataset. A model prediction can disagree with this annotation.")
            for warning in result["warnings"]:
                st.caption(warning)
            if result["error"]:
                st.error(result["error"]["message"])
    with tabs[2]:
        record = study.joined(chosen)
        if record:
            priority_panel(record)
        else:
            section("Bring both evidence streams together")
            st.write("This saved case contains the human DILI assessment. Add the matching discovery response and triage policy to display the computed before-and-after priority and recommended experiment.")
            st.button("Load a complete study", on_click=navigate, args=("Load a study",), key="load_from_candidate")
    with tabs[3]:
        pair("Method", result["provenance"]["method_id"])
        pair("Data version", result["provenance"]["data_version"])
        st.json(result, expanded=False)
        st.download_button("Download candidate evidence", json.dumps(result, indent=2), f"{chosen}-evidence.json", "application/json")
    presenter("Select a fingerprint feature to highlight every mapped environment. Explain the attribution scale, show training similarity, then compare the model call with the recorded reference annotation. For complete cases, finish on the next experiment.")


def structure_artifacts(study: Study, evidence: dict) -> None:
    artifacts = evidence["structure_artifacts"]
    if not artifacts:
        st.info("No structural files are attached to this assessment.")
    for index, artifact in enumerate(artifacts):
        with st.expander(f"{artifact['artifact_id']} · {artifact['format']}"):
            pair("Origin", artifact["origin"])
            pair("Checksum", artifact["checksum"])
            try:
                content = artifact_bytes(study, artifact["uri"], artifact["checksum"])
                st.download_button("Download artifact", content, Path(artifact["uri"]).name,
                                   key=f"artifact_{index}")
                if artifact["format"].lower() in ("sdf", "mol"):
                    plot(pose_chart(content.decode()), f"artifact_plot_{index}")
            except (OSError, ValueError, ImportError) as error:
                st.caption(str(error))
                if urlsplit(artifact["uri"]).scheme in ("http", "https"):
                    st.link_button("Open source artifact", artifact["uri"])
    if evidence["interactions"]:
        section("Recorded interactions")
        st.dataframe(evidence["interactions"], width="stretch", hide_index=True)


def discovery_lab(study: Study) -> None:
    hero("Structural discovery", "A new view of the molecule.",
         "Inspect saved docking coordinates and the evidence returned by the scientific tools.")
    if study.discovery:
        ids = [r["compound_id"] for r in study.discovery["results"]]
        chosen = st.selectbox("Discovery candidate", ids, format_func=study.name, key="discovery_candidate")
        result = next(r for r in study.discovery["results"] if r["compound_id"] == chosen)
        with st.container(border=True):
            section("Discovery evidence", pretty(result["status"]))
            if result["supplementary_metrics"]:
                st.dataframe(result["supplementary_metrics"], hide_index=True, width="stretch")
            for warning in result["warnings"]:
                st.caption(warning)
            structure_artifacts(study, result["structural_evidence"])
        with st.expander("Conventional toxicity assessment"):
            st.json(result["assessment"])
        presenter("Show the discovery metric with its recorded meaning, then open the conventional toxicity assessment. Inspect saved poses and recorded contacts before returning to the candidate decision.")
        return

    folder = ROOT / "demo/examples/nvidia_diffdock"
    if not (folder / "run.json").is_file():
        st.info("Load a complete study to inspect its discovery artifacts.")
        return
    run = read_json(folder / "run.json")
    docking = Study(title="NVIDIA public docking example", request=study.request,
                    toxicity=study.toxicity, metadata={}, source_dir=folder)
    note("Independent public NVIDIA example: PDB 8G43 / ligand ZU6. This saved docking run is separate from the DILI candidates in the selected study.")
    left, right = st.columns([1.8, 1], gap="large")
    sdf = None
    with left, st.container(key="discovery_panel"):
        section("Predicted ligand pose", "Drag to rotate · use toolbar to zoom")
        show = st.toggle("Show protein backbone", value=True)
        try:
            sdf = artifact_bytes(docking, run["pose_file"], run["pose_sha256"])
            pdb = artifact_bytes(docking, run["protein_file"], run["protein_sha256"])
            plot(pose_chart(sdf.decode(), pdb.decode(), show_protein=show), "nvidia_pose")
        except (OSError, ValueError, ImportError) as error:
            st.error(f"Could not display the saved pose: {error}")
        st.caption("Protein shown as a Cα backbone trace. Coordinates come directly from the saved run; no contacts or affinities are inferred by this viewer.")
    with right:
        st.metric("POSE CONFIDENCE", f"{run['pose_confidence']:.5f}")
        st.metric("RETURNED POSES", run["pose_count"])
        with st.container(border=True):
            section("Run details")
            pair("Model", "NVIDIA DiffDock")
            pair("Run status", run["status"])
            pair("HTTP response", run["http_status"])
            pair("Run date", run["finished_at"][:10])
            pair("Model version", "Not reported by service")
        note("Pose confidence describes predicted pose reliability. It is not binding affinity, efficacy or a toxicity score.")
        if sdf is not None:
            st.download_button("Download predicted pose", sdf, "ZU6-diffdock-pose.sdf", "chemical/x-mdl-sdfile", width="stretch")
    with st.expander("Run provenance and verification"):
        st.json(run)
    presenter("Rotate the real saved NVIDIA pose. Name the protein and ligand, and distinguish this public service demonstration from the selected DILI study. Keep pose confidence separate from toxicity and binding affinity.")


def provenance(study: Study) -> None:
    hero("Methods & provenance", "Every finding has a source.",
         "Review the study record, training membership and evaluation context before interpreting a result.")
    section("Active study")
    left, right = st.columns(2, gap="large")
    with left, st.container(key="evaluation_panel"):
        pair("Study", study.title)
        pair("Request", study.request["request_id"])
        pair("Execution", "Cached replay")
        pair("Original execution", study.metadata.get("original_execution_mode", "cached"))
        pair("Result class", study.metadata.get("result_class", "real"))
        pair("Model methods", ", ".join(sorted({r["provenance"]["method_id"] for r in study.results})))
    with right, st.container(border=True):
        section("Interpretation notes")
        for limitation in study.metadata.get("limitations", []):
            st.write(limitation)
    with st.expander("Study manifest and input checksums"):
        st.json(study.metadata)
    expected = read_json(ROOT / "evaluation/reports/baseline_test.json")
    data_version = expected["data_sha256"]
    matching = all(r["provenance"]["method_id"] == "toxoracle_dili_rf_v1" and
                   r["provenance"]["data_version"] == data_version for r in study.results)
    section("DILI baseline evaluation", "Repository reference model")
    if not matching:
        note("These evaluation metrics describe the repository’s baseline model. The active study reports a different method or data version; these metrics must not be attributed to it.")
    metrics = expected["random_forest"]
    cols = st.columns(4)
    for col, label, value in zip(cols, ["TEST COMPOUNDS", "AUROC", "AVERAGE PRECISION", "BRIER SCORE"],
                                [str(metrics["n"]), number(metrics["auroc"]), number(metrics["average_precision"]), number(metrics["brier"])]):
        col.metric(label, value)
    left, right = st.columns([1.3, 1], gap="large")
    with left, st.container(border=True):
        section("Test-set predictions", "Reference labels × model calls")
        plot(confusion_chart(metrics["confusion_matrix"]), "confusion_matrix")
    with right, st.container(border=True):
        section("Model context")
        selection = read_json(ROOT / "evaluation/reports/baseline_selection.json")
        pair("Model", "Random forest + calibration")
        pair("Fingerprint", selection["fingerprint"])
        pair("Split", pretty(selection["split_kind"]))
        pair("Training / validation / test", " / ".join(str(selection["counts"][k]["n"]) for k in ("train", "validation", "test")))
        pair("Sensitivity", number(metrics["sensitivity"]))
        pair("Specificity", number(metrics["specificity"]))
        for limitation in expected["limitations"]:
            st.caption(limitation)
    with st.expander("Evaluation source and model checksum"):
        st.json(expected)
        st.download_button("Download evaluation", json.dumps(expected, indent=2), "baseline-test.json", "application/json")
    presenter("The three demonstration compounds are examples, not an independent performance estimate. Use these aggregate held-out metrics to discuss performance, including the false positives and false negatives.")


def load_study_page(study: Study) -> None:
    hero("Study library", "Your study. The full picture.",
         "Load your saved discovery and toxicity outputs to explore the full comparison and decision workflow.")
    left, right = st.columns([1.4, 1], gap="large")
    with left, st.container(border=True):
        section("Open a study bundle", "ZIP · up to 20 MB")
        upload = st.file_uploader("Choose a complete study", type=["zip"], key="study_upload",
                                   help="Only upload public or approved molecular outputs. Files remain in this Streamlit session.")
        if st.button("Open study", type="primary", disabled=upload is None, width="stretch"):
            try:
                loaded = load_case_zip(upload.getvalue())
                st.session_state["pending_study"] = loaded
                st.rerun()
            except (ValueError, OSError, KeyError, TypeError) as error:
                st.error(f"The study could not be opened: {error}")
        st.caption("The app validates candidate identity, both evidence streams and the triage policy before displaying a combined decision.")
    with right, st.container(border=True):
        section("Inside the bundle")
        st.code("study/\n  manifest.json\n  request.json\n  discovery-response.json\n  toxicity-response.json\n  policy.json       (optional)\n  display.json      (optional)\n  poses/           (optional)", language=None)
        st.caption("Use the repository’s existing demo-case format. A saved live run is labelled as a cached replay here.")
    with st.expander("Study preparation details"):
        st.write("The manifest must be ready with result_class set to real, and reference the three response/request filenames. policy.json overrides the repository’s default triage policy. Without it, the current provisional policy is used and shown as provisional.")
        st.write("display.json can supply a study title and a compound_names mapping. Include pose files with relative paths and their recorded SHA-256 checksums to make them available in the structure viewer.")
        st.json({"title": "My discovery study", "compound_names": {"candidate_001": "Candidate A"}})
        st.write("Local complete case folders under demo/examples and artifacts/runs appear in the study selector. An additional folder can be configured using TOXORACLE_DEMO_CASE.")
    section("Current study")
    downloads(study)


def main() -> None:
    st.set_page_config(page_title="ToxOracle · Evidence to decision", page_icon="🧬", layout="wide")
    st.html(Path(__file__).with_name("demo.css"))
    if "pending_study" in st.session_state:
        st.session_state["uploaded_study"] = st.session_state.pop("pending_study")
        st.session_state["study_picker"] = "Uploaded study"
        st.session_state["page"] = "Overview"
        st.session_state.pop("candidate", None)
    options: dict[str, Path | None] = {"Public DILI study": None}
    for parent in (ROOT / "demo/examples", ROOT / "artifacts/runs"):
        for manifest in sorted(parent.glob("*/manifest.json")):
            options[f"Case · {manifest.parent.name}"] = manifest.parent
    if os.environ.get("TOXORACLE_DEMO_CASE"):
        options["Configured study"] = Path(os.environ["TOXORACLE_DEMO_CASE"])
    if "uploaded_study" in st.session_state:
        options["Uploaded study"] = None
    with st.sidebar:
        symbol = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" fill="none"><ellipse cx="20" cy="20" rx="17" ry="8" transform="rotate(-45 20 20)" stroke="#b9d6f2" stroke-width="1.2"/><ellipse cx="20" cy="20" rx="17" ry="8" transform="rotate(45 20 20)" stroke="#87a8ce" stroke-width="1.2"/><circle cx="20" cy="20" r="3" fill="#dce8f5"/><circle cx="8" cy="8" r="2.2" fill="#dce8f5"/></svg>'
        st.html('<div class="brand">' + svg_image(symbol, "", class_name="brand-symbol") + '<span class="brand-name">ToxOracle</span></div><div class="brand-sub">EVIDENCE TO DECISION</div>')
        st.divider()
        st.html('<div class="rail-heading">Your workspace</div>')
        default = "Configured study" if "Configured study" in options else next((k for k in options if k.startswith("Case ·")), "Public DILI study")
        if st.session_state.get("study_picker") not in options:
            st.session_state["study_picker"] = default
        selected = st.selectbox("Active study", list(options), key="study_picker")
        st.html('<div class="rail-heading">Explore the evidence</div>')
        st.radio("Navigate", PAGES, key="page", label_visibility="collapsed", width="stretch")
        st.divider()
        st.toggle("Presenter notes", key="presenter_notes")
        st.html('<div class="sidebar-note"><div class="eyebrow">Science, within reach.</div><p>A connected view of your candidates and the evidence behind them.</p></div><div class="rail-footer">London AI × Bio Hackathon<br>Research workspace · 2026</div>')
    try:
        if selected == "Uploaded study":
            study = st.session_state["uploaded_study"]
        elif options[selected] is not None:
            study = load_case_directory(options[selected])
        else:
            study = load_baseline()
    except (ValueError, OSError, KeyError, TypeError) as error:
        st.error(f"This study could not be loaded: {error}")
        st.info("Select the public DILI study to open the bundled demo.")
        st.stop()
    st.html(f'<div class="topline"><div class="breadcrumb"><span>Research workspace</span><span>/</span><strong>{text(study.title)}</strong></div><span class="pill"><i class="status-dot"></i>Cached scientific results</span></div>')
    routes = dict(zip(PAGES, [overview, candidate_explorer, discovery_lab, provenance, load_study_page]))
    routes[st.session_state["page"]](study)
    st.html('<div class="footer"><span class="footer-brand">ToxOracle <span style="font-family:sans-serif;font-size:10px; margin-left:9px">/ Traceable science</span></span><span>Research prioritisation · Drug-level concern does not establish clinical safety.</span></div>')
