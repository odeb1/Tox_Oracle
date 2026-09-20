"""Advanced routing, journal and pipeline tests. All service outputs are synthetic."""
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import argparse
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'discovery/src'))
from toxoracle_app import design_cli as design
from toxoracle_app.validation import ContractValidationError
from toxoracle_discovery.boltz2 import save


def request(mode='generate_screen'):
    return dict(schema_version='1.0',request_id='synthetic_design',mode=mode,target='ABL1',input_provenance='public',**({'count':2} if mode=='generate_screen' else {'compounds':[dict(compound_id='c1',smiles='CCCCCCCC')]}))


class DesignContractTests(unittest.TestCase):
    def test_schema_valid_and_intent_routing(self):
        from jsonschema import Draft202012Validator
        for name in ['design-request-v1.schema.json','generation-result-v1.schema.json']:
            Draft202012Validator.check_schema(json.loads((ROOT/'contracts'/name).read_text()))
        design.validate_design(request())
        design.validate_design(request('screen'))
        design.validate_design(dict(request(),seeds=[dict(compound_id='s',smiles='CCCCCCCC')]))
        bads=[dict(request(),mode='find'),dict(request(),target='ABL1 T315I'),dict(request(),target='EGFR'),
              dict(request(),compounds=[]),dict(request(),count=21),dict(request('screen'),count=2),
              {k:v for k,v in request('screen').items() if k!='compounds'},dict(request(),endpoint='http://untrusted')]
        for bad in bads:
            with self.assertRaises((ContractValidationError,ValueError)):design.validate_design(bad)

    def test_duplicate_ids_rejected_before_execution(self):
        r=request('screen');r['compounds']*=2
        with self.assertRaises(ValueError):design.validate_design(r)

    def test_missing_package_metadata_is_handled_by_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            save(folder / 'request.json', request())
            errors = io.StringIO()
            with patch.object(design.importlib.metadata, 'version',
                              side_effect=design.importlib.metadata.PackageNotFoundError('rdkit')):
                with redirect_stderr(errors):
                    status = design.main(['preflight', '--request', str(folder / 'request.json'),
                                          '--output-dir', str(folder / 'output')])
            self.assertEqual(status, 1)
            self.assertIn('Design stopped:', errors.getvalue())
            self.assertNotIn('Traceback', errors.getvalue())
            self.assertFalse((folder / 'output').exists())

    def test_resume_checks_identity_artifacts_and_pending_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);resolved={'synthetic':True}
            journal=design.Journal(p,resolved,False)
            save(p/'stage.json',{'ok':True});journal.checkpoint()
            design.Journal(p,resolved,True)
            with self.assertRaises(ValueError):design.Journal(p,{'synthetic':False},True)
            (p/'stage.json').write_text('{}')
            with self.assertRaises(ValueError):design.Journal(p,resolved,True)
            journal.checkpoint();journal.begin_call('generation','0')
            with self.assertRaises(ValueError):design.Journal(p,resolved,True)

    def test_resume_rejects_uncheckpointed_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);design.Journal(p,{},False)
            save(p/'unexpected.json',{})
            with self.assertRaises(ValueError):design.Journal(p,{},True)

    def test_lock_prevents_two_writers(self):
        with tempfile.TemporaryDirectory() as temp:
            with design.run_lock(Path(temp)):
                with self.assertRaises(FileExistsError):
                    with design.run_lock(Path(temp)):pass
            self.assertFalse((Path(temp)/'.run.lock').exists())

    def test_missing_lock_does_not_hide_workflow_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, 'original workflow failure'):
                with design.run_lock(Path(temp)):
                    (Path(temp) / '.run.lock').unlink()
                    raise RuntimeError('original workflow failure')


