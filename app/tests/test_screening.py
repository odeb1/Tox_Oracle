"""Offline v3 integration and decision-policy checks; no scientific claims from fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import argparse
import io
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "discovery/src"))
from toxoracle_discovery.boltz2 import failed_candidate, rank_candidates
from toxoracle_app.screening import combine_screening, render, summary, validate_screening_report
from toxoracle_app.validation import ContractValidationError
from toxoracle_app import screen_cli


def fixtures():
    request = json.loads((ROOT / "contracts/examples/request.valid.json").read_text())
    compound = request["compounds"][0]
    request["compounds"] = [dict(compound, compound_id=f"c{i}") for i in range(3)]
    rows = []
    for c, value in zip(request["compounds"], [.8, .7, .6]):
        r = failed_candidate(c, "fixture", "synthetic")
        r.update(status="ok", error=None, binding_probability=[value], mean_binding_probability=value,
                 structures=[dict(uri="fixture.cif", sha256="a"*64, format="mmcif", origin="predicted", atom_mapping_status="unavailable")])
        rows.append(r)
    discovery = dict(schema_version="3.0", stream="discovery", request_id=request["request_id"],
        target=dict(target_id="synthetic", sequence_sha256="a"*64, manifest_sha256="b"*64, reference_compound_id="c0"),
        ranking_rule="mean_binder_desc_top2_v1", results=rank_candidates(rows))
    toxicity = json.loads((ROOT / "contracts/examples/toxicity.not-run.json").read_text())
    template = toxicity["results"][0]
    toxicity["results"] = []
    toxicity["request_id"] = request["request_id"]
    for c, call in zip(request["compounds"], ["positive", "negative", "positive"]):
        r = deepcopy(template)
        r.update(compound_id=c["compound_id"], structure_id=c["structure_id"], status="ok", error=None)
        r["structural_evidence"].update({k:c[k] for k in ("canonical_smiles", "atom_mapped_smiles", "standardization_version")})
        r["assessment"].update(call=call, risk_score=.7 if call == "positive" else .2,
                                threshold=.5, score_kind="uncalibrated_score")
        toxicity["results"].append(r)
    return request, discovery, toxicity


class ScreeningTests(unittest.TestCase):
    def test_v3_schemas_are_valid(self):
        from jsonschema import Draft202012Validator
        for name in ('discovery-v3.schema.json','screening-report-v3.schema.json'):
            Draft202012Validator.check_schema(json.loads((ROOT/'contracts'/name).read_text()))

    def test_before_after_decisions_and_no_automatic_replacement(self):
        r, d, t = fixtures()
        report = combine_screening(r, d, t)
        self.assertEqual(report["discovery_shortlist"], ["c0", "c1"])
        self.assertEqual([x["follow_up"]["decision"] for x in report["results"]],
                         ["hold_for_liver_validation", "continue_target_validation", "not_shortlisted"])
        self.assertIsNone(report["comparison"]["disagreement"])
        self.assertEqual(report["policy_status"], "provisional")

    def test_missing_binding_is_unranked_not_low_priority(self):
        r, d, t = fixtures()
        d["results"][0].update(binding_probability=None, mean_binding_probability=None)
        rank_candidates(d["results"])
        report = combine_screening(r, d, t)
        self.assertEqual(report["results"][0]["follow_up"]["decision"], "discovery_incomplete")

    def test_failed_toxicity_keeps_shortlist_and_marks_incomplete(self):
        r, d, t = fixtures()
        t = screen_cli.failed_toxicity(r)
        report = combine_screening(r, d, t)
        self.assertEqual(report["results"][0]["follow_up"]["decision"], "safety_assessment_incomplete")
        self.assertEqual(report["discovery_shortlist"], ["c0", "c1"])

    def test_similarity_does_not_become_confidence_or_change_call(self):
        r, d, t = fixtures()
        for value in [0, 1, None]:
            t["results"][0]["assessment"]["applicability"]["value"] = value
            self.assertEqual(combine_screening(r,d,t)["results"][0]["follow_up"]["decision"], "hold_for_liver_validation")

    def test_missing_extra_duplicate_and_mismatched_records_rejected(self):
        for mutation in [lambda d:d["results"].pop(),
                         lambda d:d["results"].append(deepcopy(d["results"][0])),
                         lambda d:d["results"][0].update(compound_id="extra"),
                         lambda d:d["results"][0].update(structure_id="wrong"),
                         lambda d:d["results"][0].update(atom_mapped_smiles="[C:999]")]:
            r,d,t = fixtures(); mutation(d)
            with self.assertRaises(ContractValidationError): combine_screening(r,d,t)

    def test_corrupt_mean_and_ranking_rejected(self):
        for update in [dict(mean_binding_probability=.1), dict(rank=3), dict(shortlisted=False)]:
            r,d,t = fixtures(); d["results"][0].update(update)
            with self.assertRaises(ContractValidationError): combine_screening(r,d,t)

    def test_report_tampering_rejected(self):
        report = combine_screening(*fixtures())
        report["results"][0]["follow_up"]["decision"] = "continue_target_validation"
        with self.assertRaises(ContractValidationError): validate_screening_report(report)

    def test_html_escapes_untrusted_evidence_and_includes_membership(self):
        r,d,t = fixtures()
        t["results"][0]["warnings"] = ["<script>alert('bad')</script>"]
        output = render(combine_screening(r,d,t))
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("Training membership", output)

    def test_selection_membership_is_visible_in_summary_and_table(self):
        r,d,t=fixtures()
        t['results'][0]['provenance']['training_membership']='excluded'
        t['results'][0]['warnings'].append('Compound used for model selection and thresholding; not an unseen evaluation case.')
        report=combine_screening(r,d,t)
        self.assertIn('used for model selection and thresholding',summary(report))
        self.assertIn('used for model selection and thresholding',render(report).split('</table>')[0])

    def test_frozen_target_and_request_hashes(self):
        manifest = json.loads((ROOT/"demo/examples/abl1_experiment.json").read_text())
        import hashlib
        for key in ["request", "target"]:
            path = ROOT/"demo/examples"/manifest[key]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),manifest[key+"_sha256"])

    def test_model_python_symlink_preserves_venv(self):
        with tempfile.TemporaryDirectory() as temp:
            link=Path(temp)/"python"; link.symlink_to(sys.executable)
            with patch.object(screen_cli,"preflight",return_value=0) as check:
                screen_cli.main(["preflight","--request","r.json","--target","t.json","--output-dir",temp,"--model-python",str(link)])
                self.assertEqual(check.call_args[0][0].model_python,link)

    def test_pipeline_saves_discovery_before_dili_and_handles_reference_failure(self):
        from toxoracle_discovery.boltz2 import SETTINGS, BoltzError
        import hashlib
        for fails in [False, True]:
            r,d,t=fixtures()
            target=dict(schema_version="1.0", target_id="synthetic", reference_compound_id="c0",
                        sequence="ACDE",sequence_sha256=hashlib.sha256(b"ACDE").hexdigest(),inference_settings=SETTINGS)
            class Client:
                calls=0
                def predict(self,payload):
                    self.calls+=1
                    if fails: raise BoltzError("synthetic service failure")
                    return {"structures":[{"format":"mmcif","structure":"data_synthetic\n_atom_site.id 1\n"}],
                            "affinities":{"L1":{"affinity_probability_binary":[.8],"affinity_pic50":[6.]}}}
            client=Client()
            with tempfile.TemporaryDirectory() as temp:
                base=Path(temp); request_path=base/'r.json'; target_path=base/'t.json'; model=base/'model'
                request_path.write_text(json.dumps(r)); target_path.write_text(json.dumps(target)); model.write_text('synthetic')
                args=argparse.Namespace(command='run',request=request_path,target=target_path,model=model,
                    output_dir=base/'out',model_python=Path(sys.executable),cache_dir=None)
                def fake_model(args,action,request,output):
                    if action=='prepare': output.write_text(request.read_text())
                    else:
                        self.assertTrue((args.output_dir/'discovery.json').is_file())
                        output.write_text(json.dumps(t))
                with patch.object(screen_cli,'run_model',side_effect=fake_model),redirect_stdout(io.StringIO()):
                    status=screen_cli.execute(args,client)
                self.assertEqual(status,2 if fails else 0)
                self.assertEqual(client.calls,1 if fails else 3)
                report=json.loads((base/'out/combined.json').read_text())
                validate_screening_report(report)
                self.assertTrue((base/'out/summary.txt').is_file())
                with self.assertRaises(FileExistsError): screen_cli.execute(args,client)

    def test_invalid_structure_is_never_sent_to_vendor(self):
        from toxoracle_discovery.boltz2 import SETTINGS
        import hashlib
        r,d,t=fixtures()
        target=dict(schema_version='1.0',target_id='synthetic',reference_compound_id='c0',sequence='ACDE',
                    sequence_sha256=hashlib.sha256(b'ACDE').hexdigest(),inference_settings=SETTINGS)
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); (base/'request.json').write_text(json.dumps(r)); (base/'target.json').write_text(json.dumps(target)); (base/'model').write_text('synthetic')
            args=argparse.Namespace(command='run',request=base/'request.json',target=base/'target.json',model=base/'model',output_dir=base/'out',model_python=Path(sys.executable),cache_dir=None)
            from unittest.mock import Mock
            client=Mock()
            with patch.object(screen_cli,'run_model',side_effect=ValueError('invalid_smiles')),redirect_stdout(io.StringIO()):
                self.assertEqual(screen_cli.execute(args,client),2)
            client.predict.assert_not_called()
            rows=json.loads((base/'out/discovery.json').read_text())['results']
            self.assertTrue(all(row['status']=='invalid_input' for row in rows))


if __name__ == "__main__": unittest.main()
