import io
import json

import pytest

from toxoracle_app.rosalind import RosalindClient, RosalindError


def transport(model='gpt-rosalind-research',status='completed',text='Synthetic interpretation'):
    def call(request,timeout):
        body=json.loads(request.data)
        assert body['store'] is False
        assert request.full_url=='https://api.openai.com/v1/responses'
        assert 'tools' not in body
        return io.BytesIO(json.dumps(dict(model=model,status=status,id='test',output=[dict(type='message',content=[dict(type='output_text',text=text)])])).encode())
    return call


def test_callable_alias_with_different_identity_is_not_claimed_as_rosalind():
    client=RosalindClient(key='test',transport=transport(model='gpt-5.5-2026-04-23'))
    result=client.verify()
    assert result['verification']=='identity_unconfirmed'
    assert result['returned_model']=='gpt-5.5-2026-04-23'
    with pytest.raises(RosalindError):client.plan({})


def test_verified_interface_preserves_model_provenance_and_no_tools():
    client=RosalindClient(key='test',transport=transport())
    assert client.verify()['verification']=='verified'
    approved=dict(research_prompt='Question',target_id='test',request={'compounds':[{'compound_id':'c1'}]})
    result=client.plan(approved)
    assert result['requested_model']=='gpt-rosalind-research' and result['interpretation_only']


def test_model_cannot_be_silently_substituted_or_pointed_at_another_provider():
    client=RosalindClient(model='some-other-model',key='test',transport=lambda *a:pytest.fail('must not call'))
    assert not client.configuration()['configured']
    assert client.verify()['verification']=='rosalind_not_configured'


@pytest.mark.parametrize('status,text',[('incomplete','partial'),('completed','')])
def test_missing_or_partial_explanation_is_unavailable(status,text):
    client=RosalindClient(key='test',transport=transport(status=status,text=text))
    assert client.verify()['verification']!='verified'


def test_provider_errors_do_not_expose_secrets():
    def broken(*a,**kw):raise OSError('SECRET-KEY')
    client=RosalindClient(key='test',transport=broken)
    assert client.verify()['verification']=='rosalind_request_failed'
    assert 'SECRET' not in json.dumps(client.configuration())
