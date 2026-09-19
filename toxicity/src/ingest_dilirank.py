"""Acquire FDA DILIrank 2.0 and curate traceable PubChem structures.

Run from any directory; paths default to the repository containing this file.
Only the fetch stage uses the network. No model training is performed here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import unicodedata
from urllib.parse import quote

import openpyxl
import requests
from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

ROOT = Path(__file__).resolve().parents[2]
FDA_URL = "https://www.fda.gov/media/113052/download?attachment="
FDA_PAGE = "https://www.fda.gov/science-research/liver-toxicity-knowledge-base-ltkb/drug-induced-liver-injury-rank-dilirank-20-dataset"
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
POLICY = "dilirank_parent_v1"
EXPECTED = {"Most-DILI-concern": 217, "Less-DILI-concern": 351,
            "No-DILI-concern": 414, "Ambiguous-DILI-concern": 354}
SOURCE_COLUMNS = ["LTKBID", "CompoundName", "SeverityClass", "LabelSection", "vDILI-Concern", "Comment"]


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temp.replace(path)


def normalized_name(name):
    # Preserve punctuation, stereochemical prefixes and salt names.
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def category(value):
    key = value.strip().casefold()
    if key.startswith("v"):
        key = key[1:]
    for label in EXPECTED:
        if key == label.casefold():
            return label
    raise ValueError(f"Unknown FDA label: {value!r}")


def read_source(path):
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook["version 2"]  # The workbook also contains version 1.
        values = list(sheet.values)
        headers = list(values[1])
        if headers[:6] != SOURCE_COLUMNS or any(v is not None for v in headers[6:]):
            raise ValueError(f"FDA schema changed: {headers}")
        rows = []
        for number, cells in enumerate(values[2:], start=3):
            if not any(c is not None for c in cells):
                continue
            if any(c is not None for c in cells[6:]):
                raise ValueError(f"Unexpected additional data in row {number}")
            row = dict(zip(SOURCE_COLUMNS, cells[:6]))
            if not re.fullmatch(r"LT\d+", str(row["LTKBID"])) or not row["CompoundName"]:
                raise ValueError(f"Invalid FDA identity in row {number}")
            row.update(source_excel_row=number, original_dili_category=row["vDILI-Concern"],
                       dili_category=category(row["vDILI-Concern"]))
            row["dili_label"] = {"Most-DILI-concern": 1, "Less-DILI-concern": 1,
                                 "No-DILI-concern": 0, "Ambiguous-DILI-concern": None}[row["dili_category"]]
            rows.append(row)
        if len({r["LTKBID"] for r in rows}) != len(rows):
            raise ValueError("Duplicate source LTKBIDs")
        counts = dict(Counter(r["dili_category"] for r in rows))
        if counts != EXPECTED:
            raise ValueError(f"Source version/counts changed: {counts}; expected {EXPECTED}")
        return rows
    finally:
        workbook.close()


class PubChemClient:
    """Atomic disk cache, global <=2 requests/sec, finite retries, offline replay."""
    def __init__(self, cache, offline=False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.lock = threading.Lock()
        self.next_request = 0.0

    def cache_path(self, url):
        return self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    def get(self, url):
        path = self.cache_path(url)
        if path.exists():
            cached = json.loads(path.read_text())
            if (cached["http_status"] in (200, 404) and not cached.get("error")) or self.offline:
                return cached
        if self.offline:
            return {"url": url, "http_status": None, "body": {}, "error": "not_cached"}
        result = None
        for attempt in range(4):
            with self.lock:
                delay = self.next_request - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                self.next_request = time.monotonic() + 0.5
            try:
                response = requests.get(url, timeout=(10, 40), headers={"User-Agent": "ToxOracle-DILIrank-ingestion/1.0"})
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                result = {"url": url, "retrieved_at": now(), "http_status": response.status_code,
                          "body": body, "error": None if response.status_code in (200, 404) else response.text[:300]}
                if response.status_code == 200 and not body:
                    result["error"] = "invalid_json"
                if response.status_code in (200, 404) and not result["error"]:
                    break
                if response.status_code not in (429, 500, 502, 503, 504, 200):
                    break
            except requests.RequestException as exc:
                result = {"url": url, "retrieved_at": now(), "http_status": None,
                          "body": {}, "error": str(exc)}
            if attempt < 3:
                time.sleep(2 ** attempt)
        save_json(path, result)
        return result

    def properties(self, name):
        query_name = " ".join(unicodedata.normalize("NFKC", name).split())
        return self.get(f"{PUBCHEM}/compound/name/{quote(query_name, safe='')}/property/IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight/JSON?name_type=complete")

    def synonyms(self, cids):
        return self.get(f"{PUBCHEM}/compound/cid/{','.join(map(str, cids))}/synonyms/JSON")


def property_rows(response):
    return response.get("body", {}).get("PropertyTable", {}).get("Properties", [])


def fetch(rows, client):
    responses = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(client.properties, r["CompoundName"]): r for r in rows}
        for number, future in enumerate(as_completed(pending), start=1):
            row = pending[future]
            responses[row["LTKBID"]] = future.result()
            if number % 50 == 0 or number == len(rows):
                counts = Counter(v["http_status"] for v in responses.values())
                print(f"Names: {number}/{len(rows)}; HTTP statuses {dict(counts)}", flush=True)
    cids = sorted({p["CID"] for result in responses.values() for p in property_rows(result)})
    for start in range(0, len(cids), 40):
        client.synonyms(cids[start:start + 40])
        print(f"Synonyms: {min(start + 40, len(cids))}/{len(cids)}", flush=True)


def load_synonyms(responses, client):
    cids = sorted({p["CID"] for result in responses.values() for p in property_rows(result)})
    result = {}
    for start in range(0, len(cids), 40):
        response = client.synonyms(cids[start:start + 40])
        for item in response.get("body", {}).get("InformationList", {}).get("Information", []):
            result[item["CID"]] = {"synonyms": item.get("Synonym", []), "source": response["url"],
                                   "retrieved_at": response.get("retrieved_at")}
    return result


# Explicit disconnected counterions/solvents. Never choose a largest fragment blindly.
# Neutralisation before comparison accommodates protonation representations.
COUNTERIONS = ["O", "Cl", "Br", "I", "[Na+]", "[K+]", "[Li+]", "[Ca+2]", "[Mg+2]",
              "O=S(=O)(O)O", "OP(=O)(O)O", "CC(=O)O", "O=C(O)C=CC(=O)O",
              "O=C(O)CC(O)(CC(=O)O)C(=O)O", "CS(=O)(=O)O", "O=S(=O)(O)c1ccccc1",
              "Cc1ccc(S(=O)(=O)O)cc1", "O=C(O)C(O)C(O)C(=O)O", "O=C(O)C(=O)O",
              "O=C(O)CCC(=O)O", "OCCO", "CCO", "CO", "CC(C)=O"]
UNCHARGER = rdMolStandardize.Uncharger()


def neutral_key(mol):
    return Chem.MolToSmiles(UNCHARGER.uncharge(mol), isomericSmiles=False)


COUNTERION_KEYS = {neutral_key(Chem.MolFromSmiles(s)) for s in COUNTERIONS}
ALLOWED_ELEMENTS = {1, 5, 6, 7, 8, 9, 14, 15, 16, 17, 34, 35, 53}
PEPTIDE_BOND = Chem.MolFromSmarts("[NX3][CX4][CX3](=O)[NX3]")


def standardize(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or not mol.GetNumAtoms() or any(a.GetAtomicNum() == 0 for a in mol.GetAtoms()):
        raise ValueError("invalid_or_unspecified_structure")
    fragments = list(Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True))
    removed = []
    if len(fragments) > 1:
        retained = []
        for fragment in fragments:
            if neutral_key(fragment) in COUNTERION_KEYS:
                removed.append(Chem.MolToSmiles(fragment))
            else:
                retained.append(fragment)
        if not retained:
            raise ValueError("no_supported_organic_parent")
        # Repeated identical parent molecules in e.g. calcium salts can collapse.
        unique = {Chem.MolToSmiles(UNCHARGER.uncharge(f), isomericSmiles=True): f for f in retained}
        if len(unique) != 1:
            raise ValueError("unresolved_multicomponent_structure")
        mol = next(iter(unique.values()))
    if not any(a.GetAtomicNum() == 6 for a in mol.GetAtoms()):
        raise ValueError("inorganic_structure")
    if any(a.GetAtomicNum() not in ALLOWED_ELEMENTS for a in mol.GetAtoms()):
        raise ValueError("metal_or_unsupported_element")
    # Normalize functional groups, then neutralize where possible. No tautomer canonicalization.
    mol = rdMolStandardize.Normalizer().normalize(mol)
    mol = UNCHARGER.uncharge(mol)
    Chem.SanitizeMol(mol)
    if Descriptors.MolWt(mol) > 1500 or mol.GetNumHeavyAtoms() > 100:
        raise ValueError("outside_initial_size_scope")
    if len(mol.GetSubstructMatches(PEPTIDE_BOND)) >= 10:
        raise ValueError("peptide_outside_initial_scope")
    canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    key = Chem.MolToInchiKey(mol)
    if not key:
        raise ValueError("inchi_generation_failed")
    return {"canonical_smiles": canonical, "structure_key": key,
            "structure_id": hashlib.sha256((POLICY + ":" + canonical).encode()).hexdigest(),
            "connectivity_group": key.split("-")[0],
            "removed_fragments": json.dumps(removed), "parent_molecular_weight": round(Descriptors.MolWt(mol), 4),
            "standardization_version": POLICY}


def salt_form_issue(name, smiles):
    """Conservative rejection of obvious parent-for-salt results, not proof of identity."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return "invalid_smiles"
    lower = normalized_name(name)
    expected = {"hydrochloride": 17, "hydrobromide": 35, "sodium": 11,
                "potassium": 19, "calcium": 20, "magnesium": 12, "lithium": 3}
    for token, atomic_number in expected.items():
        if re.search(r"\b" + token + r"\b", lower):
            if not any(a.GetAtomicNum() == atomic_number for a in mol.GetAtoms()):
                return "name_structure_salt_mismatch"
    # Organic names such as "fumarate" or "citrate" may describe covalent
    # structures, not counterions. The name alone cannot require disconnection.
    if re.search(r"\b(hydrochloride|hydrobromide)\b", lower):
        if len(Chem.GetMolFrags(mol)) < 2:
            return "name_structure_salt_mismatch"
    return None


