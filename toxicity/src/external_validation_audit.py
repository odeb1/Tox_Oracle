"""Offline provenance/overlap audit; never fits, predicts or approves a cohort.

Source files remain unchanged. Unknown labels and missing structures stay unknown.
Only the optional DILImap reader needs h5py. Downloads are a separate explicit step.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

import openpyxl
from rdkit import rdBase
from rdkit.Chem.Scaffolds import MurckoScaffold

from toxicity.src.bionemo_experiment import ROOT, digest, load_frozen_inputs, save_json
from toxicity.src.ingest_dilirank import POLICY, normalized_name, standardize

SOURCES = {
    "dilist.xlsx": {
        "url": "https://www.fda.gov/media/160597/download?attachment=",
        "sha256": "4331ee9d16ae7641488161e4dc2c603c29e06baa8667dd16e7f3d635366e7e5e",
    },
    "tdc_dili.tab": {
        "url": "https://dataverse.harvard.edu/api/access/datafile/4259585",
        "sha256": "d3961647ff6df9711b6aa4b9fe59d6cbeb40f9d23dd6e9d51d6656e6e6df5ed8",
    },
    "dilimap_validation.h5ad": {
        "url": "https://dilimap.s3.amazonaws.com/public/data/validation_data_pathways.h5ad",
        "sha256": "f38d943a242d7a9b34d07bf6099cc11590f7ae716c60ebb423b5d987ffc9c60d",
    },
}


def scaffold(smiles):
    return MurckoScaffold.MurckoScaffoldSmiles(smiles=smiles)


def name_index(rows):
    index = defaultdict(set)
    for row in rows:
        names = [row.get("compound_name", ""), row.get("CompoundName", "")]
        names.extend(json.loads(row.get("synonyms") or "[]"))
        for name in names:
            if name and normalized_name(name):
                index[normalized_name(name)].add(row["compound_id"])
    return index


def audit_records(records, reference, membership, source_rows):
    """Report overlapping flags independently; no score-dependent exclusion rules."""
    fields = ("canonical_smiles", "structure_key", "connectivity_group", "scaffold")
    indexes = {field: defaultdict(set) for field in fields}
    source_indexes = {field: defaultdict(set) for field in fields}
    for row in reference:
        for field in fields:
            value = scaffold(row["canonical_smiles"]) if field == "scaffold" else row[field]
            if value:  # Acyclic molecules do NOT share an 'empty scaffold' group.
                indexes[field][value].add(row["structure_id"])
    for row in source_rows:
        if not row.get("canonical_smiles"):
            continue
        for field in fields:
            value = scaffold(row["canonical_smiles"]) if field == "scaffold" else row.get(field)
            if value:
                source_indexes[field][value].add(row["compound_id"])
    names = name_index(source_rows)
    source_by_id = {r["compound_id"]: r for r in source_rows}
    refs = {r["structure_id"]: r for r in reference}
    audited = []
    for original in records:
        row = dict(original)
        name_hits = sorted(names.get(normalized_name(row.get("name", "")), set()))
        row["source_name_match_ids"] = name_hits
        row["source_name_match_categories"] = sorted({
            source_by_id[cid].get("dili_category", "") for cid in name_hits
        })
        row["frozen_name_match_ids"] = sorted({
            source_by_id[cid]["structure_id"] for cid in name_hits
            if source_by_id[cid].get("structure_id") in refs
        })
        # Name hits flag potential overlap, not resolved identity or label conflicts.
        row["status"] = "unresolved_structure"
        if not row.get("smiles"):
            row["reason"] = "missing_source_smiles"
            audited.append(row)
            continue
        try:
            info = standardize(row["smiles"])
        except ValueError as exc:
            row.update(status="preprocessing_rejected", reason=str(exc))
            audited.append(row)
            continue
        row.update(info)
        row["scaffold"] = scaffold(info["canonical_smiles"])
        row["status"] = "standardized"
        row["overlap"] = {}
        row["all_source_structure_match_ids"] = {}
        for field in fields:
            hits = sorted(indexes[field].get(row[field], set())) if row[field] else []
            row["overlap"][field] = {
                "structure_ids": hits,
                "partitions": sorted({membership[sid]["partition"] for sid in hits}),
            }
            row["all_source_structure_match_ids"][field] = sorted(
                source_indexes[field].get(row[field], set()) if row[field] else set()
            )
        exact = set(row["overlap"]["canonical_smiles"]["structure_ids"])
        exact.update(row["overlap"]["structure_key"]["structure_ids"])
        row["exact_label_conflict_ids"] = sorted(
            sid for sid in exact if row["label"] is not None
            and int(refs[sid]["dili_label"]) != row["label"]
        )
        row["no_detected_frozen_structure_overlap"] = not any(
            row["overlap"][field]["structure_ids"] for field in fields
        )
        audited.append(row)

    standardized = [r for r in audited if r["status"] == "standardized"]
    duplicates = {}
    for field in ("canonical_smiles", "connectivity_group"):
        groups = defaultdict(list)
        for row in standardized:
            groups[row[field]].append(row)
        duplicates[field] = [
            {"identity": identity, "ids": [r["id"] for r in group],
             "labels": sorted({r["label"] for r in group if r["label"] is not None}),
             "conflicting_binary_labels": len({r["label"] for r in group if r["label"] is not None}) > 1}
            for identity, group in sorted(groups.items()) if len(group) > 1
        ]
    pending = [r for r in standardized if r["no_detected_frozen_structure_overlap"]]
    conservative = [r for r in pending if not r["source_name_match_ids"] and r["label"] is not None
                    and not any(r["all_source_structure_match_ids"].values())]
    summary = {
        "records": len(audited),
        "labels": dict(Counter("unknown" if r["label"] is None else str(r["label"]) for r in audited)),
        "statuses": dict(Counter(r["status"] for r in audited)),
        "preprocessing_reasons": dict(Counter(r["reason"] for r in audited if "reason" in r)),
        "source_name_match_rows": sum(bool(r["source_name_match_ids"]) for r in audited),
        "frozen_name_match_rows": sum(bool(r["frozen_name_match_ids"]) for r in audited),
        "overlap_rows": {field: sum(bool(r["overlap"][field]["structure_ids"]) for r in standardized) for field in fields},
        "overlap_rows_by_partition": {
            field: {part: sum(part in r["overlap"][field]["partitions"] for r in standardized)
                    for part in ("train", "validation", "test")} for field in fields
        },
        "exact_label_conflict_rows": sum(bool(r["exact_label_conflict_ids"]) for r in standardized),
        "no_detected_frozen_structure_overlap_rows": len(pending),
        "all_source_structure_overlap_rows": {
            field: sum(bool(r["all_source_structure_match_ids"][field]) for r in standardized)
            for field in fields
        },
        "also_no_available_source_overlap_known_label_rows": len(conservative),
        "also_no_available_source_overlap_known_label_counts": dict(Counter(str(r["label"]) for r in conservative)),
        "approved_evaluation_rows": 0,
    }
    return {"summary": summary, "duplicate_groups": duplicates, "records": audited}


def read_tdc(path):
    with Path(path).open() as handle:
        source = list(csv.DictReader(handle, delimiter="\t"))
    records = []
    for number, row in enumerate(source, 2):
        if row["Y"] not in {"0.0", "1.0", "0", "1"}:
            raise ValueError("unexpected_tdc_label")
        records.append({"id": row["Drug_ID"], "source_row": number, "name": "",
                        "smiles": row["Drug"], "raw_label": row["Y"], "label": int(float(row["Y"]))})
    return records


def read_dilist(path):
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        values = list(workbook["DILIst"].values)
    finally:
        workbook.close()
    if [str(x).strip() for x in values[0]] != [
        "DILIST_ID", "CompoundName", "DILIst Classification", "Routs of Administration"
    ]:
        raise ValueError("unexpected_dilist_header")
    records = []
    for number, (identifier, name, label, route) in enumerate(values[1:], 2):
        if label not in (0, 1):
            raise ValueError("unexpected_dilist_label")
        records.append({"id": str(identifier), "source_row": number, "name": name,
                        "smiles": "", "raw_label": label, "label": int(label), "route": route})
    return records


def read_h5_column(node):
    """Read AnnData categorical metadata without interpreting -1 as last category."""
    if hasattr(node, "keys"):
        categories = read_h5_column(node["categories"])
        return [None if code == -1 else categories[code] for code in node["codes"][:]]
    if node.dtype.kind in "OS":
        return node.asstr()[:].tolist()
    return node[:].tolist()


def read_dilimap(path):
    import h5py  # Optional metadata reader; never loads expression X or model artifacts.

    columns = ("compound_name", "smiles", "DILI_label_binary", "DILI_label", "source", "DILIrank")
    with h5py.File(path, "r") as handle:
        data = {key: read_h5_column(handle["obs"][key]) for key in columns}
    if len({len(values) for values in data.values()}) != 1:
        raise ValueError("inconsistent_dilimap_column_lengths")
    compounds = {}
    for number, values in enumerate(zip(*(data[key] for key in columns))):
        name, smiles, binary, detailed, source, rank = values
        if binary not in {None, "DILI", "No DILI"}:
            raise ValueError("unexpected_dilimap_label")
        record = {"id": name, "name": name, "smiles": smiles or "", "raw_label": binary,
                  "label": {"DILI": 1, "No DILI": 0}.get(binary), "detailed_label": detailed,
                  "label_source": source, "source_dilirank_label": rank}
        if name in compounds and compounds[name]["record"] != record:
            raise ValueError("inconsistent_dilimap_replicate_metadata")
        entry = compounds.setdefault(name, {"record": record, "obs_rows_zero_based": []})
        entry["obs_rows_zero_based"].append(number)
    return [dict(item["record"], obs_rows_zero_based=item["obs_rows_zero_based"])
            for _, item in sorted(compounds.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=ROOT / "artifacts/external_audit/sources")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/external_audit/report.json")
    parser.add_argument("--include-dilimap", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("audit_output_already_exists_use_new_path")
    rows, _, membership, data_sha, split_sha = load_frozen_inputs()
    enriched = ROOT / "data/processed/dilirank2_enriched.csv"
    with enriched.open() as handle:
        source_rows = list(csv.DictReader(handle))
    report = {"schema": "external_dili_source_audit_v1", "retrieval_date": "2026-09-19",
              "standardization_version": POLICY, "rdkit_version": rdBase.rdkitVersion,
              "data_sha256": data_sha, "split_sha256": split_sha, "enriched_sha256": digest(enriched),
              "limitations": ["No cohort approved; no models scored.",
                              "Name nonmatches do not establish chemical novelty.",
                              "TDC has no compound-name field; source-name matching is unavailable for TDC.",
                              "All-source structure checks cover only rows with available canonical structures.",
                              "Tautomer, manual structure/label and licensing review remain outstanding.",
                              "Representation pretraining overlap is unknown."], "sources": {}, "audits": {}}
    readers = {"dilist.xlsx": read_dilist, "tdc_dili.tab": read_tdc}
    if args.include_dilimap:
        readers["dilimap_validation.h5ad"] = read_dilimap
    for filename, reader in readers.items():
        path = args.sources / filename
        if digest(path) != SOURCES[filename]["sha256"]:
            raise ValueError(f"source_checksum_mismatch: {filename}")
        report["sources"][filename] = SOURCES[filename]
        report["audits"][filename] = audit_records(reader(path), rows, membership, source_rows)
    save_json(args.output, report)
    print(json.dumps({key: value["summary"] for key, value in report["audits"].items()}, indent=2))


if __name__ == "__main__":
    main()
