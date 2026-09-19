"""Static HTML rendering for a combined ToxOracle result."""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlsplit


def _text(value: Any) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _html(value: Any) -> str:
    return escape(_text(value), quote=True)


def _score(assessment: dict[str, Any]) -> str:
    score = assessment["risk_score"]
    if score is None:
        return "Unavailable"
    return f"{score:.3f} ({assessment['score_kind']})"


def _comparison_summary(comparison: dict[str, Any]) -> str:
    signed = comparison["signed_disagreement"]
    call = comparison["call_disagreement"]
    if signed is not None:
        return f"Signed disagreement: {signed:+.3f}"
    if call is not None:
        return f"Call disagreement: {call}"
    return "Unavailable"


def _discovery_metrics(result: dict[str, Any]) -> str:
    metrics = result["supplementary_metrics"]
    if not metrics:
        return "Unavailable"
    rendered = []
    for metric in metrics:
        unit = f" {metric['unit']}" if metric["unit"] else ""
        rendered.append(f"{metric['name']}={_text(metric['value'])}{unit}")
    return "; ".join(rendered)


def _safe_href(uri: str) -> str | None:
    parsed = urlsplit(uri)
    if parsed.scheme in {"http", "https"}:
        return uri
    if not parsed.scheme and not uri.startswith(("//", "/")):
        return uri
    return None


