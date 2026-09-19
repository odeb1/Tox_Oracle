import json
import re
import pytest
from fastapi.testclient import TestClient
from privacy.engine import scan,PrivacyError,mask,toxicity_request,parse
from privacy.server import create_app,ORIGIN,TTL


class SyntheticDetector:
    """Deterministic test double; production has no mock/rules-only mode."""
    def detect(self,text):
        return [dict(start=m.start(),end=m.end(),label='private_person',detector='test') for m in re.finditer('Alice Morgan',text)]


def test_text_and_format_preservation():
    result=scan('Alice Morgan: alice@example.com; concentration 10 uM','text',SyntheticDetector())
    assert 'Alice' not in result['sanitized'] and 'alice@' not in result['sanitized']
    assert '10 uM' in result['sanitized']
    raw='compound_id,smiles,patient_id,dose,unit,notes\nc1,CCO,PT123,10,uM,Alice Morgan\n'
    result=scan(raw,'csv',SyntheticDetector())
    assert 'PT123' not in result['sanitized'] and 'patient_id' not in result['sanitized']
    req=toxicity_request(result)
    assert req['compounds'][0]['canonical_smiles']=='CCO'
    assert 'dose' not in req['compounds'][0]
    assert '10' in result['sanitized'] and 'uM' in result['sanitized']


def test_nested_metadata_and_headers():
    raw=json.dumps({'Alice Morgan':'anything','metadata':{'donor_id':12345,'note':'alice@example.com'}})
    r=scan(raw,'json',SyntheticDetector())
    assert 'Alice' not in r['sanitized'] and '12345' not in r['sanitized'] and 'alice@' not in r['sanitized']
    assert 'Alice' not in json.dumps(r['audit'])


def test_essential_flag_blocks_without_corrupting_structure():
    r=scan('[{"compound_id":"Alice Morgan","smiles":"CCO"}]','json',SyntheticDetector())
    assert r['blocked'] and 'Alice Morgan' in r['sanitized']


@pytest.mark.parametrize('content,format',[('{"a":1,"a":2}','json'),('x,y\n1','csv'),('x'*6001,'text'),('x','pdf'),('[NaN]','json')])
def test_bad_inputs(content,format):
    with pytest.raises(PrivacyError):scan(content,format,SyntheticDetector())


def test_overlap():
    assert mask('abcdef',[dict(start=0,end=3),dict(start=2,end=5)])=='[REDACTED]f'


def test_detector_failure_blocks():
    class Broken:
        def detect(self,text):raise PrivacyError('local_detector_failed')
    with pytest.raises(PrivacyError):scan('hello','text',Broken())


@pytest.fixture
def client():
    app=create_app(SyntheticDetector(),token='test-token')
    with TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Session-Token':'test-token'}) as client:
        yield client


def start(client):return client.post('/api/session').json()['session_id']


def scanned(client,sid):
    response=client.post('/api/scan',json=dict(session_id=sid,enabled=True,format='text',content='Alice Morgan dose 10 uM'))
    assert response.status_code==200,response.text
    return dict(session_id=sid,scan_id=response.json()['scan_id'])


def test_authorization_and_invalidation(client):
    sid=start(client); data=scanned(client,sid)
    assert client.post('/api/export',json=data).status_code==400
    assert client.post('/api/approve',json=dict(data,approve=True)).status_code==200
    r=client.post('/api/export',json=data)
    assert r.status_code==200 and 'Alice' not in r.text
    client.post('/api/invalidate',json={'session_id':sid})
    assert client.post('/api/export',json=data).status_code==400
    assert client.post('/api/approve',json=dict(data,approve=True)).status_code==400


