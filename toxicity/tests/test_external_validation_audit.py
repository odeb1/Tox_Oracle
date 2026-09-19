"""Offline synthetic identity/metadata tests; no downloads or predictions."""
import pytest

from toxicity.src import external_validation_audit as audit
from toxicity.src.ingest_dilirank import standardize


def reference(smiles, name="reference", label=1):
    return dict(standardize(smiles), compound_id=name, compound_name=name,
                synonyms="[]", dili_label=str(label), dili_category="test_fixture")


def record(smiles, identifier="external", label=1, name=""):
    return dict(id=identifier, smiles=smiles, name=name, label=label, raw_label=label)


def run(records, refs):
    return audit.audit_records(records, refs, {
        row["structure_id"]: {"partition": "train"} for row in refs
    }, refs)


def test_salt_normalization_detects_overlap_and_retains_label_conflict():
    result = run([record("C[NH3+].[Cl-]", label=0)], [reference("CN")])
    row = result["records"][0]
    assert row["raw_label"] == row["label"] == 0
    assert row["exact_label_conflict_ids"]
    assert row["overlap"]["canonical_smiles"]["partitions"] == ["train"]
    assert result["summary"]["approved_evaluation_rows"] == 0


def test_stereo_connectivity_and_substituted_scaffold_overlap():
    refs = [reference("N[C@H](C)C(=O)O"), reference("Cc1ccccc1", "aromatic")]
    result = run([record("N[C@@H](C)C(=O)O"), record("Oc1ccccc1", "phenol")], refs)
    stereo, aromatic = result["records"]
    assert not stereo["overlap"]["canonical_smiles"]["structure_ids"]
    assert stereo["overlap"]["connectivity_group"]["structure_ids"]
    assert aromatic["overlap"]["scaffold"]["structure_ids"]
    assert not aromatic["overlap"]["connectivity_group"]["structure_ids"]


def test_empty_scaffold_does_not_collapse_all_acyclic_molecules():
    result = run([record("CCC")], [reference("CCO")])
    assert not result["records"][0]["overlap"]["scaffold"]["structure_ids"]
    assert result["summary"]["no_detected_frozen_structure_overlap_rows"] == 1


def test_duplicates_conflicting_labels_and_missing_structure_remain_visible():
    result = run([record("CCO", "a", 1), record("OCC", "b", 0),
                  record("", "missing", None), record("[Na+]", "inorganic")], [])
    duplicate = result["duplicate_groups"]["canonical_smiles"][0]
    assert duplicate["ids"] == ["a", "b"]
    assert duplicate["conflicting_binary_labels"]
    assert result["summary"]["statuses"] == {
        "standardized": 2, "unresolved_structure": 1, "preprocessing_rejected": 1}
    assert result["records"][2]["label"] is None


def test_synonym_overlap_is_conservative_not_structure_assignment():
    refs = [reference("CCO", "Ethanol")]
    refs[0]["synonyms"] = '["Alcohol", "ethyl alcohol"]'
    result = run([record("", name=" ETHYL  ALCOHOL ")], refs)
    assert result["summary"]["source_name_match_rows"] == 1
    assert result["records"][0]["status"] == "unresolved_structure"
    assert "canonical_smiles" not in result["records"][0]


def test_overlap_with_excluded_source_compound_is_not_called_independent():
    excluded = reference("c1ccncc1", "ambiguous")
    excluded["dili_category"] = "Ambiguous-DILI-concern"
    result = audit.audit_records([record("Cc1ccncc1")], [], {}, [excluded])
    assert result["summary"]["no_detected_frozen_structure_overlap_rows"] == 1
    assert result["summary"]["also_no_available_source_overlap_known_label_rows"] == 0
    assert result["records"][0]["all_source_structure_match_ids"]["scaffold"] == ["ambiguous"]


def test_tdc_rejects_unexpected_labels(tmp_path):
    path = tmp_path / "example.tab"
    path.write_text("Drug_ID\tDrug\tY\n1\tCCO\t2\n")
    with pytest.raises(ValueError, match="unexpected_tdc_label"):
        audit.read_tdc(path)


def test_dilist_reader_preserves_source_rows_and_route(tmp_path):
    book = audit.openpyxl.Workbook()
    sheet = book.active
    sheet.title = "DILIst"
    sheet.append(["DILIST_ID", "CompoundName", "DILIst Classification ", "Routs of Administration "])
    sheet.append([1, "example", 0, "Oral"])
    path = tmp_path / "example.xlsx"
    book.save(path)
    assert audit.read_dilist(path) == [{"id": "1", "source_row": 2, "name": "example",
                                     "smiles": "", "raw_label": 0, "label": 0, "route": "Oral"}]


def test_hdf5_missing_categories_do_not_become_last_category(tmp_path):
    h5py = pytest.importorskip("h5py")
    path = tmp_path / "example.h5ad"
    with h5py.File(path, "w") as handle:
        group = handle.create_group("label")
        group.create_dataset("categories", data=["DILI", "No DILI"], dtype=h5py.string_dtype())
        group.create_dataset("codes", data=[0, -1, 1])
    with h5py.File(path, "r") as handle:
        assert audit.read_h5_column(handle["label"]) == ["DILI", None, "No DILI"]