def select_match(name, properties, synonyms):
    matches = [p for p in properties if any(normalized_name(s) == normalized_name(name)
               for s in synonyms.get(p["CID"], {}).get("synonyms", []))]
    if not properties:
        return None, "name_not_found"
    if any(p["CID"] not in synonyms for p in properties):
        return None, "synonyms_unavailable"
    if len(matches) != 1:
        return None, "multiple_exact_matches" if len(matches) > 1 else "no_exact_synonym_match"
    selected = matches[0]
    smiles = selected.get("SMILES") or selected.get("IsomericSMILES")
    if not smiles:
        return None, "isomeric_smiles_unavailable"
    issue = salt_form_issue(name, smiles)
    return (None, issue) if issue else (selected, None)


def curate_row(row, response, synonyms):
    result = dict(row, compound_id=row["LTKBID"], compound_name=row["CompoundName"],
                  label_source=FDA_URL, structure_source="", mapping_status="unresolved",
                  model_eligible=False, exclusion_reason="", canonical_smiles="", structure_key="",
                  structure_id="", connectivity_group="", standardization_version=POLICY,
                  retrieved_smiles="", pubchem_cid="", pubchem_inchikey="", synonyms="",
                  lookup_url=response["url"], lookup_retrieved_at=response.get("retrieved_at", ""))
    props = property_rows(response)
    result["candidate_cids"] = json.dumps([p["CID"] for p in props])
    result["candidate_structures"] = json.dumps(props, ensure_ascii=False)
    if response["http_status"] not in (200, 404) or response.get("error"):
        result["exclusion_reason"] = "lookup_failed"
        result["lookup_error"] = response.get("error") or str(response["http_status"])
        return result
    match, reason = select_match(row["CompoundName"], props, synonyms)
    if reason:
        result["exclusion_reason"] = reason
        return result
    cid = match["CID"]
    result.update(pubchem_cid=cid, retrieved_smiles=match.get("SMILES") or match["IsomericSMILES"],
                  pubchem_inchikey=match.get("InChIKey", ""), molecular_formula=match.get("MolecularFormula", ""),
                  source_molecular_weight=match.get("MolecularWeight", ""),
                  synonyms=json.dumps(synonyms[cid]["synonyms"], ensure_ascii=False),
                  synonym_source=synonyms[cid]["source"],
                  structure_source=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                  mapping_status="exact_pubchem_synonym")
    try:
        source_mol = Chem.MolFromSmiles(result["retrieved_smiles"])
        if source_mol is None:
            raise ValueError("invalid_smiles")
        if result["pubchem_inchikey"] and Chem.MolToInchiKey(source_mol) != result["pubchem_inchikey"]:
            raise ValueError("source_smiles_inchikey_mismatch")
        result.update(standardize(result["retrieved_smiles"]))
    except ValueError as exc:
        result["exclusion_reason"] = str(exc)
        return result
    result["exclusion_reason"] = "ambiguous_dili_label" if row["dili_label"] is None else ""
    result["model_eligible"] = row["dili_label"] is not None
    return result


