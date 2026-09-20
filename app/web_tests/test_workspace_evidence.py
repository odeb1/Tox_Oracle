import json
import shutil
from unittest.mock import patch

import pytest
from toxoracle_app.workspace_evidence import REPLAY, recorded_study, preview


def test_recorded_public_evidence_is_verified_without_network():
    with patch('urllib.request.urlopen', side_effect=AssertionError('Replay must never call providers')):
        data=recorded_study()
    assert data['mode']=='recorded' and not data['network_calls']
    assert len(data['candidates'])==4
    assert data['report']['discovery_shortlist']==['LT01248','LT00607']
    assert all(c['image'].startswith('data:image/svg+xml;base64,') for c in data['candidates'])


def test_modified_replay_fails_closed(tmp_path):
    shutil.copytree(REPLAY,tmp_path/'replay')
    p=tmp_path/'replay/report.json';p.write_text(p.read_text()+' ')
    with pytest.raises(ValueError,match='recorded_evidence_changed'):recorded_study(tmp_path/'replay')


def test_preview_reports_row_errors_without_fabricating_structures():
    result=preview([{'compound_id':'C1','smiles':'CCO'},{'compound_id':'C1','smiles':'CCO'},{'compound_id':'C3','smiles':'invalid'}])
    assert [r['status'] for r in result]==['valid','invalid','invalid']
    assert result[1]['row']==2 and 'image' not in result[2]


def test_replay_does_not_enter_legacy_streamlit_case_discovery():
    # Streamlit discovers */manifest.json as legacy v2 studies; this is v3 evidence.
    assert not (REPLAY/'manifest.json').exists()
    assert (REPLAY/'evidence-manifest.json').is_file()
