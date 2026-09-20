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
