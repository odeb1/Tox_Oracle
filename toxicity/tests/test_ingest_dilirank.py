"""Offline checks of the identity and curation decisions that affect model labels."""
import importlib.util
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

SPEC = importlib.util.spec_from_file_location("ingest", Path(__file__).parents[1] / "src/ingest_dilirank.py")
ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest)


@pytest.mark.parametrize("raw,expected", [("vMOST-DILI-concern", "Most-DILI-concern"),
    ("vNo-DILI-Concern", "No-DILI-concern"), ("Ambiguous-DILI-concern", "Ambiguous-DILI-concern")])
def test_label_case_preserves_meaning(raw, expected):
    assert ingest.category(raw) == expected


def test_unknown_label_is_not_negative():
    with pytest.raises(ValueError, match="Unknown FDA label"):
        ingest.category("Uncertain")


def test_salts_and_repeated_parents_share_structure():
    parent = "NCCc1ccccc1"
    hydrochloride = "[Cl-].[NH3+]CCc1ccccc1"
    assert ingest.standardize(parent)["structure_key"] == ingest.standardize(hydrochloride)["structure_key"]
    sodium = "[Na+].O=C([O-])c1ccccc1"
    calcium = "[Ca+2].O=C([O-])c1ccccc1.O=C([O-])c1ccccc1"
    assert ingest.standardize(sodium)["structure_key"] == ingest.standardize(calcium)["structure_key"]


def test_preserves_stereochemistry_and_covalent_modification():
    left = ingest.standardize("N[C@@H](C)C(=O)O")
    right = ingest.standardize("N[C@H](C)C(=O)O")
    assert left["structure_key"] != right["structure_key"]
    assert left["connectivity_group"] == right["connectivity_group"]
    assert ingest.standardize("CC(=O)Oc1ccccc1C(=O)O")["structure_key"] != ingest.standardize("Oc1ccccc1C(=O)O")["structure_key"]


@pytest.mark.parametrize("smiles,reason", [("not_a_smiles", "invalid_or_unspecified_structure"),
    ("*CC", "invalid_or_unspecified_structure"), ("", "invalid_or_unspecified_structure"),
    ("CCN.c1ccccc1", "unresolved_multicomponent_structure"),
    ("[Pt](N)(N)(Cl)Cl", "inorganic_structure"),
    ("C[Hg]C", "metal_or_unsupported_element"),
    ("C" * 110, "outside_initial_size_scope")])
def test_unsupported_structures_are_explicit(smiles, reason):
    with pytest.raises(ValueError, match=reason):
        ingest.standardize(smiles)


def test_no_tautomer_canonicalization():
    assert ingest.standardize("Oc1ccccn1")["canonical_smiles"] != ingest.standardize("O=c1cccc[nH]1")["canonical_smiles"]


def test_normalization_is_idempotent():
    first = ingest.standardize("[Cl-].[NH3+]CCc1ccccc1")
    second = ingest.standardize(first["canonical_smiles"])
    assert first["canonical_smiles"] == second["canonical_smiles"]
    assert first["structure_id"] == second["structure_id"]


def test_match_requires_unique_exact_synonym():
    props = [{"CID": 1, "SMILES": "CCO"}, {"CID": 2, "SMILES": "CCN"}]
    syn = {1: {"synonyms": ["Drug A"]}, 2: {"synonyms": ["Drug B"]}}
    assert ingest.select_match(" drug a ", props, syn)[0]["CID"] == 1
    assert ingest.select_match("Drug", props, syn)[1] == "no_exact_synonym_match"
    syn[2]["synonyms"] = ["Drug A"]
    assert ingest.select_match("Drug A", props, syn)[1] == "multiple_exact_matches"
    del syn[2]
    assert ingest.select_match("Drug A", props, syn)[1] == "synonyms_unavailable"


def test_salt_name_cannot_silently_resolve_to_parent():
    p = [{"CID": 1, "SMILES": "NCCc1ccccc1"}]
    s = {1: {"synonyms": ["Example hydrochloride"]}}
    assert ingest.select_match("Example hydrochloride", p, s)[1] == "name_structure_salt_mismatch"
    p[0]["SMILES"] = "[Cl-].[NH3+]CCc1ccccc1"
    assert ingest.select_match("Example hydrochloride", p, s)[1] is None


def test_query_cleans_whitespace_without_altering_chemical_name(tmp_path, monkeypatch):
    client = ingest.PubChemClient(tmp_path, offline=True)
    monkeypatch.setattr(client, "get", lambda url: url)
    url = client.properties(" (S)-Example\u00a0 hydrochloride\u00a0")
    assert "/name/%28S%29-Example%20hydrochloride/" in url


def test_covalent_fumarate_is_not_rejected_as_missing_counterion():
    smiles = "COC(=O)/C=C/C(=O)OC"
    props = [{"CID": 1, "SMILES": smiles}]
    synonyms = {1: {"synonyms": ["Dimethyl fumarate"]}}
    assert ingest.select_match("Dimethyl fumarate", props, synonyms)[1] is None
    assert ingest.standardize(smiles)["removed_fragments"] == "[]"


def test_lookup_failure_never_becomes_negative():
    row = {"LTKBID": "LT00001", "CompoundName": "Example", "dili_label": 0}
    response = {"url": "https://example.test", "http_status": 503, "error": "unavailable"}
    result = ingest.curate_row(row, response, {})
    assert not result["model_eligible"]
    assert result["exclusion_reason"] == "lookup_failed"
    assert result["canonical_smiles"] == ""


