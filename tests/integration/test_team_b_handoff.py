"""Validate real cached Team B results against the shared Team A runtime."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app/src'))
from toxoracle_app.validation import validate_response_against_request, validate_combined_report
from toxoracle_app.join import combine_responses


class TeamBHandoffTests(unittest.TestCase):
    def test_real_cached_handoff_and_unavailable_comparator(self):
        request=json.loads((ROOT/'demo/examples/dili_request.json').read_text())
        toxicity=json.loads((ROOT/'demo/examples/dili_response.json').read_text())
        validate_response_against_request(request,toxicity,expected_stream='toxicity')
        discovery=json.loads((ROOT/'contracts/examples/discovery.not-run.json').read_text())
        template=discovery['results'][0]
        discovery['request_id']=request['request_id'];discovery['results']=[]
        for compound in request['compounds']:
            row=copy.deepcopy(template)
            row.update(compound_id=compound['compound_id'],structure_id=compound['structure_id'])
            row['structural_evidence'].update({k:compound[k] for k in ['canonical_smiles','atom_mapped_smiles','standardization_version']})
            discovery['results'].append(row)
        validate_response_against_request(request,discovery,expected_stream='discovery')
        policy=json.loads((ROOT/'configs/triage-v1.json').read_text())
        combined=combine_responses(request,discovery,toxicity,policy)
        validate_combined_report(combined)
        self.assertEqual(len(combined['results']),3)
        for result in combined['results']:
            self.assertEqual(result['comparison']['comparison_mode'],'unavailable')


if __name__=='__main__':unittest.main()
