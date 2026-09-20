"""Offline source-review tests; no workbook writes or downloads."""
from copy import deepcopy
import json

import pytest

from toxicity.src import curation_followup as review


def training_fixture():
    train, source, records = [], [], []
    for i, label in enumerate((0, 1)):
        sid, cid = f"structure{i}", f"LT0000{i}"
        train.append({"structure_id": sid, "dili_label": str(label), "source_compound_ids": json.dumps([cid])})
        source.append({"structure_id": sid, "compound_id": cid, "LTKBID": cid,
                       "compound_name": f"compound{i}", "CompoundName": f"compound{i}",
                       "vDILI-Concern": "vMost-DILI-concern" if label else "vNo-DILI-concern",
                       "source_excel_row": str(i+3), "Comment": "New", "mapping_status": "exact_pubchem_synonym",
                       "pubchem_cid": str(i+1), "structure_source": "public-source"})
        records.append({"structure_id": sid, "compound_name": f"compound{i}", "label": label,
                        "probabilities": {"rf": .8, "svm": .7}, "wrong_at_diagnostic_05": [] if label else ["rf", "svm"],
                        "nearest_outer_fitting_compound": {"structure_id": f"structure{1-i}", "label": 1-label, "tanimoto": .2}})
    return {"records": records, "hard_case_review_queue": [records[0]]}, train, source


def test_label_trace_is_read_only_and_missing_original_disclosed():
    audit, train, source = training_fixture()
    before = deepcopy((audit, train, source))
    result = review.training_review(audit, train, source)
    assert (audit, train, source) == before
    assert result["summary"]["training_records_verified"] == 2
    assert result["summary"]["verification_basis"] == "pinned_enriched_snapshot_retained_FDA_columns"
    assert result["summary"]["strata"]["0"]["consensus_errors"] == 1
    assert result["summary"]["strata"]["1"]["median_nearest_tanimoto_consensus_errors"] is None
    assert result["hard_cases"][0]["source_evidence"][0]["original_workbook_rechecked"] is False


@pytest.mark.parametrize("change", ["foreign", "duplicate", "label", "structure", "probability", "errors", "self_neighbour"])
def test_training_review_rejects_inconsistent_evidence(change):
    audit, train, source = training_fixture()
    if change == "foreign": audit["records"][0]["structure_id"] = "test_id"
    elif change == "duplicate": audit["records"].append(audit["records"][0])
    elif change == "label": source[0]["vDILI-Concern"] = "vMost-DILI-concern"
    elif change == "structure": source[0]["structure_id"] = "wrong"
    elif change == "probability": audit["records"][0]["probabilities"]["rf"] = float("nan")
    elif change == "errors": audit["records"][0]["wrong_at_diagnostic_05"] = []
    else: audit["records"][0]["nearest_outer_fitting_compound"]["structure_id"] = "structure0"
    with pytest.raises(ValueError): review.training_review(audit, train, source)


def test_naming_tag_is_only_a_review_flag_and_preserves_chemical_qualifiers():
    source = [{"compound_id": "LT1", "compound_name": "Acarbose", "synonyms": '["Acarbosum [INN-Latin]"]'}]
    hits = review.alias_hits(["Acarbosum"], review.alias_index(source))
    assert hits == [{"compound_id": "LT1", "compound_name": "Acarbose", "external_alias": "Acarbosum", "source_alias": "Acarbosum [INN-Latin]"}]
    assert review.alias_key("drug hydrochloride") != review.alias_key("drug")
    assert review.alias_key("drug [13C]") != review.alias_key("drug")
    assert review.alias_key("drug [unknown]") != review.alias_key("drug")


def test_ambiguous_membership_retained_without_overriding_frozen_label():
    audit, train, source = training_fixture()
    ambiguous = {**source[0], "compound_id": "LT99999", "LTKBID": "LT99999",
                 "vDILI-Concern": "Ambiguous-DILI-concern"}
    source.append(ambiguous)
    train[0]["source_compound_ids"] = json.dumps(["LT00000", "LT99999"])
    result = review.training_review(audit, train, source)
    case = result["hard_cases"][0]
    assert case["label"] == 0
    assert [r["mapped_label"] for r in case["source_evidence"]] == [0, None]


def test_external_review_preserves_labels_and_never_approves():
    source = [{"compound_id": "LT1", "compound_name": "Acarbose", "synonyms": '["Acarbosum [INN-Latin]"]'}]
    row = {"pubchem_cid": 1, "pubchem_title": "Acarbosum", "label": 1,
           "new_name_overlap_flags": [], "tautomer_no_stereo_source_match_ids": [],
           "underlying_table_disagreement": False, "pubchem_structure_source_overlap": {},
           "pubchem_identity": "connectivity_only_stereochemistry_differs",
           "underlying_table_evidence": [{"sheet": "S1.1", "annotation": "Most DILI-concern"}]}
    before = deepcopy(row)
    result = review.external_review([row], source, {})
    assert row == before and result["records"][0]["label"] == 1
    assert result["summary"]["new_flagged_from_previous_remainder"] == 1
    assert result["summary"]["approved"] == 0
    assert result["records"][0]["approved_for_evaluation"] is False
    assert result["records"][0]["endpoint_adjudicated"] is False


def test_source_cells_accept_numeric_or_text_identifiers_but_not_label_changes():
    class Sheet:
        def __init__(self, values): self.values = values
        def iter_rows(self, **kwargs): return iter([self.values])
    row = {"pubchem_cid": 123, "original_combined_table": {"row": 3, "smiles": "CC", "annotation": "Negative", "label": 0},
           "underlying_table_evidence": []}
    for cid in (123, "123"):
        review.verify_external_cells([row], {"supplementary table S2.1": Sheet((cid, "CC", "Negative", 0))})
    with pytest.raises(ValueError, match="cell_mismatch"):
        review.verify_external_cells([row], {"supplementary table S2.1": Sheet((123, "CC", "Negative", 1))})


def test_existing_output_rejected_before_input_read(tmp_path, monkeypatch):
    monkeypatch.setattr(review.experiment, "digest", lambda path: pytest.fail("unexpected read"))
    with pytest.raises(ValueError, match="refusing_to_overwrite"):
        review.run(tmp_path)
