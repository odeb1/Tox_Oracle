"""Offline transport/artifact tests with explicitly synthetic responses."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from toxoracle_discovery.boltz2 import (BoltzError, SETTINGS, digest, predict_candidate,
    rank_candidates, failed_candidate, validate_target, numbers)

ROOT=Path(__file__).resolve().parents[2]


class FakeClient:
    def __init__(self, response=None):
        self.calls=[]
        self.response=response if response is not None else {
            "structures":[{"format":"mmcif","structure":"data_synthetic\n_atom_site.id 1\n"}],
            "confidence_scores":[.8],"affinities":{"L1":{"affinity_probability_binary":[.9,.7],
                "affinity_pic50":[6.,7.],"affinity_pred_value":[0.,-1.]}}}
    def predict(self,payload):
        self.calls.append(payload)
        return self.response


class BoltzTests(unittest.TestCase):
    def setUp(self):
        self.target=json.loads((ROOT/"discovery/configs/targets/abl1.json").read_text())
        self.compound=json.loads((ROOT/"demo/examples/abl1_request.json").read_text())["compounds"][0]

    def test_payload_arrays_and_structures_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            client=FakeClient(); row=predict_candidate(self.compound,self.target,temp,client)
            self.assertEqual(row["binding_probability"],[.9,.7])
            self.assertEqual(row["mean_binding_probability"],.8)
            self.assertEqual(row["affinity_pic50"],[6.,7.])
            self.assertIsNone(row["provenance"]["served_model_version"])
            self.assertEqual(row["structures"][0]["atom_mapping_status"],"unavailable")
            self.assertEqual(client.calls[0]["diffusion_samples_affinity"],5)
            self.assertTrue(client.calls[0]["ligands"][0]["predict_affinity"])

    def test_no_affinity_never_uses_confidence_for_rank(self):
        client=FakeClient(); client.response["affinities"]={}
        with tempfile.TemporaryDirectory() as temp:
            row=predict_candidate(self.compound,self.target,temp,client)
            rank_candidates([row])
            self.assertEqual(row["status"],"ok")
            self.assertIsNone(row["rank"])

    def test_missing_structure_is_failed(self):
        client=FakeClient(); client.response["structures"]=[]
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(predict_candidate(self.compound,self.target,temp,client)["status"],"failed")

    def test_cache_exact_match_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); client=FakeClient()
            predict_candidate(self.compound,self.target,base/"one",client,cache=base/"cache")
            row=predict_candidate(self.compound,self.target,base/"two",client,cache=base/"cache")
            self.assertEqual(len(client.calls),1)
            self.assertEqual(row["provenance"]["execution_mode"],"cached")
            changed=dict(self.compound,compound_id="another")
            predict_candidate(changed,self.target,base/"three",client,cache=base/"cache")
            self.assertEqual(len(client.calls),2)
            path=base/"cache"/(row["provenance"]["cache_key"]+".json")
            entry=json.loads(path.read_text()); entry["response"]["confidence_scores"]=[.1]
            path.write_text(json.dumps(entry))
            with self.assertRaises(BoltzError): predict_candidate(self.compound,self.target,base/"four",client,cache=base/"cache")

    def test_finite_scores_and_probability_bounds(self):
        for value in [[float('nan')],[float('inf')],[True],[],['.5'],[1.1],[-.1]]:
            self.assertIsNone(numbers(value,probability=True))

    def test_ranking_ties_and_failures(self):
        rows=[]
        for cid,value in [('b',.9),('a',.9),('c',.8)]:
            r=failed_candidate(dict(self.compound,compound_id=cid),'synthetic','synthetic')
            r.update(status='ok',binding_probability=[value],mean_binding_probability=value)
            rows.append(r)
        rows.append(failed_candidate(dict(self.compound,compound_id='d'),'failed','failed'))
        rank_candidates(rows)
        self.assertEqual([r['rank'] for r in rows],[2,1,3,None])
        self.assertEqual([r['shortlisted'] for r in rows],[True,True,False,False])

    def test_target_checksum_and_settings_guard(self):
        validate_target(self.target)
        self.target['sequence']+='A'
        with self.assertRaises(ValueError): validate_target(self.target)

    def test_malformed_target_types_are_rejected(self):
        for target in [None, [], dict(self.target, sequence=123), dict(self.target, target_id=123)]:
            with self.assertRaises(ValueError): validate_target(target)


if __name__ == '__main__': unittest.main()
