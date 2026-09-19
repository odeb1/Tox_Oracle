import csv
import json
from pathlib import Path
import joblib
import numpy as np
import pytest
from rdkit import Chem
from jsonschema import validate
from toxicity.src.baseline import ROOT, MODEL, DATA, prepare_compound, fingerprint, split_data, fragments, predict


def test_identity_and_atom_maps():
    p=prepare_compound({'compound_id':'a','smiles':'CCO'})
    assert prepare_compound(p)==p
    bad=dict(p,structure_id='wrong')
    with pytest.raises(ValueError,match='identity_mismatch'):prepare_compound(bad)
    with pytest.raises(ValueError,match='atom_map_mismatch'):
        prepare_compound(dict(p,atom_mapped_smiles='[CH3:1][CH2:1][OH:2]'))
    shuffled=dict(p,atom_mapped_smiles='[OH:8][CH2:9][CH3:7]')
    assert prepare_compound(shuffled)['atom_mapped_smiles']==shuffled['atom_mapped_smiles']
    with pytest.raises(ValueError,match='invalid_smiles'):
        prepare_compound({'compound_id':'a','smiles':'CCO Alice'})


def test_scaffold_and_connectivity_splits():
    rows=list(csv.DictReader(DATA.open()))
    y=np.array([int(r['dili_label']) for r in rows])
    tr,va,te,g,method=split_data(rows,y)
    for a,b in [(tr,va),(tr,te),(va,te)]:
        assert not set(g[a]) & set(g[b])
        assert not {rows[i]['connectivity_group'] for i in a} & {rows[i]['connectivity_group'] for i in b}
    assert method=='scaffold_and_connectivity'
    assert all(set(y[s])=={0,1} for s in [tr,va,te])
    assert len(set(tr)|set(va)|set(te))==len(rows)


@pytest.fixture(scope='module')
def artifact():
    if not MODEL.exists():pytest.skip('Train baseline to run artifact checks')
    return joblib.load(MODEL)


def test_prediction_contract_failures_and_ids(artifact):
    p=prepare_compound({'compound_id':'ok','smiles':'CCO'})
    request={'schema_version':'2.0','request_id':'r','compounds':[p,{'compound_id':'bad','smiles':'not a molecule'},
        {'compound_id':'duplicate','smiles':'CCO'},{'compound_id':'duplicate','smiles':'CC'}]}
    out=predict(request,artifact)
    assert [r['compound_id'] for r in out['results']]==['ok','bad','duplicate','duplicate']
    assert [r['status'] for r in out['results']]==['ok','invalid_input','invalid_input','invalid_input']
    assert all(r['assessment']['risk_score'] is None for r in out['results'][1:])
    assert out['results'][0]['structural_evidence']['attribution_status']=='available'


def test_fragment_maps_resolve(artifact):
    p=prepare_compound({'compound_id':'x','smiles':'CCOc1ccccc1'})
    f,base=fragments(artifact['rf'],p,fingerprint(p['canonical_smiles']))
    ids={a.GetAtomMapNum() for a in Chem.MolFromSmiles(p['atom_mapped_smiles']).GetAtoms()}
    assert f and np.isfinite(base)
    assert all(set(row['atom_map_ids'])<=ids for row in f)


def test_cached_demo_is_heldout(artifact):
    req=json.loads((ROOT/'demo/examples/dili_request.json').read_text())
    validate(req,json.loads((ROOT/'contracts/request.schema.json').read_text()))
    allowed={artifact['rows'][i]['structure_id'] for i in artifact['test_indices']}
    assert all(c['structure_id'] in allowed for c in req['compounds'])


def test_invalid_id_types_return_diagnostic_record(artifact):
    out=predict({'schema_version':'2.0','request_id':'r','compounds':[{'compound_id':42,'smiles':'CCO'}]},artifact)
    assert out['results'][0]['compound_id'] is None
    assert out['results'][0]['status']=='invalid_input'


def test_shared_response_schema_for_valid_and_failed_compounds(artifact):
    good=prepare_compound({'compound_id':'good1','smiles':'CCO'})
    bad=dict(good,compound_id='bad1',canonical_smiles='invalid')
    result=predict({'schema_version':'2.0','request_id':'shared','compounds':[good,bad]},artifact)
    validate(result,json.loads((ROOT/'contracts/response.schema.json').read_text()))
    assert result['results'][1]['error']['code']=='invalid_smiles'
    assert result['results'][1]['structural_evidence']['canonical_smiles']=='invalid'
