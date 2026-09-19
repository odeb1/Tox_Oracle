"""Offline GenMol transport and chemistry tests; vendor responses are synthetic."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'discovery/src'))
from toxoracle_discovery.generation import (GenerationError, GenMolClient, generate_batch,
    make_template, chemical_checks, diverse_subset, validate_response, parse_molecule)


class GenerationTransportTests(unittest.TestCase):
    def test_cache_is_exact_and_batch_index_prevents_collapsing_draws(self):
        template={'template_id':'synthetic','safe_input':'[*{20-30}]'}
        client=Mock()
        client.generate.return_value={'status':'success','molecules':[{'smiles':'CCCCCCCC','score':.5}]}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            _,meta=generate_batch(template,0,p/'a',client,cache=p/'cache')
            _,cached=generate_batch(template,0,p/'b',client,cache=p/'cache')
            self.assertEqual(cached['execution_mode'],'cached')
            generate_batch(template,1,p/'c',client,cache=p/'cache')
            self.assertEqual(client.generate.call_count,2)
            path=p/'cache'/(meta['cache_key']+'.json')
            raw=json.loads(path.read_text());raw['response']['molecules']=[]
            path.write_text(json.dumps(raw))
            with self.assertRaises(GenerationError):generate_batch(template,0,p/'d',client,cache=p/'cache')
            self.assertEqual(client.generate.call_count,2)

    def test_failure_and_oversized_response_rejected(self):
        for raw in [None,[],{'status':'failed','error':'do not expose'}, {'status':'success','molecules':[{},{}]},
                    {'status':'success','molecules':[],'score':float('nan')}]:
            with self.assertRaises(GenerationError):validate_response(raw,1)
        self.assertEqual(validate_response({'status':'success','molecules':[]},20),[])

    def test_credentials_missing_and_transport_errors_do_not_leak(self):
        from urllib.error import HTTPError
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(GenerationError):GenMolClient().generate({})
        with patch.dict('os.environ',{'NVIDIA_API_KEY':'synthetic-secret'},clear=True),patch('toxoracle_discovery.generation.urlopen',side_effect=HTTPError('url',401,'sensitive body',{},None)):
            with self.assertRaises(GenerationError) as exc:GenMolClient().generate({})
            self.assertNotIn('sensitive',str(exc.exception))
            self.assertNotIn('synthetic-secret',str(exc.exception))


@unittest.skipUnless(importlib.util.find_spec('rdkit'),'Scientific environment required')
class GenerationChemistryTests(unittest.TestCase):
    def setUp(self):
        self.seed=json.loads((ROOT/'demo/examples/abl1_request.json').read_text())['compounds'][0]
        self.template=make_template(self.seed,cut_atoms=[6,5],retain_atom=5)

    def test_template_reconstructs_seed_and_requires_attachment(self):
        from rdkit import Chem
        full=Chem.MolFromSmiles(self.template['reconstruction_safe'])
        self.assertEqual(Chem.MolToSmiles(full),self.seed['canonical_smiles'])
        self.assertTrue(self.template['safe_input'].startswith('N4'))
        chemical_checks(self.seed['canonical_smiles'],self.template)
        with self.assertRaises(GenerationError):chemical_checks('Cc1ccc(N)cc1Nc1nccc(-c2cccnc2)n1',self.template)
        with self.assertRaises(GenerationError):chemical_checks('CCCCCCCC',self.template)

    def test_invalid_mixture_radical_and_stereochemistry(self):
        for s in ['invalid','CC.CCCCCCC','[Na+]','[CH2]CCCCCCC','CCCCCCCC name']:
            with self.assertRaises(GenerationError):parse_molecule(s)
        self.assertTrue(chemical_checks('CCCCCC(O)CC'))
        self.assertFalse(chemical_checks('CCCCC[C@H](O)CC'))

    def test_diversity_is_deterministic_and_not_vendor_score_order(self):
        rows=[dict(compound_id=str(i),structure_id=str(i),canonical_smiles=s) for i,s in enumerate(['CCCCCCCC','c1ccccc1CC','CCCCCCCCC'])]
        a=diverse_subset(rows,2)
        b=diverse_subset(list(reversed(rows)),2)
        self.assertEqual(a,b)
        self.assertEqual([r['compound_id'] for r in a],['0','1'])

    def test_user_seed_cut_is_deterministic_and_unsupported_ring_fails(self):
        self.assertEqual(make_template(self.seed),make_template(self.seed))
        with self.assertRaises(GenerationError):make_template(dict(self.seed,canonical_smiles='c1ccccc1'))