def test_inconsistent_source_identifiers_require_review():
    row = {"LTKBID": "LT00001", "CompoundName": "Example", "dili_label": 1}
    response = {"url": "https://example.test", "http_status": 200,
        "body": {"PropertyTable": {"Properties": [{"CID": 1, "SMILES": "CCO", "InChIKey": "WRONG"}]}}}
    synonyms = {1: {"synonyms": ["Example"], "source": "https://example.test/synonyms"}}
    result = ingest.curate_row(row, response, synonyms)
    assert not result["model_eligible"]
    assert result["exclusion_reason"] == "source_smiles_inchikey_mismatch"
    assert result["retrieved_smiles"] == "CCO"


def group_row(identifier, label, smiles="CCO"):
    return {"compound_id": identifier, "dili_label": label, "canonical_smiles": smiles,
            "model_eligible": label is not None, "original_dili_category": str(label)}


def test_conflicting_labels_exclude_entire_group():
    rows = [group_row("LT1", 0), group_row("LT2", 1), group_row("LT3", None)]
    model, duplicates = ingest.group_rows(rows)
    assert not model
    assert all(not row["model_eligible"] for row in rows)
    assert all(row["exclusion_reason"] == "conflicting_binary_labels" for row in rows)
    assert duplicates[0]["conflicting_binary_labels"]


def test_duplicates_retain_all_source_memberships():
    rows = [group_row("LT3", 1), group_row("LT1", None), group_row("LT2", 1)]
    model, _ = ingest.group_rows(rows)
    assert len(model) == 1
    assert model[0]["compound_id"] == "LT2"
    assert json.loads(model[0]["source_compound_ids"]) == ["LT1", "LT2", "LT3"]
    assert not next(r for r in rows if r["compound_id"] == "LT1")["model_eligible"]


def test_cache_replay_and_transient_retry(tmp_path, monkeypatch):
    calls = []
    responses = iter([503, 200])
    def get(url, **kwargs):
        calls.append(url)
        code = next(responses)
        return SimpleNamespace(status_code=code, text="busy", json=lambda: {"ok": code == 200})
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(ingest.time, "sleep", lambda seconds: None)
    client = ingest.PubChemClient(tmp_path)
    assert client.get("https://example.test")["http_status"] == 200
    assert len(calls) == 2
    assert client.get("https://example.test")["http_status"] == 200
    assert len(calls) == 2
    offline = ingest.PubChemClient(tmp_path, offline=True)
    assert offline.get("https://example.test")["http_status"] == 200
    assert offline.get("https://missing.test")["error"] == "not_cached"
    assert len(calls) == 2


def test_source_reader_uses_v2_and_reconciles_counts(tmp_path, monkeypatch):
    values = [("title",), tuple(ingest.SOURCE_COLUMNS)]
    index = 0
    for label, count in ingest.EXPECTED.items():
        for _ in range(count):
            index += 1
            values.append((f"LT{index:05d}", f"Name {index}", 0, "No match", label, "New"))
    class Workbook:
        def __getitem__(self, sheet):
            assert sheet == "version 2"
            return SimpleNamespace(values=values)
        def close(self):
            pass
    monkeypatch.setattr(ingest.openpyxl, "load_workbook", lambda *a, **k: Workbook())
    rows = ingest.read_source(tmp_path / "source.xlsx")
    assert len(rows) == 1336
    assert sum(r["dili_label"] is None for r in rows) == 354
    assert rows[0]["source_excel_row"] == 3
    values.pop()
    with pytest.raises(ValueError, match="counts changed"):
        ingest.read_source(tmp_path / "source.xlsx")


def test_offline_outputs_account_for_every_source_and_replay_identically(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Offline curation attempted network access")
    monkeypatch.setattr(requests, "get", no_network)
    raw = tmp_path / "data/raw/dilirank_2.0.xlsx"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"source hash fixture; source parsing tested separately")
    client = ingest.PubChemClient(tmp_path / "cache", offline=True)
    specs = [("LT1", "Example A", 1, "CCO", 1), ("LT2", "Example B", 1, "CCO", 1),
             ("LT3", "Example C", None, "CC(=O)O", 2), ("LT4", "Missing", 0, None, None)]
    rows = []
    for identifier, name, label, smiles, cid in specs:
        label_name = {1: "Most-DILI-concern", 0: "No-DILI-concern", None: "Ambiguous-DILI-concern"}[label]
        rows.append({"LTKBID": identifier, "CompoundName": name, "dili_label": label,
                     "original_dili_category": label_name, "dili_category": label_name})
        url = client.properties(name)["url"]
        ingest.save_json(client.cache_path(url), {"url": url, "http_status": 200 if cid else 404,
            "retrieved_at": "2026-01-01T00:00:00+00:00", "body": {"PropertyTable": {"Properties":
                [{"CID": cid, "SMILES": smiles}] if cid else []}}})
    url = client.synonyms([1, 2])["url"]
    ingest.save_json(client.cache_path(url), {"url": url, "http_status": 200,
        "body": {"InformationList": {"Information": [
            {"CID": 1, "Synonym": ["Example A", "Example B"]}, {"CID": 2, "Synonym": ["Example C"]}]}}})
    ingest.curate(rows, client, tmp_path)
    report_path = tmp_path / "data/manifests/dilirank2_acquisition_report.json"
    report = json.loads(report_path.read_text())
    assert report["acquisition_complete"]
    assert report["source_entries"] == 4
    assert report["model_ready_unique_structures"] == 1
    assert report["review_entries"] == 1
    with (tmp_path / "data/processed/dilirank2_enriched.csv").open() as handle:
        master = list(csv.DictReader(handle))
    assert {r["compound_id"] for r in master} == {"LT1", "LT2", "LT3", "LT4"}
    assert next(r for r in master if r["compound_id"] == "LT3")["dili_label"] == ""
    ingest.curate(rows, client, tmp_path)
    assert json.loads(report_path.read_text())["artifacts"] == report["artifacts"]
