"""Visualizations of supplied scores, atom mappings and saved coordinates."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from .molecular_evidence import unique_features, molecule_svg

OXFORD_BLUE = "#002147"
INK = OXFORD_BLUE
AMBER = "#AB8952"
CORAL = "#B17B64"
MUTED = "#52667D"


def chart_layout(figure: go.Figure, *, height: int = 350) -> go.Figure:
    figure.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Arial, sans-serif", size=11, color=MUTED),
        margin=dict(l=12, r=35, t=20, b=25),
        hoverlabel=dict(bgcolor="#FFFEFB", bordercolor="#DCE3EC", font_size=12, font_color=INK),
        xaxis=dict(gridcolor="#E7ECF3", zeroline=False, automargin=True, tickfont=dict(size=10)),
        yaxis=dict(gridcolor="#E7ECF3", zeroline=False, automargin=True, tickfont=dict(size=11)),
    )
    return figure


def score_chart(results: list[dict[str, Any]], names: dict[str, str]) -> go.Figure:
    """Keep each candidate's own threshold; never normalize uncalibrated scores."""
    figure = go.Figure()
    for result in results:
        assessment = result["assessment"]
        if result["status"] != "ok" or assessment["risk_score"] is None:
            continue
        label = names.get(result["compound_id"], result["compound_id"])
        color = AMBER if assessment["call"] == "positive" else OXFORD_BLUE
        figure.add_trace(go.Scatter(
            x=[0, 1], y=[label, label], mode="lines", line=dict(color="#E4EAF2", width=3),
            hoverinfo="skip", showlegend=False,
        ))
        figure.add_trace(go.Scatter(
            x=[0, assessment["risk_score"]], y=[label, label], mode="lines",
            line=dict(color=color, width=3), hoverinfo="skip", showlegend=False,
        ))
        figure.add_trace(go.Scatter(
            x=[assessment["risk_score"]], y=[label], mode="markers+text",
            marker=dict(color=color, size=10, line=dict(color="#FFFEFB", width=2)),
            text=[f"  {assessment['risk_score']:.3f}"], textposition="middle right", textfont=dict(color=INK),
            customdata=[[result["compound_id"], assessment["score_kind"], assessment["call"]]],
            hovertemplate="%{y}<br>%{customdata[0]}<br>Score %{x:.3f}<br>%{customdata[1]}<br>Call: %{customdata[2]}<extra></extra>",
            showlegend=False,
        ))
        if assessment["threshold"] is not None:
            figure.add_trace(go.Scatter(
                x=[assessment["threshold"]], y=[label], mode="markers",
                marker=dict(symbol="line-ns", size=18, color="#5E7897", line=dict(width=1.5, color="#5E7897")),
                hovertemplate="Recorded threshold: %{x:.3f}<extra></extra>", showlegend=False,
            ))
    chart_layout(figure, height=max(290, 75 * len(results) + 80))
    figure.update_xaxes(range=[0, 1.07], title="Human DILI model score", fixedrange=True)
    figure.update_yaxes(autorange="reversed", fixedrange=True, automargin=True, showgrid=False)
    return figure


def feature_chart(groups: list[dict[str, Any]], selected: str | None = None) -> go.Figure:
    shown = [g for g in groups if g["contribution"] is not None][:10]
    figure = go.Figure(go.Bar(
        x=[g["contribution"] for g in shown],
        y=[g["source"].replace("Morgan_bit_", "Feature ") for g in shown], orientation="h",
        width=.55,
        marker=dict(cornerradius=3, color=[CORAL if g["contribution"] > 0 else OXFORD_BLUE for g in shown],
                    opacity=[1.0 if selected in (None, g["source"]) else .4 for g in shown]),
        customdata=[[len(g["atom_map_ids"]), "Ambiguous mapping" if g["ambiguous"] else "Mapped environment"] for g in shown],
        hovertemplate="%{y}<br>Contribution %{x:+.4f}<br>%{customdata[0]} mapped atoms<br>%{customdata[1]}<extra></extra>",
    ))
    chart_layout(figure, height=370)
    figure.update_xaxes(title="Recorded feature contribution", zeroline=True, zerolinecolor="#A7B7CB")
    figure.update_yaxes(autorange="reversed", showgrid=False)
    return figure


