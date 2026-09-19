"""Evaluate synthetic fixtures and a real local handoff with networking disabled."""
import json
import socket
import time
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from privacy.engine import LocalDetector, detect, mask, ROOT
from privacy.server import create_app, ORIGIN


def no_network(*args,**kwargs):
    raise RuntimeError('Network disabled during privacy verification')


def main():
    cases=json.loads((Path(__file__).parent/'tests/synthetic_cases.json').read_text())
    detector=LocalDetector();results=[];tp=fp=fn=0
    started=time.monotonic()
    with patch.object(socket.socket,'connect',no_network),patch.object(socket,'getaddrinfo',no_network):
        for case in cases:
            text=case['text'];spans=detect(text,detector);redacted=mask(text,spans)
            actual=set()
            for span in spans:actual.update(range(span['start'],span['end']))
            expected=set();offsets={}
            for sensitive in case['sensitive']:
                start=text.index(sensitive,offsets.get(sensitive,0));end=start+len(sensitive)
                offsets[sensitive]=end;expected.update(range(start,end))
            ctp=len(expected&actual);cfp=len(actual-expected);cfn=len(expected-actual)
            tp+=ctp;fp+=cfp;fn+=cfn
            results.append(dict(id=case['id'],true_positive_characters=ctp,false_positive_characters=cfp,
                 missed_characters=cfn,preserved_all_scientific_values=all(s in redacted for s in case['preserve']),
                 detected_labels=sorted({s['label'] for s in spans})))
        with TestClient(create_app(detector,token='synthetic-test'),base_url=ORIGIN,
                        headers={'Origin':ORIGIN,'X-Session-Token':'synthetic-test'}) as client:
            sid=client.post('/api/session').json()['session_id']
            request=json.loads((ROOT/'demo/examples/dili_request.json').read_text())
            # Remove derived identities here to exercise the preparation handoff.
            records=[dict(compound_id=r['compound_id'],smiles=r['canonical_smiles'],
                          patient_name='Alice Morgan',patient_id='SYN-12345',
                          notes='Contact alice@example.com. Dose 10 mg.') for r in request['compounds']]
            r=client.post('/api/scan',json=dict(session_id=sid,enabled=True,format='json',content=json.dumps({'compounds':records})))
            if r.status_code!=200 or r.json().get('blocked'):
                raise RuntimeError('Real structured scan was blocked: '+str(r.json().get('blocked',r.json().get('error'))))
            data=dict(session_id=sid,scan_id=r.json()['scan_id'])
            assert client.post('/api/export',json=data).status_code==400
            fields=[f['field_id'] for f in r.json()['review_fields']]
            if fields:
                assert client.post('/api/approve',json=dict(data,approve=True)).status_code==400
            assert client.post('/api/approve',json=dict(data,approve=True,retain_fields=fields)).status_code==200
            exported=client.post('/api/export',json=dict(data,kind='toxicity')).json()
            assert all('patient_name' not in c for c in exported['compounds'])
            result=client.post('/api/predict',json=data)
            assert result.status_code==200 and all(r['status']=='ok' for r in result.json()['results'])
            client.post('/api/invalidate',json={'session_id':sid})
            assert client.post('/api/export',json=data).status_code==400
    report=dict(model_revision='7ffa9a043d54d1be65afb281eddf0ffbe629385b',
        metric='character-level coverage; includes rule supplementation; overlap counted once',
        precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None,
        true_positive_characters=tp,false_positive_characters=fp,missed_characters=fn,cases=results,
        real_local_handoff='passed',outbound_socket_connections='blocked during full evaluation',
        elapsed_seconds=round(time.monotonic()-started,2),
        limitations=['Ten hand-written synthetic examples, not a population benchmark or anonymity guarantee.',
                     'Input values and labels in the fixture are synthetic; no patient records used.',
                     'Character-level metrics may penalize punctuation and boundary differences.'])
    (ROOT/'evaluation/reports/privacy_synthetic.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