def group_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        if row.get("canonical_smiles"):
            groups[row["canonical_smiles"]].append(row)
    model_rows = []
    duplicate_groups = []
    for group in groups.values():
        group.sort(key=lambda r: r["compound_id"])
        ids = [r["compound_id"] for r in group]
        labels = {r["dili_label"] for r in group if r["dili_label"] is not None}
        for row in group:
            row["source_compound_ids"] = json.dumps(ids)
        if len(group) > 1:
            duplicate_groups.append({"source_compound_ids": ids, "labels": sorted(labels),
                                     "conflicting_binary_labels": len(labels) > 1})
        if len(labels) > 1:
            for row in group:
                row.update(model_eligible=False, exclusion_reason="conflicting_binary_labels")
            continue
        eligible = [r for r in group if r["model_eligible"]]
        if eligible:
            representative = dict(eligible[0])
            representative["source_original_categories"] = json.dumps([r["original_dili_category"] for r in group])
            model_rows.append(representative)
    return sorted(model_rows, key=lambda r: r["compound_id"]), duplicate_groups


def write_csv(path, rows, columns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or list(dict.fromkeys(k for row in rows for k in row))
    temp = path.with_suffix(".csv.tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def curate(rows, client, root):
    responses = {r["LTKBID"]: client.properties(r["CompoundName"]) for r in rows}
    synonyms = load_synonyms(responses, client)
    enriched = [curate_row(r, responses[r["LTKBID"]], synonyms) for r in rows]
    model_rows, duplicates = group_rows(enriched)
    # Review excludes label-only exclusions; Ambiguous is an intentional target choice.
    review = [r for r in enriched if r["exclusion_reason"] not in ("", "ambiguous_dili_label")]
    columns = list(dict.fromkeys(k for row in enriched for k in row))
    out = root / "data/processed"
    write_csv(out / "dilirank2_enriched.csv", enriched, columns)
    write_csv(out / "dilirank2_review.csv", review, columns)
    model_columns = ["compound_id", "compound_name", "canonical_smiles", "structure_key", "structure_id",
                     "connectivity_group", "original_dili_category", "dili_label", "label_source", "structure_source",
                     "pubchem_cid", "standardization_version", "source_compound_ids", "source_original_categories"]
    write_csv(out / "dilirank2_model_ready.csv", [{k: r.get(k, "") for k in model_columns} for r in model_rows], model_columns)
    report = {"generated_at": now(), "source_entries": len(rows),
              "acquisition_complete": all(v["http_status"] in (200, 404) and not v.get("error") for v in responses.values())
                  and all(p["CID"] in synonyms for v in responses.values() for p in property_rows(v)),
              "missing_or_failed_name_lookups": sum(v["http_status"] not in (200, 404) or bool(v.get("error")) for v in responses.values()),
              "missing_synonym_cids": sorted({p["CID"] for v in responses.values() for p in property_rows(v)} - set(synonyms)),
              "source_categories": dict(Counter(r["dili_category"] for r in enriched)),
              "matched_pubchem_entries": sum(bool(r["pubchem_cid"]) for r in enriched),
              "standardized_entries": sum(bool(r["canonical_smiles"]) for r in enriched),
              "eligible_source_entries": sum(r["model_eligible"] for r in enriched),
              "model_ready_unique_structures": len(model_rows),
              "model_ready_class_counts": dict(Counter(r["dili_label"] for r in model_rows)),
              "review_entries": len(review),
              "exclusion_counts": dict(Counter(r["exclusion_reason"] for r in enriched if r["exclusion_reason"])),
              "coverage_by_category": {c: {"total": sum(r["dili_category"] == c for r in enriched),
                  "matched": sum(r["dili_category"] == c and bool(r["pubchem_cid"]) for r in enriched),
                  "standardized": sum(r["dili_category"] == c and bool(r["canonical_smiles"]) for r in enriched)} for c in EXPECTED},
              "duplicate_groups": duplicates, "rdkit_version": rdBase.rdkitVersion,
              "standardization_version": POLICY,
              "pipeline_sha256": digest(Path(__file__)),
              "dependency_lock_sha256": digest(ROOT / "toxicity/requirements-data.lock"),
              "source_sha256": digest(root / "data/raw/dilirank_2.0.xlsx"),
              "artifacts": {p.name: digest(p) for p in sorted(out.glob("dilirank2_*.csv"))},
              "limitations": ["Exact PubChem synonyms are database identity evidence, not manual verification of every structure.",
                  "Unresolved, unsupported and conflicting records are retained but excluded from the model-ready subset.",
                  "No train/validation/test split or model has been created. Group related chemical forms before splitting."]}
    save_json(root / "data/manifests/dilirank2_acquisition_report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("duplicate_groups", "artifacts", "limitations")}, indent=2))


def ensure_source(root, offline):
    path = root / "data/raw/dilirank_2.0.xlsx"
    manifest_path = root / "data/manifests/dilirank2_source.json"
    if not path.exists():
        if offline:
            raise FileNotFoundError("FDA workbook absent; run fetch with network access first")
        response = requests.get(FDA_URL, timeout=(10, 90))
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.stem + ".download.xlsx")
        temporary.write_bytes(response.content)
        read_source(temporary)
        temporary.replace(path)
    rows = read_source(path)
    checksum = digest(path)
    if manifest_path.exists():
        if json.loads(manifest_path.read_text())["sha256"] != checksum:
            raise ValueError("FDA workbook checksum differs from the recorded source manifest")
    else:
        save_json(manifest_path, {"dataset": "FDA DILIrank 2.0", "url": FDA_URL, "landing_page": FDA_PAGE,
            "local_path": "data/raw/dilirank_2.0.xlsx", "sheet": "version 2", "header_row": 2,
            "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "retrieval_timestamp_basis": "local download file modification time", "sha256": checksum,
            "source_columns": SOURCE_COLUMNS, "entries": len(rows), "category_counts": EXPECTED,
            "access_conditions": {"fda": "Public FDA download; preserve attribution. No dataset-specific licence stated on landing page; repository licence does not relicense source data.",
                "fda_notice": "FDA asks downloaders to notify NCTRBioinformaticsSupport@fda.hhs.gov. No email sent by this pipeline.",
                "pubchem": "Public PUG REST; retain source attribution and contributing-source rights. Cache locally; do not assume all contributed data share a single licence.",
                "pubchem_policy_url": "https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest"}})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("fetch", "curate", "all"), default="all")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    rows = ensure_source(args.root, offline=args.stage == "curate")
    client = PubChemClient(args.root / "data/cache/pubchem", offline=args.stage == "curate")
    if args.stage in ("fetch", "all"):
        fetch(rows, client)
    if args.stage in ("curate", "all"):
        client.offline = True
        curate(rows, client, args.root)


if __name__ == "__main__":
    main()
