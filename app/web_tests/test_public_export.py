"""Public scientific evidence must remain identical apart from artifact references."""
import hashlib
import json
from pathlib import Path
import pytest
from toxoracle_app.screening import validate_screening_report

ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('slug,expected', [('generated',18),('supplied',4)])
def test_export_contract_and_source_parity(slug,expected):
    folder=ROOT/'demo/public/studies'/slug
    manifest=json.loads((folder/'manifest.json').read_text())
    study=json.loads((folder/'study.json').read_text())
    report=study['report'];validate_screening_report(report)
    assert sum(r['discovery_result']['status']=='ok' for r in report['results'])==expected
    assert study['run']['assistant']['status']=='complete'
    assert len(report['discovery_shortlist'])==2
    for name,record in manifest['assets'].items():
        raw=(folder/name).read_bytes()
        assert len(raw)==record['bytes']
        assert hashlib.sha256(raw).hexdigest()==record['sha256']
        assert b'/Users/' not in raw and b'nvapi-' not in raw
    original=ROOT/'artifacts/web/runs'/manifest['source_run']/'science/combined.json'
    if original.exists():
        raw=original.read_bytes(); assert hashlib.sha256(raw).hexdigest()==manifest['source_report_sha256']
        source=json.loads(raw)
        for old,new in zip(source['results'],report['results']):
            for a,b in zip(old['discovery_result']['structures'],new['discovery_result']['structures']):
                assert Path(a['uri']).read_bytes()==(folder/b['uri']).read_bytes()
                a['uri']=b['uri']
            if old['discovery_result']['raw_response']:
                old['discovery_result']['raw_response']['uri']=new['discovery_result']['raw_response']['uri']
        assert source==report
    assert set(study['review']['audit'])=={'policy_version','model_revision','category_counts','reviewed_scientific_fields_retained'}


def test_complete_demo_cohort_preserves_source_and_scientific_decisions():
    import runpy
    module = runpy.run_path(str(ROOT/'scripts/export-demo-cohort.py'))
    folder = ROOT/'demo/public/studies/generated'
    source = json.loads((folder/'study.json').read_text())
    before = json.dumps(source, sort_keys=True)
    cohort = module['derive'](source)
    assert json.dumps(source, sort_keys=True) == before
    assert cohort == json.loads((folder/'cohort-study.json').read_text())
    assert cohort['report'] == json.loads((folder/'cohort-report.json').read_text())
    assert len(source['report']['results']) == 20
    assert len(cohort['report']['results']) == 18
    assert cohort['report']['discovery_shortlist'] == source['report']['discovery_shortlist']
    original = {r['compound_id']: r for r in source['report']['results']}
    for row in cohort['report']['results']:
        assert row == original[row['compound_id']]
        assert row['discovery_result']['status'] == row['toxicity_result']['status'] == 'ok'
        assert row['follow_up']['decision'] not in ['discovery_incomplete', 'safety_assessment_incomplete']
    ids = {r['compound_id'] for r in cohort['report']['results']}
    assert set(cohort['evidence']) == ids
    assert {c['compound_id'] for c in cohort['run']['candidates']} == ids
    assert cohort['run']['candidate_count'] == 18
    assert cohort['run']['assistant'] == source['run']['assistant']
    assert cohort['review'] == source['review']
    assert 'generation' not in cohort['run']
    completed = [e for e in cohort['run']['events'] if e['stage'] == 'candidate_finished']
    assert [e['completed'] for e in completed] == list(range(1,19))
    assert all(e['total'] == 18 and e['status'] == 'ok' for e in completed)
    assert {e['compound_id'] for e in completed} == ids
    ready = next(e for e in cohort['run']['events'] if e['stage'] == 'candidates_ready')
    assert {c['compound_id'] for c in ready['candidates']} == ids
    manifest = json.loads((folder/'manifest.json').read_text())
    assert manifest['presentation']['source_study_sha256'] == hashlib.sha256((folder/'study.json').read_bytes()).hexdigest()
    html = (folder/'cohort-report.html').read_text()
    for cid in set(original)-ids:
        assert cid not in html