def _artifact_list(evidence: dict[str, Any]) -> str:
    artifacts = evidence["structure_artifacts"]
    if not artifacts:
        return "<p class=\"muted\">No structural artifacts supplied.</p>"
    items = []
    for artifact in artifacts:
        uri = artifact["uri"]
        href = _safe_href(uri)
        label = f"{artifact['artifact_id']} ({artifact['format']}, {artifact['origin']})"
        if href is None:
            rendered_uri = f"<code>{_html(uri)}</code>"
        else:
            rendered_uri = (
                f"<a href=\"{escape(href, quote=True)}\">{_html(label)}</a>"
            )
        items.append(
            f"<li>{rendered_uri} — checksum <code>{_html(artifact['checksum'])}</code></li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


def _fragment_list(evidence: dict[str, Any]) -> str:
    fragments = evidence["fragments"]
    if not fragments:
        return "<p class=\"muted\">No fragment attribution supplied.</p>"
    items = []
    for fragment in fragments:
        atoms = ", ".join(str(atom) for atom in fragment["atom_map_ids"])
        contribution = _text(fragment["contribution"])
        ambiguity = "ambiguous mapping" if fragment["mapping_ambiguous"] else "mapped"
        items.append(
            "<li>"
            f"<strong>{_html(fragment['fragment_id'])}</strong>: atoms {_html(atoms)}; "
            f"{_html(fragment['evidence_kind'])}; contribution {_html(contribution)}; "
            f"{_html(ambiguity)}; source <code>{_html(fragment['source_ref'])}</code>"
            "</li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


def _assessment_card(title: str, result: dict[str, Any]) -> str:
    assessment = result["assessment"]
    evidence = result["structural_evidence"]
    return f"""
      <section class="card">
        <h4>{_html(title)}</h4>
        <dl>
          <dt>Status</dt><dd>{_html(result['status'])}</dd>
          <dt>Endpoint</dt><dd>{_html(assessment['endpoint_id'])}</dd>
          <dt>Evidence</dt><dd>{_html(assessment['evidence_type'])}</dd>
          <dt>Call</dt><dd>{_html(assessment['call'])}</dd>
          <dt>Risk score</dt><dd>{_html(_score(assessment))}</dd>
          <dt>Calibration</dt><dd>{_html(assessment['calibration']['status'])}</dd>
          <dt>Applicability</dt><dd>{_html(assessment['applicability']['method'])}: {_html(assessment['applicability']['value'])}</dd>
          <dt>Attribution</dt><dd>{_html(evidence['attribution_status'])}</dd>
        </dl>
        <h5>Fragments</h5>
        {_fragment_list(evidence)}
        <h5>Artifacts</h5>
        {_artifact_list(evidence)}
      </section>
    """


def _messages(result: dict[str, Any]) -> str:
    messages = list(result["warnings"])
    if result["error"] is not None:
        messages.append(
            f"{result['error']['code']}: {result['error']['message']}"
        )
    if not messages:
        return "<p class=\"muted\">None reported.</p>"
    return "<ul>" + "".join(f"<li>{_html(message)}</li>" for message in messages) + "</ul>"


def _experiment(priority: dict[str, Any]) -> str:
    experiment = priority["proposed_experiment"]
    if experiment is None:
        return "<p class=\"muted\">No additional experiment proposed by this policy branch.</p>"
    readouts = "".join(f"<li>{_html(item)}</li>" for item in experiment["readouts"])
    return f"""
      <dl>
        <dt>Question</dt><dd>{_html(experiment['question'])}</dd>
        <dt>Assay/model</dt><dd>{_html(experiment['assay'])}</dd>
        <dt>Readouts</dt><dd><ul>{readouts}</ul></dd>
      </dl>
    """


def _summary_row(result: dict[str, Any]) -> str:
    discovery = result["discovery_result"]
    toxicity = result["toxicity_result"]
    comparison = result["comparison"]
    priority = result["priority"]
    experiment = priority["proposed_experiment"]
    next_experiment = experiment["assay"] if experiment else "None proposed"
    return f"""
      <tr>
        <td><a href="#{_html(result['compound_id'])}">{_html(result['compound_id'])}</a></td>
        <td>{_html(discovery['assessment']['call'])}</td>
        <td>{_html(toxicity['assessment']['call'])}</td>
        <td>{_html(comparison['comparison_mode'])}<br><span class="muted">{_html(_comparison_summary(comparison))}</span></td>
        <td>{_html(priority['toxicity_reliability'])}</td>
        <td>{_html(_discovery_metrics(discovery))}</td>
        <td>{_html(priority['original_priority'])}</td>
        <td>{_html(priority['revised_priority'])}</td>
        <td>{_html(next_experiment)}</td>
      </tr>
    """


def _candidate_detail(result: dict[str, Any]) -> str:
    comparison = result["comparison"]
    priority = result["priority"]
    limitations = priority["limitations"]
    limitations_html = (
        "<ul>" + "".join(f"<li>{_html(item)}</li>" for item in limitations) + "</ul>"
        if limitations
        else "<p class=\"muted\">None reported.</p>"
    )
    return f"""
      <article class="candidate" id="{_html(result['compound_id'])}">
        <h3>{_html(result['compound_id'])}</h3>
        <p><strong>Structure ID:</strong> <code>{_html(result['structure_id'])}</code></p>
        <p><strong>Canonical SMILES:</strong> <code>{_html(result['canonical_smiles'])}</code></p>
        <p><strong>Atom-mapped SMILES:</strong> <code>{_html(result['atom_mapped_smiles'])}</code></p>
        <div class="cards">
          {_assessment_card('Conventional/discovery assessment', result['discovery_result'])}
          {_assessment_card('Human DILI assessment', result['toxicity_result'])}
        </div>
        <section class="card">
          <h4>Comparison</h4>
          <p><strong>Mode:</strong> {_html(comparison['comparison_mode'])}</p>
          <p><strong>Result:</strong> {_html(_comparison_summary(comparison))}</p>
          <p>{_html(comparison['reason'])}</p>
          <p class="muted">Formula version: {_html(comparison['formula_version'])}</p>
        </section>
        <section class="card">
          <h4>Priority and next experiment</h4>
          <p><strong>Original:</strong> {_html(priority['original_priority'])} → <strong>Revised:</strong> {_html(priority['revised_priority'])}</p>
          <p>{_html(priority['recommendation'])}</p>
          {_experiment(priority)}
          <h5>Limitations</h5>
          {limitations_html}
        </section>
        <section class="card">
          <h4>Warnings and errors</h4>
          <h5>Discovery</h5>{_messages(result['discovery_result'])}
          <h5>Toxicity</h5>{_messages(result['toxicity_result'])}
        </section>
      </article>
    """


def render_combined_report(combined: dict[str, Any]) -> str:
    """Render a self-contained, offline HTML report from a combined record."""

    rows = "".join(_summary_row(result) for result in combined["results"])
    details = "".join(_candidate_detail(result) for result in combined["results"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ToxOracle combined report — {_html(combined['request_id'])}</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; line-height: 1.45; }}
    body {{ margin: 0 auto; max-width: 1500px; padding: 2rem; color: #17202a; background: #f6f8fa; }}
    h1, h2, h3, h4, h5 {{ line-height: 1.2; }}
    table {{ width: 100%; border-collapse: collapse; background: white; font-size: .9rem; }}
    th, td {{ border: 1px solid #d0d7de; padding: .6rem; text-align: left; vertical-align: top; }}
    th {{ background: #eaeef2; }}
    .table-wrap {{ overflow-x: auto; }}
    .candidate {{ margin-top: 2rem; border-top: 3px solid #0969da; padding-top: 1rem; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; }}
    .card {{ background: white; border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
    dl {{ display: grid; grid-template-columns: minmax(8rem, auto) 1fr; gap: .35rem 1rem; }}
    dt {{ font-weight: 650; }} dd {{ margin: 0; }}
    code {{ overflow-wrap: anywhere; }} .muted {{ color: #57606a; }}
    .notice {{ border-left: 4px solid #bf8700; background: #fff8c5; padding: .8rem 1rem; }}
  </style>
</head>
<body>
  <header>
    <h1>ToxOracle combined report</h1>
    <p><strong>Request:</strong> <code>{_html(combined['request_id'])}</code> · <strong>Schema:</strong> {_html(combined['schema_version'])} · <strong>Policy:</strong> {_html(combined['policy_version'])}</p>
    <p class="notice">Predictions and lower-concern calls do not establish safety. Unavailable assessments are shown explicitly and are never treated as negative results.</p>
  </header>
  <main>
    <h2>Candidate summary</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Candidate</th><th>Conventional call</th><th>Human DILI call</th><th>Comparison</th><th>Reliability</th><th>Discovery evidence</th><th>Original priority</th><th>Revised priority</th><th>Next experiment</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <h2>Candidate details</h2>
    {details}
  </main>
</body>
</html>
"""
