"""Current-run dashboard adapters, using real saved public evidence offline."""
import hashlib
import json
from unittest.mock import patch

import pytest

from test_workspace import env, scan, approve, submit, finished
from toxoracle_app.molecular_evidence import molecule_svg, unique_features
from toxoracle_app.workspace_evidence import recorded_study
from toxoracle_app.workspace_results import candidate_evidence, model_context


def test_feature_groups_and_atom_highlights_share_teammate_rendering():
    report = recorded_study()['report']
    row = report['results'][0]
    evidence = row['toxicity_result']['structural_evidence']
    result = candidate_evidence(report, row['compound_id'])
    assert len(result['features']) == len({f['source_ref'] for f in evidence['fragments']})
    group = result['features'][0]
    mapped = candidate_evidence(report, row['compound_id'], group['source'], True)
    assert mapped['image'].startswith('data:image/svg+xml;base64,')
    assert mapped['image'] != result['image']
    assert group['atom_map_ids'] == sorted(set(group['atom_map_ids']))
    with pytest.raises(ValueError):
        molecule_svg('[CH3:1][OH:2]', [999])
    with pytest.raises(ValueError):
        candidate_evidence(report, row['compound_id'], 'unrecorded-feature')
    with pytest.raises(ValueError):
        candidate_evidence(report, 'unrecorded-candidate')


def test_ambiguous_hashed_features_retain_all_environments_without_double_counting():
    fragments = [dict(source_ref='bit1', fragment_id='a', contribution=.2,
                      atom_map_ids=[1, 2], mapping_ambiguous=True),
                 dict(source_ref='bit1', fragment_id='b', contribution=.2,
                      atom_map_ids=[3], mapping_ambiguous=True)]
    group = unique_features(fragments)[0]
    assert group['contribution'] == .2 and group['atom_map_ids'] == {1, 2, 3}
    fragments[1]['contribution'] = .3
    assert unique_features(fragments)[0]['contribution'] is None


def test_model_context_does_not_attribute_baseline_metrics_to_other_models():
    report = recorded_study()['report']
    assert model_context(report)['matching_method_and_data']
    report['results'][0]['toxicity_result']['provenance']['data_version'] = 'different-data'
    assert not model_context(report)['matching_method_and_data']


def test_results_api_local_validation_and_session_gate(env):
    client, sid, _, _ = env
    report = recorded_study()['report']
    payload = dict(session_id=sid, report=report, compound_id=report['results'][0]['compound_id'])
    with patch('urllib.request.urlopen', side_effect=AssertionError('No network in results views')):
        assert client.post('/api/results/evidence', json=payload).json()['image']
        assert client.post('/api/results/evidence', json={**payload, 'view':'model'}).json()['matching_method_and_data']
    assert client.post('/api/results/evidence', json={**payload, 'source':'not-recorded'}).status_code == 400
    assert client.post('/api/results/evidence', json={**payload, 'report':{}}).status_code == 400
    assert client.post('/api/results/evidence', json={**payload, 'session_id':'unowned'}).status_code != 200


def test_structure_download_ownership_integrity_and_path_boundary(env, tmp_path):
    client, sid, manager, _ = env
    reviewed = scan(client,sid).json()
    assert approve(client,sid,reviewed).status_code == 200
    response = submit(client,sid,reviewed).json()
    job = manager.owned(sid, response['job_id'])
    finished(manager)
    payload = dict(session_id=sid,job_id=job.job_id,compound_id='LT00107',index=0)
    path = job.directory/'science/combined.json'
    report = json.loads(path.read_text())
    row = next(r for r in report['results'] if r['compound_id']=='LT00107')
    artifact = row['discovery_result']['structures'][0]
    assert client.post('/api/results/structure',json=payload).status_code == 200
    other = client.post('/api/session').json()['session_id']
    assert client.post('/api/results/structure',json={**payload,'session_id':other}).status_code != 200
    assert client.post('/api/results/structure',json={**payload,'index':-1}).status_code == 400
    artifact['sha256'] = '0'*64
    path.write_text(json.dumps(report))
    assert client.post('/api/results/structure',json=payload).status_code == 400
    outside = tmp_path/'outside.cif';outside.write_text('not part of this run')
    artifact.update(uri=str(outside),sha256=hashlib.sha256(outside.read_bytes()).hexdigest())
    path.write_text(json.dumps(report))
    assert client.post('/api/results/structure',json=payload).status_code == 400


def test_recorded_pose_uses_verified_server_report_not_caller_paths(env, tmp_path):
    client, sid, _, _ = env
    saved = recorded_study()
    directory = tmp_path/'artifacts/runs'/saved['manifest']['source_run']
    directory.mkdir(parents=True)
    pose = directory/'pose.cif'
    pose.write_text('data_saved_pose\n')
    artifact = saved['report']['results'][0]['discovery_result']['structures'][0]
    artifact.update(uri=str(pose), sha256=hashlib.sha256(pose.read_bytes()).hexdigest())
    from toxoracle_app import web
    with patch.object(web, 'ROOT', tmp_path), patch('toxoracle_app.workspace_evidence.recorded_study',return_value=saved):
        payload = dict(session_id=sid, source='recorded',compound_id=saved['report']['results'][0]['compound_id'],index=0,
                       uri='/etc/passwd')
        response=client.post('/api/results/structure',json=payload)
        assert response.status_code == 200
        assert response.json()['content'] == 'data_saved_pose\n'
        assert response.json()['sha256'] == artifact['sha256']
        assert response.json()['format'] == 'mmcif'
        pose.write_text('changed')
        assert client.post('/api/results/structure',json=payload).status_code == 400
        assert client.post('/api/results/structure',json={**payload,'compound_id':'wrong-study'}).status_code == 400
