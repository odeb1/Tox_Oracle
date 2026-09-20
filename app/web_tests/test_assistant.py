import io
import json
import urllib.error
from unittest.mock import patch

import pytest
from toxoracle_app.assistant import NvidiaAssistant, AssistantError, MODEL

APPROVED = dict(research_prompt='Screen these candidates against ABL1', target_id='ABL1',
                request={'compounds':[{'compound_id':'c1'},{'compound_id':'c2'}]})
PLAN = dict(supported=True,target_id='ABL1',candidate_ids=['c1','c2'],explanation='Screen approved candidates, freeze discovery, then assess DILI.')


def transport(plan=None, model=MODEL):
    def call(request, timeout):
        body=json.loads(request.data)
        assert request.full_url == 'https://integrate.api.nvidia.com/v1/chat/completions'
        message={'content':'Interface check'}
        if 'tools' in body:
            assert body['tools'][0]['function']['name']=='prepare_abl1_screening'
            assert 'canonical_smiles' not in body['messages'][1]['content']
            message={'tool_calls':[{'type':'function','function':{'name':'prepare_abl1_screening','arguments':json.dumps(plan or PLAN)}}]}
        return io.BytesIO(json.dumps(dict(model=model,choices=[dict(finish_reason='tool_calls' if 'tools' in body else 'stop',message=message)])).encode())
    return call


def test_verification_and_validated_bounded_tool():
    client=NvidiaAssistant(key='test-only',transport=transport())
    assert client.verify()['verification']=='verified'
    result=client.plan(APPROVED)
    assert result['supported'] and result['tool']=='prepare_abl1_screening'
    assert result['requested_model']==result['returned_model']==MODEL


@pytest.mark.parametrize('overrides',[{'target_id':'EGFR'},{'candidate_ids':['c1']},{'threshold':0.1},{'supported':'yes'},{'explanation':''}])
def test_plan_cannot_change_inputs_or_policy(overrides):
    client=NvidiaAssistant(key='test-only',transport=transport(dict(PLAN,**overrides)))
    with pytest.raises(AssistantError,match='assistant_invalid_plan'):client.plan(APPROVED)


def test_unsupported_question_preserves_clarification():
    client=NvidiaAssistant(key='test-only',transport=transport(dict(PLAN,supported=False,explanation='Only ABL1 screening is supported.')))
    assert client.plan(APPROVED)['supported'] is False


def test_unexpected_model_is_not_silently_accepted():
    assert NvidiaAssistant(key='test',transport=transport(model='other')).verify()['verification']=='assistant_identity_unconfirmed'


def test_rate_limit_is_safe_and_not_retried():
    calls=[]
    def limited(*args,**kwargs):
        calls.append(1)
        raise urllib.error.HTTPError('https://example.invalid',429,'SECRET',{},None)
    client=NvidiaAssistant(key='SECRET',transport=limited)
    assert client.verify()['verification']=='assistant_rate_limited'
    assert calls==[1] and 'SECRET' not in json.dumps(client.configuration())


def test_truncated_response_is_rejected():
    def incomplete(*args,**kwargs):
        return io.BytesIO(json.dumps(dict(model=MODEL,choices=[dict(finish_reason='length',message={'content':'partial'})])).encode())
    assert NvidiaAssistant(key='test',transport=incomplete).verify()['verification']=='assistant_incomplete'


def test_generation_plan_has_no_invented_candidate_ids_and_uses_generation_tool():
    captured = []
    def generate(request, timeout):
        body = json.loads(request.data); captured.append(body)
        name = body['tools'][0]['function']['name']
        assert name == 'prepare_abl1_generation'
        plan = dict(PLAN, candidate_ids=[], explanation='Generate from the documented fragment, screen, freeze, then assess DILI.')
        return io.BytesIO(json.dumps(dict(model=MODEL, choices=[dict(finish_reason='tool_calls', message=dict(tool_calls=[dict(type='function', function=dict(name=name, arguments=json.dumps(plan)))]))])).encode())
    approved = dict(APPROVED, workflow='generate_screen', request={'count':20}, research_prompt='Propose ABL1 candidates')
    assert NvidiaAssistant(key='test', transport=generate).plan(approved)['candidate_ids'] == []
    assert json.loads(captured[0]['messages'][1]['content'])['workflow'] == 'generate_screen'


def test_explanation_receives_discovery_and_toxicity_availability():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    report = json.loads((root/'demo/examples/abl1_recorded_workspace/report.json').read_text())
    captured = []
    def respond(request, timeout):
        body = json.loads(request.data)
        captured.append(json.loads(body['messages'][1]['content']))
        return io.BytesIO(json.dumps(dict(model=MODEL, choices=[dict(finish_reason='stop', message={'content':'Evidence interpretation.'})])).encode())
    NvidiaAssistant(key='test', transport=respond).explain(APPROVED, report)
    for evidence, original in zip(captured[0]['results'], report['results']):
        assert evidence['discovery_status'] == original['discovery_result']['status']
        assert evidence['toxicity_status'] == original['toxicity_result']['status']
