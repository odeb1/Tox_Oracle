"""Offline integration fixtures, never scientific evidence or a production mock mode."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from privacy.engine import PrivacyError
from toxoracle_app import screen_cli
from toxoracle_app.screening import validate_screening_report
from toxoracle_app.web import ORIGIN, create_app
from toxoracle_app.workspace_jobs import CachedOnlyClient, JobManager, WorkspaceConfig, WorkspaceError, check_execution

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = json.loads((ROOT / "demo/examples/abl1_request.json").read_text())
TARGET = json.loads((ROOT / "discovery/configs/targets/abl1.json").read_text())


class Detector:
    def detect(self, text):
        return []  # Only an injected test double; production always requires OPF.


class SyntheticClient:
    calls = 0
    def predict(self, payload):
        self.calls += 1
        return {"structures": [{"format": "mmcif", "structure": "data_synthetic\n_atom_site.id 1\n"}],
                "confidence_scores": [.75],
                "affinities": {"L1": {"affinity_probability_binary": [.95 - self.calls * .1], "affinity_pic50": [6.]}}}


def synthetic_model(args, action, request_path, output):
    if action == "prepare":
        output.write_text(request_path.read_text())
        return
    assert (args.output_dir / "discovery.json").is_file(), "DILI must follow the frozen discovery artifact"
    request = json.loads(request_path.read_text())
    response = screen_cli.failed_toxicity(request)
    for index, row in enumerate(response["results"]):
        row.update(status="ok", error=None)
        row["assessment"].update(call="positive" if index == 0 else "negative",
            risk_score=.8 if index == 0 else .2, threshold=.5, score_kind="uncalibrated_score")
        row["warnings"] = ["Synthetic interface test only; no scientific inference ran."]
    output.write_text(json.dumps(response))


def runner(args, **kwargs):
    kwargs["client"] = SyntheticClient()
    with patch.object(screen_cli, "run_model", side_effect=synthetic_model):
        return screen_cli.execute(args, **kwargs)


@pytest.fixture
def env(tmp_path):
    model = tmp_path / "test-model"
    model.write_text("Synthetic fixture, not a trained model")
    config = WorkspaceConfig(tmp_path / "runs", model, Path(sys.executable), tmp_path / "cache")
    manager = JobManager(config, runner=runner)
    app = create_app(config, detector=Detector(), token="test", manager=manager, preflight=lambda *a: None)
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN, "X-Session-Token": "test"}) as client:
        sid = client.post("/api/session").json()["session_id"]
        yield client, sid, manager, config


def scan(client, sid, **overrides):
    data = dict(session_id=sid, target_id=TARGET["target_id"], mode="live", use_assistant=False,
                format="json", content=json.dumps(EXAMPLE), research_prompt="Review ABL1; contact researcher@example.com")
    data.update(overrides)
    return client.post("/api/study/scan", json=data)


def approve(client, sid, result):
    return client.post("/api/approve", json=dict(session_id=sid, scan_id=result["scan_id"],
        approve=True, retain_fields=[f["field_id"] for f in result["review_fields"]]))


def submit(client, sid, result, **overrides):
    return client.post("/api/study/submit", json=dict(session_id=sid, scan_id=result["scan_id"], **overrides))


def finished(manager):
    manager.pool.submit(lambda: None).result(timeout=15)


def test_full_approved_flow_freezes_discovery_and_changes_follow_up(env):
    client, sid, manager, config = env
    response = scan(client, sid)
    assert response.status_code == 200, response.text
    result = response.json()
    assert "researcher@example.com" not in result["sanitized"]
    assert submit(client, sid, result).status_code == 400
    assert not config.runs.exists()
    assert approve(client, sid, result).status_code == 200
    job = submit(client, sid, result).json()
    finished(manager)
    body = client.post("/api/run/report", json=dict(session_id=sid, job_id=job["job_id"])).json()
    report, run = body["report"], body["run"]
    validate_screening_report(report)
    assert run["status"] == "complete"
    assert report["results"][0]["follow_up"]["decision"] == "hold_for_liver_validation"
    assert report["results"][1]["follow_up"]["decision"] == "continue_target_validation"
    assert run["shortlist"] == report["discovery_shortlist"]
    stages = [e["stage"] for e in run["events"]]
    assert stages.index("shortlist_frozen") < stages.index("toxicity") < stages.index("reporting")
    directory = config.runs / job["job_id"]
    assert run["discovery_sha256"] == hashlib.sha256((directory / "science/discovery.json").read_bytes()).hexdigest()
    assert all("researcher@example.com" not in f.read_text() for f in directory.rglob("*.json"))
    assert "snapshot" not in (directory / "approved.json").read_text()
    assert (directory / "approved.json").stat().st_mode & 0o077 == 0


def test_settings_cannot_be_overridden_at_submission_and_retries_are_idempotent(env):
    client, sid, manager, _ = env
    result = scan(client, sid).json()
    approve(client, sid, result)
    one = submit(client, sid, result, mode="cached", use_assistant=True, target_id="forged").json()
    two = submit(client, sid, result).json()
    assert one["job_id"] == two["job_id"]
    assert one["mode"] == "live" and one["target_id"] == TARGET["target_id"]
    assert one["assistant"]["status"] == "off"
    finished(manager)
    assert len(manager.jobs) == 1


def test_edit_and_malformed_rescan_revoke_approval(env):
    client, sid, manager, _ = env
    result = scan(client, sid).json(); approve(client, sid, result)
    assert scan(client, sid, content="invalid JSON").status_code == 400
    assert submit(client, sid, result).status_code == 400
    result = scan(client, sid).json(); approve(client, sid, result)
    client.post("/api/invalidate", json={"session_id": sid})
    assert submit(client, sid, result).status_code == 400
    assert not manager.jobs


def test_cross_session_read_cancel_download_and_approve_are_denied(env):
    client, sid, manager, _ = env
    result = scan(client, sid).json(); approve(client, sid, result)
    job = submit(client, sid, result).json(); finished(manager)
    other = client.post("/api/session").json()["session_id"]
    for path in ("status", "report", "cancel", "download"):
        assert client.post("/api/run/" + path, json=dict(session_id=other, job_id=job["job_id"], kind="report")).status_code == 400
    assert approve(client, other, result).status_code == 400
    assert client.post("/api/workspace", json={"session_id": other}).json()["runs"] == []


@pytest.mark.parametrize("headers", [{"Host":"evil.example"},{"Origin":"https://evil.example"},{"X-Session-Token":"wrong"}])
def test_workflow_routes_keep_gateway_security(env, headers):
    client, sid, *_ = env
    assert client.post("/api/study/submit", json={"session_id":sid}, headers=headers).status_code == 403


@pytest.mark.parametrize("origin", ["http://0.0.0.0:8766","https://127.0.0.1:8766","http://localhost:8766","http://127.0.0.1:8766/path"])
def test_factory_rejects_non_loopback_or_ambiguous_origin(origin):
    from privacy.server import create_app as gateway
    with pytest.raises(ValueError): gateway(origin=origin)


def test_target_reference_structure_and_offline_options_are_enforced(env):
    client, sid, *_ = env
    assert scan(client,sid,target_id="user_supplied").json()["error"] == "unsupported_target"
    assert scan(client,sid,mode="cached",use_assistant=True).json()["error"] == "cached_mode_is_offline"
    request=deepcopy(EXAMPLE); request["compounds"] = request["compounds"][1:]
    assert scan(client,sid,content=json.dumps(request)).json()["error"] == "reference_required"
    request["compounds"][0]["compound_id"] = "LT00107"
    assert scan(client,sid,content=json.dumps(request)).json()["error"] == "reference_identity_mismatch"


def test_duplicate_candidates_and_csv_input(env):
    client, sid, *_ = env
    request=deepcopy(EXAMPLE); request["compounds"].append(request["compounds"][0])
    result=scan(client,sid,content=json.dumps(request)).json()
    assert result["blocked"] and "study" not in result
    content="compound_id,smiles\n"+"\n".join(c["compound_id"]+","+c["canonical_smiles"] for c in EXAMPLE["compounds"])
    result=scan(client,sid,content=content,format="csv")
    assert result.status_code==200 and result.json()["study"]["request"]["compounds"]==EXAMPLE["compounds"]


def test_gateway_generic_scan_cannot_become_a_workflow(env):
    client, sid, *_=env
    result=client.post('/api/scan',json=dict(session_id=sid,enabled=True,format='json',content=json.dumps(EXAMPLE))).json()
    approve(client,sid,result)
    assert submit(client,sid,result).json()['error']=='study_review_required'


def test_approval_revoked_during_preflight_stops_launch(tmp_path):
    entered,release=threading.Event(),threading.Event()
    def slow(*args):entered.set();assert release.wait(10)
    manager=JobManager(WorkspaceConfig(runs=tmp_path/'runs'),runner=runner)
    app=create_app(detector=Detector(),token='t',manager=manager,preflight=slow)
    with TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Session-Token':'t'}) as client:
        sid=client.post('/api/session').json()['session_id']
        result=scan(client,sid).json();approve(client,sid,result)
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(submit,client,sid,result)
            assert entered.wait(5)
            client.post('/api/invalidate',json={'session_id':sid});release.set()
            assert pending.result().status_code==400
        assert not manager.jobs


def test_cancel_before_discovery_prevents_later_operations(env):
    client,sid,manager,_=env
    entered,release=threading.Event(),threading.Event()
    def slow_runner(args,**kwargs):
        entered.set();assert release.wait(10)
        return runner(args,**kwargs)
    manager.runner=slow_runner
    result=scan(client,sid).json();approve(client,sid,result)
    job=submit(client,sid,result).json();assert entered.wait(5)
    client.post('/api/run/cancel',json=dict(session_id=sid,job_id=job['job_id']))
    release.set();finished(manager)
    state=manager.owned(sid,job['job_id']).snapshot()
    assert state['status']=='cancelled' and not state['report_available']
    assert not any(e['stage']=='toxicity' for e in state['events'])
    manifest=json.loads((manager.owned(sid,job['job_id']).directory/'science/run.json').read_text())
    assert manifest['status']=='cancelled'


def test_cache_miss_cannot_contact_nvidia(env):
    _,_,_,config=env
    with patch('subprocess.run') as process:
        process.return_value.returncode=0
        with pytest.raises(WorkspaceError,match='complete_cache_required'):
            check_execution(config,EXAMPLE,TARGET,'cached')
    from toxoracle_discovery.boltz2 import BoltzError
    with pytest.raises(BoltzError,match='no network fallback'):CachedOnlyClient().predict({})


def test_failure_records_no_exception_text_or_false_results(env):
    client,sid,manager,_=env
    def broken(*args,**kwargs):raise RuntimeError('SECRET-INPUT-and-credential')
    manager.runner=broken
    result=scan(client,sid).json();approve(client,sid,result)
    job=submit(client,sid,result).json();finished(manager)
    state=manager.owned(sid,job['job_id']).snapshot()
    assert state['status']=='failed' and not state['report_available']
    assert 'SECRET' not in json.dumps(state)


def test_dili_failure_returns_partial_report_with_original_shortlist(env):
    client,sid,manager,_=env
    def fail_predict(args,action,request,output):
        if action=='predict':raise ValueError('Synthetic DILI failure')
        return synthetic_model(args,action,request,output)
    def partial_runner(args,**kwargs):
        kwargs['client']=SyntheticClient()
        with patch.object(screen_cli,'run_model',side_effect=fail_predict):
            return screen_cli.execute(args,**kwargs)
    manager.runner=partial_runner
    result=scan(client,sid).json();approve(client,sid,result)
    job=submit(client,sid,result).json();finished(manager)
    body=client.post('/api/run/report',json=dict(session_id=sid,job_id=job['job_id'])).json()
    assert body['run']['status']=='partial'
    assert body['report']['discovery_shortlist']==body['run']['shortlist']
    assert all(row['toxicity_result']['assessment']['risk_score'] is None for row in body['report']['results'])
    assert body['report']['results'][0]['follow_up']['decision']=='safety_assessment_incomplete'


def test_stop_after_freeze_preserves_shortlist_and_never_starts_dili(env):
    client,sid,manager,_=env
    def stop_at_freeze(args,**kwargs):
        callback=kwargs['progress']
        def progress(event):
            callback(event)
            if event['stage']=='shortlist_frozen':
                next(iter(manager.jobs.values())).stop.set()
        kwargs['progress']=progress
        return runner(args,**kwargs)
    manager.runner=stop_at_freeze
    result=scan(client,sid).json();approve(client,sid,result)
    job=submit(client,sid,result).json();finished(manager)
    saved=manager.owned(sid,job['job_id'])
    assert saved.snapshot()['status']=='cancelled'
    assert saved.snapshot()['shortlist']==['LT00107','LT01248']
    assert not (saved.directory/'science/toxicity.json').exists()


def test_altered_discovery_artifact_cannot_be_published(env):
    client,sid,manager,_=env
    def tampering_runner(args,**kwargs):
        status=runner(args,**kwargs)
        path=args.output_dir/'discovery.json'
        path.write_text(path.read_text()+' ')
        return status
    manager.runner=tampering_runner
    result=scan(client,sid).json();approve(client,sid,result)
    job=submit(client,sid,result).json();finished(manager)
    saved=manager.owned(sid,job['job_id']).snapshot()
    assert saved['status']=='failed' and not saved['report_available']


def test_report_import_validates_policy_and_never_runs_science(env):
    client,sid,manager,_=env
    result=scan(client,sid).json();approve(client,sid,result)
    job=submit(client,sid,result).json();finished(manager)
    report=json.loads((manager.owned(sid,job['job_id']).directory/'science/combined.json').read_text())
    assert client.post('/api/report/inspect',json=dict(session_id=sid,content=json.dumps(report))).status_code==200
    report['results'][0]['follow_up']['decision']='continue_target_validation'
    assert client.post('/api/report/inspect',json=dict(session_id=sid,content=json.dumps(report))).status_code==400
    assert len(manager.jobs)==1


def test_download_does_not_accept_paths(env):
    client,sid,manager,_=env
    result=scan(client,sid).json();approve(client,sid,result)
    job=submit(client,sid,result).json();finished(manager)
    assert client.post('/api/run/download',json=dict(session_id=sid,job_id=job['job_id'],kind='../../.env')).status_code==400


def test_production_detector_is_fail_closed(env):
    client,sid,manager,_=env
    with patch('privacy.engine.LocalDetector.detect',side_effect=PrivacyError('local_detector_failed')):
        app=create_app(token='t')
        with TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Session-Token':'t'}) as c:
            s=c.post('/api/session').json()['session_id']
            assert scan(c,s).json()['error']=='local_detector_failed'
            assert not app.state.jobs.jobs


def test_failed_planning_requires_explicit_idempotent_continuation(env):
    from toxoracle_app.assistant import AssistantError
    client,sid,manager,_=env
    class Broken:
        def plan(self,approved):raise AssistantError('assistant_rate_limited')
    manager.assistant=Broken()
    result=scan(client,sid).json();approve(client,sid,result)
    # The test injects assistant choice into the trusted, approved snapshot before submission.
    result['study']['use_assistant']=True
    job=manager.submit(sid,result,TARGET);finished(manager)
    assert job.snapshot()['status']=='awaiting_plan'
    assert not (job.directory/'science').exists()
    continued=client.post('/api/run/continue',json=dict(session_id=sid,job_id=job.job_id))
    assert continued.status_code==200
    assert client.post('/api/run/continue',json=dict(session_id=sid,job_id=job.job_id)).json()['job_id']==job.job_id
    finished(manager)
    assert job.snapshot()['status']=='complete'
    assert job.snapshot()['assistant_override']=='researcher_selected_fixed_protocol'


def test_unsupported_plan_cannot_be_bypassed_or_start_science(env):
    client,sid,manager,_=env
    class Unsupported:
        def plan(self,approved):return dict(supported=False,text='Only ABL1 is supported.')
    manager.assistant=Unsupported()
    result=scan(client,sid).json();approve(client,sid,result);result['study']['use_assistant']=True
    job=manager.submit(sid,result,TARGET);finished(manager)
    assert job.snapshot()['status']=='awaiting_plan' and not job.snapshot()['can_continue']
    assert client.post('/api/run/continue',json=dict(session_id=sid,job_id=job.job_id)).status_code==400
    assert not (job.directory/'science').exists()
    assert client.post('/api/run/cancel',json=dict(session_id=sid,job_id=job.job_id)).json()['status']=='cancelled'


def test_recorded_endpoint_does_not_submit_a_job(env):
    client,sid,manager,_=env
    response=client.post('/api/recorded',json=dict(session_id=sid))
    assert response.status_code==200 and response.json()['mode']=='recorded'
    assert not manager.jobs


def test_public_example_uses_minimal_csv_and_preserves_prepared_identities(env):
    client,sid,*_=env
    example=client.post('/api/example',json=dict(session_id=sid)).json()
    assert example['format']=='csv' and 'structure_id' not in example['content']
    result=scan(client,sid,content=example['content'],format=example['format']).json()
    assert result['study']['request']['compounds']==EXAMPLE['compounds']
    assert len(result['outbound']['boltz2'])==4 and result['outbound']['assistant'] is None
    assert result['outbound']['boltz2'][0]['payload']['polymers'][0]['sequence']==TARGET['sequence']


def test_target_only_review_needs_no_dataset_and_freezes_bounded_generation(env):
    client, sid, manager, _ = env
    response = scan(client, sid, content='', research_prompt='Propose drug candidates for human ABL1')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['study']['workflow'] == 'generate_screen'
    assert result['study']['request']['count'] == 20
    assert 'compounds' not in result['study']['request']
    assert result['outbound']['generation']['max_batches'] == 5
    assert result['outbound']['generated_screening']['max_generated_candidates'] == 20
    assert not manager.jobs
    assert submit(client, sid, result).status_code == 400


@pytest.mark.parametrize('prompt', ['Propose candidates for EGFR', 'Propose molecules', 'Design ABL1 T315I inhibitors'])
def test_prompt_target_is_not_silently_substituted(env, prompt):
    client, sid, *_ = env
    assert scan(client, sid, content='', research_prompt=prompt).json()['error'] == 'target_preparation_required'


def generated_runner(args, **kwargs):
    """Synthetic generator only; execute actual reference, scoring, freeze and join code."""
    from toxoracle_app import design_cli as design
    def proposals(args, resolved, journal, seeds, client):
        journal.emit('generating', batch=1, accepted=0, requested=20)
        design.save(args.output_dir / 'generation.json', dict(status='complete', synthetic=True))
        return [dict(c, compound_id='GEN_'+str(i)) for i, c in enumerate(EXAMPLE['compounds'][1:3])]
    with patch.object(design, 'generate', side_effect=proposals), patch.object(design, 'run_model', side_effect=synthetic_model):
        kwargs['boltz_client'] = SyntheticClient()
        return design.execute(args, **kwargs)


def test_generation_web_run_has_separate_reference_frozen_shortlist_and_export(env):
    client, sid, manager, _ = env
    manager.design_runner = generated_runner
    result = scan(client, sid, content='', research_prompt='Propose ABL1 candidates').json()
    approve(client, sid, result)
    first = submit(client, sid, result).json()
    assert submit(client, sid, result).json()['job_id'] == first['job_id']
    finished(manager)
    job = manager.owned(sid, first['job_id']); state = job.snapshot()
    assert state['status'] == 'complete', state
    assert state['candidate_count'] == 2
    assert state['shortlist'] == ['GEN_0', 'GEN_1']
    assert TARGET['reference_compound_id'] not in state['shortlist']
    stages = [e['stage'] for e in state['events']]
    assert stages.index('reference') < stages.index('generating') < stages.index('shortlist_frozen') < stages.index('toxicity')
    for kind in ('report', 'html'):
        response = client.post('/api/run/download', json=dict(session_id=sid, job_id=job.job_id, kind=kind))
        assert response.status_code == 200
    html = client.post('/api/run/download', json=dict(session_id=sid, job_id=job.job_id, kind='html')).json()
    assert 'design-report.html' in html['filename']


def test_cancel_generation_at_freeze_never_runs_dili(env):
    client, sid, manager, _ = env
    def stop(args, **kwargs):
        callback = kwargs['progress']
        def event(e):
            callback(e)
            if e['stage'] == 'shortlist_frozen':
                next(iter(manager.jobs.values())).stop.set()
        kwargs['progress'] = event
        return generated_runner(args, **kwargs)
    manager.design_runner = stop
    result = scan(client, sid, content='', research_prompt='Propose ABL1 candidates').json()
    approve(client, sid, result)
    submitted = submit(client, sid, result).json(); finished(manager)
    job = manager.owned(sid, submitted['job_id'])
    assert job.snapshot()['status'] == 'cancelled'
    assert not (job.directory/'science/toxicity.json').exists()
    assert json.loads((job.directory/'science/workflow.json').read_text())['status'] == 'cancelled'


def test_cached_generation_client_cannot_fall_back_to_network():
    from toxoracle_discovery.generation import GenerationError
    with pytest.raises(GenerationError, match='no network fallback'):
        CachedOnlyClient().generate({})


def test_generation_approval_is_revoked_when_dataset_changes(env):
    client, sid, manager, _ = env
    generated = scan(client, sid, content='', research_prompt='Propose ABL1 candidates').json()
    approve(client, sid, generated)
    supplied = scan(client, sid).json()
    assert supplied['study']['workflow'] == 'screen'
    assert submit(client, sid, generated).status_code == 400
    assert not manager.jobs


def test_generation_reference_failure_publishes_no_false_assessment(env):
    from toxoracle_app import design_cli as design
    from toxoracle_discovery.boltz2 import BoltzError
    client, sid, manager, _ = env
    class FailedReference:
        def predict(self, payload): raise BoltzError('synthetic reference failure')
    def fail(args, **kwargs):
        kwargs['boltz_client'] = FailedReference()
        with patch.object(design, 'generate') as generator:
            status = design.execute(args, **kwargs)
            generator.assert_not_called()
            return status
    manager.design_runner = fail
    result = scan(client, sid, content='', research_prompt='Propose ABL1 candidates').json()
    approve(client, sid, result)
    run = submit(client, sid, result).json(); finished(manager)
    state = manager.owned(sid, run['job_id']).snapshot()
    assert state['status'] == 'partial' and not state['report_available']
    assert state['shortlist'] is None
    assert state['error'] == 'generation_no_assessment'


def test_prompt_only_api_does_not_need_target_selector_or_dataset_metadata(env):
    client, sid, *_ = env
    result = client.post('/api/study/scan', json=dict(session_id=sid,
        research_prompt='Propose candidates for human ABL1', mode='live', use_assistant=False))
    assert result.status_code == 200, result.text
    assert result.json()['study']['workflow'] == 'generate_screen'