def test_off_reset_and_cross_session(client):
    sid=start(client); data=scanned(client,sid)
    other=start(client)
    assert client.post('/api/approve',json=dict(data,session_id=other,approve=True)).status_code==400
    r=client.post('/api/scan',json={'session_id':sid,'enabled':False,'format':'text','content':'private'})
    assert r.status_code==400
    assert client.post('/api/export',json=data).status_code==400
    client.post('/api/reset',json={'session_id':sid})
    assert client.post('/api/export',json=data).status_code==400


def test_local_security(client):
    assert client.post('/api/session',headers={'X-Session-Token':'wrong'}).status_code==403
    assert client.post('/api/session',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/',headers={'Host':'evil.example'}).status_code==403
    assert client.get('/').headers['cache-control']=='no-store'


def test_expiry():
    now=[0.]
    with TestClient(create_app(SyntheticDetector(),token='t',clock=lambda:now[0]),base_url=ORIGIN,
                    headers={'Origin':ORIGIN,'X-Session-Token':'t'}) as c:
        sid=start(c);data=scanned(c,sid)
        now[0]=TTL+1
        assert c.post('/api/approve',json=dict(data,approve=True)).status_code==400


def test_scientific_retention_requires_separate_approval():
    class FlagSMILES(SyntheticDetector):
        def detect(self,text):
            return [dict(start=m.start(),end=m.end(),label='secret',detector='test') for m in re.finditer('CCO',text)]
    with TestClient(create_app(FlagSMILES(),token='t'),base_url=ORIGIN,
                    headers={'Origin':ORIGIN,'X-Session-Token':'t'}) as c:
        sid=start(c)
        r=c.post('/api/scan',json=dict(session_id=sid,enabled=True,format='json',
            content='[{"compound_id":"candidate_1","smiles":"CCO"}]')).json()
        assert not r['blocked'] and len(r['review_fields'])==1
        data=dict(session_id=sid,scan_id=r['scan_id'],approve=True)
        assert c.post('/api/approve',json=data).status_code==400
        assert c.post('/api/approve',json=dict(data,retain_fields=['unknown'])).status_code==400
        assert c.post('/api/approve',json=dict(data,retain_fields=['field_1'])).status_code==200
        out=c.post('/api/export',json=data).json()
        assert 'CCO' in out['content']
        assert out['audit']['reviewed_scientific_fields_retained']==1
        c.post('/api/invalidate',json={'session_id':sid})
        assert c.post('/api/export',json=data).status_code==400


def test_unvalidated_scientific_alias_cannot_be_retained():
    raw='[{"compound_id":"c1","canonical_smiles":"CCO","smiles":"Alice Morgan"}]'
    r=scan(raw,'json',SyntheticDetector())
    assert r['blocked'] and not r['review_fields']


def test_invalidating_inflight_scan():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered=threading.Event();release=threading.Event()
    class Slow:
        def detect(self,text):
            entered.set();release.wait(10);return []
    with TestClient(create_app(Slow(),token='t'),base_url=ORIGIN,
                    headers={'Origin':ORIGIN,'X-Session-Token':'t'}) as c:
        sid=start(c)
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(c.post,'/api/scan',json=dict(session_id=sid,enabled=True,format='text',content='example'))
            assert entered.wait(5)
            c.post('/api/invalidate',json={'session_id':sid})
            release.set()
            assert future.result().status_code==400


def test_errors_do_not_echo_payload(client,capsys):
    sid=start(client);secret='PRIVATE-PAYLOAD-12345'
    r=client.post('/api/scan',json=dict(session_id=sid,enabled=True,format='json',content=secret))
    assert r.status_code==400 and secret not in r.text
    assert secret not in capsys.readouterr().err


def test_unsupported_limit_and_no_origin(client):
    sid=start(client)
    r=client.post('/api/scan',json=dict(session_id=sid,enabled=True,format='text',content='x'*1_000_001))
    assert r.status_code==400
    with TestClient(create_app(SyntheticDetector(),token='t'),base_url=ORIGIN,headers={'X-Session-Token':'t'}) as c:
        assert c.post('/api/session').status_code==403