@unittest.skipUnless(importlib.util.find_spec('rdkit'),'Scientific environment required')
class DesignPipelineTests(unittest.TestCase):
    def setUp(self):
        self.ref=json.loads((ROOT/'demo/examples/abl1_request.json').read_text())['compounds'][0]
        self.generated=[dict(self.ref,compound_id='GEN_a'),dict(self.ref,compound_id='GEN_b')]

    def args(self,p,r):
        save(p/'request.json',r);(p/'model').write_text('synthetic model artifact')
        return argparse.Namespace(command='run',request=p/'request.json',output_dir=p/'out',model=p/'model',model_python=Path(sys.executable),cache_dir=None,resume=False)

    def boltz(self,fail=False):
        client=Mock()
        if fail:client.predict.side_effect=design.BoltzError('synthetic failure')
        else:client.predict.return_value={'structures':[{'format':'mmcif','structure':'data_synthetic\n_atom_site.id 1\n'}],
             'affinities':{'L1':{'affinity_probability_binary':[.8],'affinity_pic50':[6.]}}}
        return client

    def toxicity(self,args,action,inp,out):
        if action=='prepare':raise AssertionError('Input preprocessing mocked separately')
        self.assertTrue((args.output_dir/'discovery.json').is_file())
        r=design.load(inp)
        result=design.failed_toxicity(r)
        for row in result['results']:
            row.update(status='ok',error=None)
            row['assessment'].update(call='positive',risk_score=.8,threshold=.5,score_kind='uncalibrated_score')
        save(out,result)

    def mock_generate(self,args,resolved,journal,seeds,client):
        save(journal.output/'generation.json',{'status':'complete','synthetic':True})
        return deepcopy(self.generated)

    def test_generated_reference_is_not_ranked_and_dili_follows_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);args=self.args(p,request());client=self.boltz()
            def prepare(*a):save(args.output_dir/'input-ledger.json',[]);return []
            with patch.object(design,'prepare_inputs',side_effect=prepare),patch.object(design,'generate',side_effect=self.mock_generate),patch.object(design,'run_model',side_effect=self.toxicity),redirect_stdout(io.StringIO()):
                self.assertEqual(design.execute(args,boltz_client=client),0)
                args.resume=True
                self.assertEqual(design.execute(args,boltz_client=client),0)
            self.assertEqual(client.predict.call_count,3)
            report=design.load(args.output_dir/'combined.json')
            self.assertEqual(report['discovery_shortlist'],['GEN_a','GEN_b'])
            self.assertNotIn(self.ref['compound_id'],report['discovery_shortlist'])
            self.assertTrue(all(r['follow_up']['decision']=='hold_for_liver_validation' for r in report['results']))
            self.assertIn('unestablished', (args.output_dir/'design-report.html').read_text())

    def test_reference_failure_never_calls_generator(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);args=self.args(p,request())
            with patch.object(design,'prepare_inputs',return_value=[]),patch.object(design,'generate') as gen,redirect_stdout(io.StringIO()):
                self.assertEqual(design.execute(args,boltz_client=self.boltz(True)),2)
            gen.assert_not_called()
            self.assertTrue((args.output_dir/'design-report.html').is_file())

    def test_empty_generation_stops_at_five_batches(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);args=self.args(p,request());args.output_dir.mkdir()
            resolved=design.resolve(args);j=design.Journal(args.output_dir,resolved,False)
            client=Mock();client.generate.return_value={'status':'success','molecules':[]}
            rows=design.generate(args,resolved,j,[],client)
            self.assertEqual(rows,[])
            self.assertEqual(client.generate.call_count,5)
            self.assertEqual(design.load(args.output_dir/'generation.json')['status'],'partial')

    def test_generation_failure_has_no_automatic_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);args=self.args(p,request());args.output_dir.mkdir()
            resolved=design.resolve(args);j=design.Journal(args.output_dir,resolved,False)
            client=Mock();client.generate.side_effect=design.GenerationError('synthetic failure')
            self.assertEqual(design.generate(args,resolved,j,[],client),[])
            self.assertEqual(client.generate.call_count,1)
            self.assertFalse(j.data['pending_call'])

    def test_supplied_mode_does_not_generate_and_dili_failure_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);args=self.args(p,request('screen'))
            def prepare(*a):save(args.output_dir/'input-ledger.json',[{'status':'accepted'}]);return deepcopy(self.generated)
            with patch.object(design,'prepare_inputs',side_effect=prepare),patch.object(design,'generate') as gen,patch.object(design,'run_model',side_effect=ValueError('synthetic failure')),redirect_stdout(io.StringIO()):
                self.assertEqual(design.execute(args,boltz_client=self.boltz()),2)
            gen.assert_not_called()
            report=design.load(args.output_dir/'combined.json')
            self.assertEqual(report['results'][0]['follow_up']['decision'],'safety_assessment_incomplete')

    def test_partial_report_escapes_input_and_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);args=self.args(p,request());args.output_dir.mkdir()
            resolved=design.resolve(args);j=design.Journal(args.output_dir,resolved,False)
            j.data['errors']=[{'code':'<script>alert(1)</script>'}]
            design.report_workflow(args.output_dir,resolved,j)
            text=(args.output_dir/'design-report.html').read_text()
            self.assertNotIn('<script>',text)
            self.assertIn('&lt;script&gt;',text)

    def test_saved_batch_is_prepared_before_any_new_generation(self):
        from toxoracle_discovery.generation import make_template
        from rdkit import Chem
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);r=request();r['count']=1;args=self.args(p,r);args.output_dir.mkdir()
            resolved=design.resolve(args);j=design.Journal(args.output_dir,resolved,False)
            template=make_template(self.ref,cut_atoms=[6,5],retain_atom=5)
            mol={'smiles':'Cc1ccc(NC(=O)c2ccccc2)cc1Nc1nccc(-c2cccnc2)n1','score':.5}
            raw={'status':'success','molecules':[mol,mol,{'smiles':'invalid','score':.5}]}
            meta=dict(batch_index=0,execution_mode='cached',response_sha256=design.digest(raw),returned_count=3,requested_count=20)
            save(args.output_dir/'genmol/0/response.json',raw)
            save(args.output_dir/'generation-state.json',dict(templates=[template],batches=[meta],ledger=[],accepted=[],valid_structure_count=0,stopped=False))
            def prep(args,row,directory,request_id):
                m=Chem.MolFromSmiles(row['smiles']);smiles=Chem.MolToSmiles(m)
                for i,a in enumerate(m.GetAtoms(),1):a.SetAtomMapNum(i)
                return dict(compound_id=row['compound_id'],canonical_smiles=smiles,
                    atom_mapped_smiles=Chem.MolToSmiles(m),structure_id=hashlib.sha256(smiles.encode()).hexdigest(),standardization_version='dilirank_parent_v1')
            client=Mock()
            with patch.object(design,'prepare',side_effect=prep):
                rows=design.generate(args,resolved,j,[],client)
            client.generate.assert_not_called()
            self.assertEqual(len(rows),1)
            report=design.load(args.output_dir/'generation.json')
            self.assertEqual([x['status'] for x in report['ledger']],['selected','duplicate','rejected'])

    def test_unchanged_followup_is_reported_without_replacement(self):
        from test_screening import fixtures
        from toxoracle_app.screening import combine_screening
        r,d,t=fixtures()
        for row in t['results']:
            row['assessment'].update(call='negative',risk_score=.2)
        report=combine_screening(r,d,t)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);args=self.args(p,request());args.output_dir.mkdir()
            resolved=design.resolve(args);j=design.Journal(args.output_dir,resolved,False)
            design.report_workflow(args.output_dir,resolved,j,report)
            outer=design.load(args.output_dir/'design-report.json')
            self.assertEqual(outer['follow_up_change']['held_or_incomplete'],[])
            self.assertEqual(outer['follow_up_change']['discovery_shortlist'],['c0','c1'])
            self.assertIn('No shortlisted',outer['follow_up_change']['message'])
