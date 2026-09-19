"""Visualizations of supplied scores, atom mappings and saved coordinates."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

TEAL = "#587E66"
INK = "#344B3B"
AMBER = "#AB8952"
CORAL = "#B17B64"
MUTED = "#7B8774"


def chart_layout(figure: go.Figure, *, height: int = 350) -> go.Figure:
    figure.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Arial, sans-serif", size=11, color=MUTED),
        margin=dict(l=12, r=35, t=20, b=25),
        hoverlabel=dict(bgcolor="#FFFEFB", bordercolor="#DDE3D3", font_size=12, font_color=INK),
        xaxis=dict(gridcolor="#ECEEE5", zeroline=False, automargin=True, tickfont=dict(size=10)),
        yaxis=dict(gridcolor="#ECEEE5", zeroline=False, automargin=True, tickfont=dict(size=11)),
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
        color = AMBER if assessment["call"] == "positive" else TEAL
        figure.add_trace(go.Scatter(
            x=[0, 1], y=[label, label], mode="lines", line=dict(color="#E9ECE2", width=3),
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
                marker=dict(symbol="line-ns", size=18, color="#6E8066", line=dict(width=1.5, color="#6E8066")),
                hovertemplate="Recorded threshold: %{x:.3f}<extra></extra>", showlegend=False,
            ))
    chart_layout(figure, height=max(290, 75 * len(results) + 80))
    figure.update_xaxes(range=[0, 1.07], title="Human DILI model score", fixedrange=True)
    figure.update_yaxes(autorange="reversed", fixedrange=True, automargin=True, showgrid=False)
    return figure


def unique_features(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One bar per feature, retaining every environment for ambiguous hashed bits."""
    groups: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        source = fragment["source_ref"]
        if source not in groups:
            groups[source] = {"source": source, "contribution": fragment["contribution"],
                              "fragments": [], "atom_map_ids": set(), "ambiguous": False}
        group = groups[source]
        group["fragments"].append(fragment["fragment_id"])
        group["atom_map_ids"].update(fragment["atom_map_ids"])
        group["ambiguous"] |= fragment["mapping_ambiguous"]
        # Inconsistent supplied contributions cannot be presented as one feature score.
        if group["contribution"] != fragment["contribution"]:
            group["contribution"] = None
    return sorted(groups.values(), key=lambda g: abs(g["contribution"] or 0), reverse=True)


def feature_chart(groups: list[dict[str, Any]], selected: str | None = None) -> go.Figure:
    shown = [g for g in groups if g["contribution"] is not None][:10]
    figure = go.Figure(go.Bar(
        x=[g["contribution"] for g in shown],
        y=[g["source"].replace("Morgan_bit_", "Feature ") for g in shown], orientation="h",
        width=.55,
        marker=dict(cornerradius=3, color=[CORAL if g["contribution"] > 0 else TEAL for g in shown],
                    opacity=[1.0 if selected in (None, g["source"]) else .4 for g in shown]),
        customdata=[[len(g["atom_map_ids"]), "Ambiguous mapping" if g["ambiguous"] else "Mapped environment"] for g in shown],
        hovertemplate="%{y}<br>Contribution %{x:+.4f}<br>%{customdata[0]} mapped atoms<br>%{customdata[1]}<extra></extra>",
    ))
    chart_layout(figure, height=370)
    figure.update_xaxes(title="Recorded feature contribution", zeroline=True, zerolinecolor="#ABB9AE")
    figure.update_yaxes(autorange="reversed", showgrid=False)
    return figure


def molecule_svg(mapped_smiles: str, atom_ids: list[int] | None = None,
                 *, positive: bool = True, labels: bool = False) -> str:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(mapped_smiles)
    if mol is None:
        raise ValueError("The supplied molecular structure cannot be drawn.")
    requested = set(atom_ids or [])
    available = {a.GetAtomMapNum() for a in mol.GetAtoms()}
    if not requested.issubset(available):
        raise ValueError("The selected evidence references atom maps absent from this molecule.")
    indices = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomMapNum() in requested]
    for atom in mol.GetAtoms():
        if labels:
            atom.SetProp("atomNote", str(atom.GetAtomMapNum()))
        atom.SetAtomMapNum(0)
    drawer = rdMolDraw2D.MolDraw2DSVG(760, 380)
    options = drawer.drawOptions()
    options.clearBackground = False
    options.padding = .12
    options.bondLineWidth = 2
    options.addStereoAnnotation = True
    color = (.93, .68, .60) if positive else (.56, .79, .70)
    bonds = [b.GetIdx() for b in mol.GetBonds()
             if b.GetBeginAtomIdx() in indices and b.GetEndAtomIdx() in indices]
    rdMolDraw2D.PrepareAndDrawMolecule(
        drawer, mol, highlightAtoms=indices, highlightBonds=bonds,
        highlightAtomColors={i: color for i in indices},
        highlightBondColors={i: color for i in bonds},
    )
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


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
                mode="lines+markers", line=dict(color="#85AEA2", width=7),
                marker=dict(size=2, color="#85AEA2"), text=labels,
                hovertemplate="%{text}<extra>Protein backbone</extra>", name="Protein Cα trace",
            ))
    bx, by, bz = [], [], []
    for bond in mol.GetBonds():
        start, end = points[bond.GetBeginAtomIdx()], points[bond.GetEndAtomIdx()]
        for output, index in ((bx, 0), (by, 1), (bz, 2)):
            output.extend([start[index], end[index], None])
    figure.add_trace(go.Scatter3d(x=bx, y=by, z=bz, mode="lines",
                                line=dict(color=AMBER, width=7), hoverinfo="skip", showlegend=False))
    palette = {"O": CORAL, "N": "#628BC3", "S": "#DAB35A", "Cl": TEAL, "F": TEAL}
    figure.add_trace(go.Scatter3d(
        x=points[:, 0], y=points[:, 1], z=points[:, 2], mode="markers",
        marker=dict(size=5, color=[palette.get(a.GetSymbol(), AMBER) for a in mol.GetAtoms()]),
        text=[f"{a.GetSymbol()} · pose atom {a.GetIdx() + 1}" for a in mol.GetAtoms()],
        hovertemplate="%{text}<extra>Predicted ligand</extra>", name="Predicted ligand",
    ))
    chart_layout(figure, height=540)
    axis = dict(visible=False, showbackground=False)
    figure.update_layout(scene=dict(xaxis=axis, yaxis=axis, zaxis=axis, aspectmode="data",
                                    bgcolor="#F3F4EB"), legend=dict(orientation="h", y=0),
                         margin=dict(l=0, r=0, t=0, b=0), uirevision="pose")
    return figure


def confusion_chart(matrix: list[list[int]]) -> go.Figure:
    figure = go.Figure(go.Heatmap(
        z=matrix, x=["Lower predicted concern", "Elevated predicted concern"],
        y=["No DILI concern", "Most / Less DILI concern"],
        text=matrix, texttemplate="%{text}", textfont=dict(size=26),
        colorscale=[[0, "#EEF0E4"], [1, TEAL]], showscale=False,
        hovertemplate="Reference: %{y}<br>Prediction: %{x}<br>%{z} compounds<extra></extra>",
    ))
    chart_layout(figure, height=330)
    figure.update_yaxes(autorange="reversed")
    return figure