def pose_chart(sdf: str, pdb: str | None = None, *, show_protein: bool = True) -> go.Figure:
    """Display existing coordinates only; never compute interactions or new poses."""
    from rdkit import Chem
    mol = Chem.MolFromMolBlock(sdf.split("$$$$")[0], removeHs=True)
    if mol is None or mol.GetNumConformers() == 0 or not mol.GetConformer().Is3D():
        raise ValueError("The artifact does not contain a readable 3D pose.")
    points = mol.GetConformer().GetPositions()
    figure = go.Figure()
    if pdb and show_protein:
        backbone, labels = [], []
        previous_chain = None
        for line in pdb.splitlines():
            if line.startswith("ATOM  ") and line[12:16].strip() == "CA":
                point = [float(line[30:38]), float(line[38:46]), float(line[46:54])]
                chain = line[21:22]
                if backbone and (chain != previous_chain or sum((point[i] - backbone[-1][i])**2 for i in range(3)) > 25):
                    backbone.append([None] * 3)
                    labels.append("")
                backbone.append(point)
                labels.append(f"{line[17:20].strip()} {chain}:{line[22:26].strip()}")
                previous_chain = chain
        if backbone:
            figure.add_trace(go.Scatter3d(
                x=[p[0] for p in backbone], y=[p[1] for p in backbone], z=[p[2] for p in backbone],
                mode="lines+markers", line=dict(color="#8AA6C7", width=7),
                marker=dict(size=2, color="#8AA6C7"), text=labels,
                hovertemplate="%{text}<extra>Protein backbone</extra>", name="Protein Cα trace",
            ))
    bx, by, bz = [], [], []
    for bond in mol.GetBonds():
        start, end = points[bond.GetBeginAtomIdx()], points[bond.GetEndAtomIdx()]
        for output, index in ((bx, 0), (by, 1), (bz, 2)):
            output.extend([start[index], end[index], None])
    figure.add_trace(go.Scatter3d(x=bx, y=by, z=bz, mode="lines",
                                line=dict(color=AMBER, width=7), hoverinfo="skip", showlegend=False))
    palette = {"O": CORAL, "N": "#628BC3", "S": "#DAB35A", "Cl": OXFORD_BLUE, "F": OXFORD_BLUE}
    figure.add_trace(go.Scatter3d(
        x=points[:, 0], y=points[:, 1], z=points[:, 2], mode="markers",
        marker=dict(size=5, color=[palette.get(a.GetSymbol(), AMBER) for a in mol.GetAtoms()]),
        text=[f"{a.GetSymbol()} · pose atom {a.GetIdx() + 1}" for a in mol.GetAtoms()],
        hovertemplate="%{text}<extra>Predicted ligand</extra>", name="Predicted ligand",
    ))
    chart_layout(figure, height=540)
    axis = dict(visible=False, showbackground=False)
    figure.update_layout(scene=dict(xaxis=axis, yaxis=axis, zaxis=axis, aspectmode="data",
                                    bgcolor="#EDF1F6"), legend=dict(orientation="h", y=0),
                         margin=dict(l=0, r=0, t=0, b=0), uirevision="pose")
    return figure


def confusion_chart(matrix: list[list[int]]) -> go.Figure:
    figure = go.Figure(go.Heatmap(
        z=matrix, x=["Lower predicted concern", "Elevated predicted concern"],
        y=["No DILI concern", "Most / Less DILI concern"],
        text=matrix, texttemplate="%{text}", textfont=dict(size=26),
        colorscale=[[0, "#EDF2F8"], [1, OXFORD_BLUE]], showscale=False,
        hovertemplate="Reference: %{y}<br>Prediction: %{x}<br>%{z} compounds<extra></extra>",
    ))
    chart_layout(figure, height=330)
    figure.update_yaxes(autorange="reversed")
    return figure
