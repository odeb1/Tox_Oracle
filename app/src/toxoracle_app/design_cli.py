"""Rosalind advanced ABL1 workflows. All hosted actions are explicit and bounded."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .screen_cli import ROOT, load, run_model, failed_toxicity
from .screening import combine_screening, render, summary, validate_discovery
from .validation import DEFAULT_CONTRACTS_DIR, _validate_schema, ContractValidationError, validate_request
from toxoracle_discovery.boltz2 import (BoltzClient, BoltzError, digest, save, validate_target,
    predict_candidate, failed_candidate, rank_candidates)
from toxoracle_discovery.generation import (PROTOCOL, GenerationError, credentials_present,
    make_template, chemical_checks, parse_molecule, diverse_subset, chemistry_metrics, generate_batch)

TARGET_PATH = ROOT / 'discovery/configs/targets/abl1.json'
SEED_PATH = ROOT / 'discovery/configs/generation/abl1-imatinib.json'
CONFIG_PATH = ROOT / 'configs/design-v1.json'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_design(request):
    _validate_schema(request, DEFAULT_CONTRACTS_DIR / 'design-request-v1.schema.json', 'design request')
    for name in ('compounds', 'seeds'):
        rows = request.get(name, [])
        ids = [r['compound_id'] for r in rows]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate input compound IDs')


def resolve(args):
    request = load(args.request)
    validate_design(request)
    target, seed_manifest, config = load(TARGET_PATH), load(SEED_PATH), load(CONFIG_PATH)
    validate_target(target)
    if seed_manifest['target_id'] != target['target_id'] or config['protocol'] != PROTOCOL:
        raise ValueError('Protocol/target mismatch')
    if (config['max_generation_requests'], config['batch_size'], config['max_proposals'],
        config['max_candidates'], config['shortlist_size']) != (5,20,100,20,2):
        raise ValueError('Budget changes require a new supported protocol version')
    source_path = ROOT / seed_manifest['seed_source']
    if sha(source_path) != seed_manifest['source_sha256']:
        raise ValueError('Seed source checksum mismatch')
    reference = next(c for c in load(source_path)['compounds'] if c['compound_id'] == seed_manifest['seed_compound_id'])
    if target['reference_compound_id'] != reference['compound_id']:
        raise ValueError('Reference mismatch')
    # Pin implementation as well as config for safe resume after code changes.
    implementation = {str(p.relative_to(ROOT)): sha(p) for base in ('app/src', 'discovery/src', 'toxicity/src', 'contracts')
                      for p in sorted((ROOT/base).rglob('*')) if p.suffix in {'.py','.json'}}
    packages=('rdkit','numpy','scikit-learn','joblib','shap','jsonschema')
    versions={name:importlib.metadata.version(name) for name in packages}
    model_env=subprocess.run([str(args.model_python),'-c',
        'import json,importlib.metadata as m; print(json.dumps({n:m.version(n) for n in '+repr(packages)+'}))'],
        capture_output=True,text=True,timeout=60)
    if model_env.returncode:
        raise ValueError('Scientific subprocess environment is incomplete')
    return dict(request=request, target=target, reference=reference, seed_manifest=seed_manifest,
                config=config, target_sha256=sha(TARGET_PATH), seed_manifest_sha256=sha(SEED_PATH),
                model_sha256=sha(args.model) if args.model.is_file() else None,
                implementation_sha256=digest(implementation), model_python=str(args.model_python),
                runtime_versions=versions, model_runtime_versions=json.loads(model_env.stdout),
                count=request.get('count', config['requested_count_default']))


class Journal:
    """Persist call intent before dispatch; an interrupted call is never resubmitted."""
    def __init__(self, output, resolved, resume):
        self.output = output
        self.manifest_path = output/'workflow.json'
        if resume:
            self.data = load(self.manifest_path)
            if self.data['input_digest'] != digest(resolved):
                raise ValueError('Resume input, model, implementation or configuration changed')
            actual = {str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()
                      and p.name not in {'workflow.json', '.run.lock', 'workflow.tmp'}}
            if actual != set(self.data['artifacts']):
                raise ValueError('Uncheckpointed artifacts: review interrupted stage before recovery')
            for name, checksum in self.data['artifacts'].items():
                path = output/name
                if path.resolve().parent != output.resolve() and output.resolve() not in path.resolve().parents:
                    raise ValueError('Unsafe artifact path')
                if not path.is_file() or sha(path) != checksum:
                    raise ValueError('Resume artifact integrity check failed')
            if self.data.get('pending_call'):
                raise ValueError('Interrupted external call: outcome unknown; automatic resubmission prohibited')
        else:
            try:
                revision = subprocess.run(['git','rev-parse','HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
                dirty = bool(subprocess.run(['git','status','--porcelain'], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip())
            except (OSError, subprocess.TimeoutExpired):
                revision, dirty = None, None
            self.data = dict(schema_version='1.0', protocol=PROTOCOL, status='running',
                started_at=now(), input_digest=digest(resolved), git_commit=revision, working_tree_dirty=dirty,
                pending_call=None, generation_attempts=0, boltz_attempts=0, artifacts={}, errors=[],
                stages={}, reference_passed=False)
            save(output/'resolved.json', resolved)
            self.checkpoint()

    def checkpoint(self):
        self.data['artifacts'] = {str(p.relative_to(self.output)): sha(p) for p in sorted(self.output.rglob('*'))
            if p.is_file() and p.name not in {'workflow.json', '.run.lock', 'workflow.tmp'}}
        self.data['updated_at'] = now()
        save(self.output/'workflow.tmp', self.data)
        (self.output/'workflow.tmp').replace(self.manifest_path)

    def begin_call(self, kind, identity):
        self.data[kind+'_attempts'] += 1
        self.data['pending_call'] = dict(kind=kind, identity=identity, started_at=now())
        self.checkpoint()

    def end_call(self):
        self.data['pending_call'] = None
        self.checkpoint()


@contextmanager
def run_lock(output):
    lock = output/'.run.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def prepare(args, row, directory, request_id):
    directory.mkdir(parents=True, exist_ok=True)
    inp, out = directory/'input.json', directory/'prepared.json'
    save(inp, dict(request_id=request_id, compounds=[row]))
    run_model(args, 'prepare', inp, out)
    result = load(out)['compounds'][0]
    # Supplied shared identities must match, rather than being silently rewritten.
    for field in ('canonical_smiles','structure_id','atom_mapped_smiles','standardization_version'):
        if field in row and row[field] != result[field]:
            raise ValueError('Submitted molecular identity differs from standardization')
    return result


def prepare_inputs(args, resolved, output):
    req = resolved['request']
    rows = req.get('compounds', req.get('seeds', []))
    prepared, ledger, seen = [], [], set()
    for i, row in enumerate(rows):
        item = dict(compound_id=row['compound_id'], status='rejected')
        try:
            parse_molecule(row.get('smiles', row.get('canonical_smiles')))
            compound = prepare(args, row, output/'inputs'/str(i), req['request_id'])
            item['warnings'] = chemical_checks(compound['canonical_smiles'])
            if compound['compound_id'] == resolved['reference']['compound_id'] and compound != resolved['reference']:
                raise ValueError('Reference ID conflicts with candidate identity')
            if compound['structure_id'] in seen:
                item.update(status='duplicate', reason='duplicate_standardized_structure')
            else:
                seen.add(compound['structure_id'])
                prepared.append(compound)
                item.update(status='accepted', compound=compound)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            item['reason'] = 'invalid_unsupported_or_inconsistent_structure'
        ledger.append(item)
    save(output/'input-ledger.json', ledger)
    if rows and not prepared:
        raise ValueError('No acceptable supplied structures')
    return prepared


def generate(args, resolved, journal, seeds, client):
    output, req = journal.output, resolved['request']
    state_path = output/'generation-state.json'
    if state_path.exists():
        state = load(state_path)
    else:
        if seeds:
            templates = [make_template(s) for s in seeds]
        else:
            manifest = resolved['seed_manifest']
            templates = [make_template(resolved['reference'], cut_atoms=manifest['cut_atom_indices'], retain_atom=manifest['retain_atom'])]
        state = dict(templates=templates, batches=[], ledger=[], accepted=[], valid_structure_count=0, stopped=False)
        save(state_path,state)
        journal.checkpoint()
    # Finish saved responses locally before dispatching another generation request.
    for meta in state['batches']:
        i = meta['batch_index']
        raw = load(output/'genmol'/str(i)/'response.json')
        process_batch(args, resolved, journal, state, i, raw['molecules'])
    while len(state['accepted']) < resolved['count'] and len(state['batches']) < 5 and not state['stopped']:
        i = len(state['batches'])
        if journal.data['generation_attempts'] >= 5:
            break
        template = state['templates'][i % len(state['templates'])]
        journal.begin_call('generation', str(i))
        try:
            molecules, meta = generate_batch(template, i, output/'genmol'/str(i), client,
                cache=args.cache_dir/'genmol' if args.cache_dir else None)
        except (ValueError, OSError, TypeError):
            state['stopped'] = True
            journal.data['errors'].append(dict(stage='generation', code='generation_failed', batch=i))
            save(state_path,state)
            journal.end_call()
            break
        # Save the response before clearing intent; preprocessing can resume without
        # making this generation call again.
        state['batches'].append(meta)
        save(state_path,state)
        journal.end_call()
        process_batch(args, resolved, journal, state, i, molecules)
    # Resume any successful batch whose local preprocessing was interrupted.
    for meta in state['batches']:
        i = meta['batch_index']
        raw = load(output/'genmol'/str(i)/'response.json')
        process_batch(args, resolved, journal, state, i, raw['molecules'])
    selected = diverse_subset(state['accepted'], resolved['count'])
    selected_ids = [c['compound_id'] for c in selected]
    for item in state['ledger']:
        if item['status'] in {'accepted','selected','not_selected'}:
            item['status'] = 'selected' if item['compound']['compound_id'] in selected_ids else 'not_selected'
    metrics = chemistry_metrics(selected, [t['seed'] for t in state['templates']])
    metrics.update(returned_count=sum(b['returned_count'] for b in state['batches']),
        accepted_unique_count=len(state['accepted']), selected_count=len(selected),
        valid_structure_count=state['valid_structure_count'], requested_count=resolved['count'],
        proposed_slots=sum(b['requested_count'] for b in state['batches']),
        novelty_scope='Exact identity against supplied seeds and the frozen four-compound ABL1 panel only')
    result = dict(schema_version='1.0', protocol=PROTOCOL, templates=state['templates'], batches=state['batches'],
        ledger=state['ledger'], selected=selected_ids, metrics=metrics,
        status='complete' if len(selected) == resolved['count'] and not state['stopped'] else 'partial')
    _validate_schema(result, DEFAULT_CONTRACTS_DIR/'generation-result-v1.schema.json','generation result')
    save(output/'generation.json', result)
    return selected


def process_batch(args, resolved, journal, state, index, molecules):
    output = journal.output
    template = state['templates'][index % len(state['templates'])]
    known = {c['structure_id'] for c in load(ROOT/'demo/examples/abl1_request.json')['compounds']}
    known.update(t['seed']['structure_id'] for t in state['templates'])
    for j, molecule in enumerate(molecules):
        pid = f'b{index:02d}_p{j:03d}'
        if any(x['proposal_id'] == pid for x in state['ledger']):
            continue
        item = dict(proposal_id=pid, template_id=template['template_id'], status='rejected', raw=molecule)
        try:
            if not isinstance(molecule, dict):
                raise GenerationError('invalid_molecule_record')
            score = molecule.get('score')
            if isinstance(score,bool) or not isinstance(score,(int,float)) or not math_isfinite(score) or not 0 <= score <= 1:
                raise GenerationError('invalid_QED_score')
            warnings = chemical_checks(molecule.get('smiles'))
            state['valid_structure_count'] += 1
            chemical_checks(molecule['smiles'],template)
            compound = prepare(args, dict(compound_id='proposal_'+pid, smiles=molecule['smiles']),
                               output/'proposals'/pid,resolved['request']['request_id'])
            chemical_checks(compound['canonical_smiles'],template)
            compound['compound_id'] = 'GEN_'+compound['structure_id'][:24]
            item.update(compound=compound, warnings=warnings, generation_score_kind='QED', generation_score=score)
            if compound['structure_id'] in known:
                item.update(status='known_structure', reason='exact_seed_or_frozen_panel_match')
            elif compound['structure_id'] in {c['structure_id'] for c in state['accepted']}:
                item.update(status='duplicate', reason='duplicate_standardized_structure')
            else:
                item['status']='accepted'
                state['accepted'].append(compound)
        except GenerationError as error:
            item['reason']=str(error)
        except (ValueError,OSError,subprocess.TimeoutExpired):
            item['reason']='standardization_failed'
        state['ledger'].append(item)
        save(output/'generation-state.json',state)
        journal.checkpoint()


def math_isfinite(value):
    import math
    return math.isfinite(value)


def score(args, resolved, journal, compound, client, role):
    output = journal.output
    path = output/'records'/(digest([role,compound]) + '.json')
    if path.exists():
        return load(path)
    journal.begin_call('boltz', compound['compound_id'])
    try:
        record = predict_candidate(compound, resolved['target'], output/'boltz2'/digest([role,compound]), client,
                                   cache=args.cache_dir/'boltz2' if args.cache_dir else None)
    except (BoltzError, ValueError, OSError, TypeError):
        record = failed_candidate(compound,'boltz2_failed','Discovery request or artifact validation failed; no automatic retry')
    save(path,record)
    journal.end_call()
    return record


def report_workflow(output, resolved, journal, report=None):
    generation = load(output/'generation.json') if (output/'generation.json').exists() else None
    ledger = load(output/'input-ledger.json') if (output/'input-ledger.json').exists() else []
    wrapper = dict(schema_version='1.0', mode=resolved['request']['mode'], status=journal.data['status'],
        request_id=resolved['request']['request_id'], reference=load(output/'reference.json') if (output/'reference.json').exists() else None,
        generation=generation, input_ledger=ledger, assessment=report, errors=journal.data['errors'],
        limitations=['Generated proposals have no prospective efficacy or safety validation.',
            'DILI generalization to generated chemistry is unestablished; similarity is not confidence.',
            'Synthesis feasibility is unassessed. No automatic replacement or DILI-guided generation.',
            'Generation is ligand-fragment-conditioned, not protein-conditioned.'])
    modes = [load(p)['provenance']['execution_mode'] for p in (output/'records').glob('*.json')]
    generation_modes = [b['execution_mode'] for b in generation['batches']] if generation and 'batches' in generation else []
    journal.data['execution_counts'] = {
        'boltz_completed_live': modes.count('live'), 'boltz_completed_cached': modes.count('cached'),
        'boltz_failed_or_unavailable': modes.count('not_run'),
        'genmol_completed_live': generation_modes.count('live'),
        'genmol_completed_cached': generation_modes.count('cached'),
    }
    wrapper['execution_counts'] = journal.data['execution_counts']
    shortlist = report['discovery_shortlist'] if report else []
    changed = [r['compound_id'] for r in report['results'] if r['compound_id'] in shortlist and r['follow_up']['decision'] in {'hold_for_liver_validation','safety_assessment_incomplete'}] if report else []
    wrapper['follow_up_change'] = dict(discovery_shortlist=shortlist, held_or_incomplete=changed,
        message='No shortlisted follow-up categories changed.' if shortlist and not changed else 'Review held or incomplete shortlisted candidates.' if shortlist else 'No discovery shortlist available.')
    save(output/'design-report.json',wrapper)
    esc=lambda x:html.escape(str(x))
    introduction=(f'<h1>ToxOracle advanced ABL1 workflow</h1><p>Mode: {esc(wrapper["mode"])} · Status: {esc(wrapper["status"])}</p>'
        f'<p>{esc(wrapper["follow_up_change"]["message"])}</p><p>Generation provenance and all rejected inputs/proposals are recorded below.</p>'
        '<details><summary>Generation, input ledger and workflow evidence</summary><pre>'+esc(json.dumps({k:v for k,v in wrapper.items() if k!='assessment'},indent=2))+'</pre></details>')
    if generation and 'metrics' in generation:
        m=generation['metrics']
        modes=', '.join(sorted({b['execution_mode'] for b in generation['batches']}))
        introduction=(f'<p>GenMol: {esc(modes)} · Returned proposals: {m["returned_count"]} · '
            f'Accepted unique: {m["accepted_unique_count"]} · Selected for discovery: {m["selected_count"]}</p>'
            '<p>Ligand-fragment-conditioned proposals. Generation QED is not binding affinity. '
            'Synthesis feasibility and DILI generalization to these proposals are unestablished.</p>')+introduction
    if report:
        page=render(report).replace('<h1>Discovery screening + human DILI</h1>',introduction+'<h2>Discovery screening + human DILI</h2>')
        if generation:
            page=page.replace('Retrospective demonstration · Provisional decision policy','Generated proposals · Provisional decision policy')
    else:
        page='<!doctype html><html lang="en"><meta charset="utf-8"><title>ToxOracle design</title><style>body{font:16px system-ui;margin:2rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'+introduction+'</html>'
    (output/'design-report.html').write_text(page)
    text=f'ToxOracle {wrapper["mode"]}: {wrapper["status"]}\n'+wrapper['follow_up_change']['message']+'\n'
    if report:
        assessment_summary=summary(report)
        if generation:
            assessment_summary=assessment_summary.replace('Policy: provisional; retrospective demonstration',
                'Policy: provisional; generated proposals, not labelled evaluation cases')
        text+=assessment_summary
    (output/'summary.txt').write_text(text)


def execute(args, *, genmol_client=None, boltz_client=None):
    resolved=resolve(args)
    if resolved['model_sha256'] is None:
        raise ValueError('Missing local DILI model; never train implicitly')
    output=args.output_dir.resolve()
    if not args.resume:
        output.mkdir(parents=True,exist_ok=False)
    elif not output.is_dir():
        raise ValueError('Resume directory missing')
    with run_lock(output):
        journal=Journal(output,resolved,args.resume)
        if journal.data['status'] in {'complete','partial','failed'}:
            print(f'Saved run: {journal.data["status"]}; {output / "design-report.html"}')
            return 0 if journal.data['status']=='complete' else 2
        started=time.monotonic()
        report=None
        try:
            # All local input preparation precedes external submission.
            prepared_path=output/'prepared-inputs.json'
            if prepared_path.exists():
                prepared=load(prepared_path)
            else:
                prepared=prepare_inputs(args,resolved,output)
                save(prepared_path,prepared)
                journal.checkpoint()
            if resolved['request']['mode']=='generate_screen':
                # Verify seed preparation before spending the reference request.
                if prepared:
                    for seed in prepared: make_template(seed)
                else:
                    make_template(resolved['reference'],cut_atoms=resolved['seed_manifest']['cut_atom_indices'],retain_atom=resolved['seed_manifest']['retain_atom'])
            class LazyBoltz:
                def predict(self,payload): return BoltzClient().predict(payload)
            client=boltz_client or LazyBoltz()
            reference=score(args,resolved,journal,resolved['reference'],client,'reference')
            save(output/'reference.json',reference)
            reference_ok=(reference['status']=='ok' and reference['binding_probability'] is not None and
                          (reference['affinity_pic50'] is not None or reference['affinity_pred_value'] is not None))
            journal.data['reference_passed']=reference_ok
            journal.checkpoint()
            if not reference_ok:
                journal.data['errors'].append(dict(stage='reference',code='reference_failed'))
                journal.data['status']='partial'
                return 2
            candidate_path=output/'request.json'
            if candidate_path.exists():
                request=load(candidate_path)
            else:
                compounds=generate(args,resolved,journal,prepared,genmol_client) if resolved['request']['mode']=='generate_screen' else prepared
                if not compounds:
                    journal.data['status']='partial'
                    journal.data['errors'].append(dict(stage='generation',code='no_acceptable_candidates'))
                    return 2
                request=dict(schema_version='2.0',request_id=resolved['request']['request_id'],compounds=compounds)
                validate_request(request)
                save(candidate_path,request)
                journal.checkpoint()
            discovery_path=output/'discovery.json'
            if discovery_path.exists():
                discovery=load(discovery_path)
                validate_discovery(request,discovery)
            else:
                records=[]
                for compound in request['compounds']:
                    records.append(reference.copy() if compound==resolved['reference'] else score(args,resolved,journal,compound,client,'candidate'))
                discovery=dict(schema_version='3.0',stream='discovery',request_id=request['request_id'],
                    target=dict(target_id=resolved['target']['target_id'],sequence_sha256=resolved['target']['sequence_sha256'],
                        manifest_sha256=resolved['target_sha256'],reference_compound_id=resolved['reference']['compound_id']),
                    ranking_rule='mean_binder_desc_top2_v1',results=rank_candidates(records))
                validate_discovery(request,discovery)
                save(discovery_path,discovery)
                journal.data['stages']['discovery_snapshot']=now()
                journal.checkpoint()
            tox_path=output/'toxicity.json'
            if tox_path.exists():
                toxicity=load(tox_path)
            else:
                try:
                    run_model(args,'predict',candidate_path,tox_path)
                    toxicity=load(tox_path)
                except (ValueError,OSError,subprocess.TimeoutExpired):
                    toxicity=failed_toxicity(request)
                    save(tox_path,toxicity)
                journal.data['stages']['dili_completed']=now()
                journal.checkpoint()
            report=combine_screening(request,discovery,toxicity)
            if resolved['request']['mode']=='generate_screen':
                report['limitations'][0]='Generated proposals, not labelled evaluation cases; fitting/selection overlap and chemical coverage must be disclosed.'
                report['limitations'].append('Generalization of the DILI baseline to these proposals is unestablished. Synthesis feasibility is unassessed.')
            save(output/'combined.json',report)
            complete=all(r['status']=='ok' and r['rank'] is not None for r in discovery['results']) and all(r['status']=='ok' for r in toxicity['results'])
            complete=complete and all(x['status']=='accepted' for x in load(output/'input-ledger.json'))
            if (output/'generation.json').exists(): complete=complete and load(output/'generation.json')['status']=='complete'
            journal.data['status']='complete' if complete else 'partial'
            return 0 if complete else 2
        except Exception:
            journal.data['status']='failed'
            journal.data['errors'].append(dict(stage='workflow',code='workflow_failed'))
            raise
        finally:
            journal.data['elapsed_seconds']=journal.data.get('elapsed_seconds',0)+time.monotonic()-started
            journal.data['finished_at']=now()
            report_workflow(output,resolved,journal,report)
            journal.checkpoint()
            print(f'Advanced report: {output / "design-report.html"}; status={journal.data["status"]}')


def preflight(args):
    resolved=resolve(args)
    checks=dict(request_valid=True,target_valid=True,model_present=resolved['model_sha256'] is not None,
        scientific_python=args.model_python.is_file(),credentials_present=credentials_present(),
        output_available=(args.output_dir/'workflow.json').is_file() if args.resume else not args.output_dir.exists())
    try:
        p=subprocess.run([str(args.model_python),'-c','import rdkit,joblib,sklearn,shap,jsonschema'],capture_output=True,timeout=60)
        checks['scientific_dependencies']=p.returncode==0
    except (OSError,subprocess.TimeoutExpired): checks['scientific_dependencies']=False
    local_ready=all(v for k,v in checks.items() if k!='credentials_present')
    print(json.dumps(dict(checks=checks,local_ready=local_ready,ready_for_live_run=local_ready and checks['credentials_present'],
        cache_status='verified during execution; missing entries need a credential',network_and_entitlement='not_tested',
        resolved_mode=resolved['request']['mode'],protocol=PROTOCOL),indent=2))
    return 0 if local_ready and (checks['credentials_present'] or args.cache_dir is not None or args.resume) else 2


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['preflight','run'])
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--cache-dir',type=Path,help='Opt-in genmol/ and boltz2/ exact-input cache')
    parser.add_argument('--resume',action='store_true',help='Verify artifacts; never repeat completed/ambiguous calls')
    parser.add_argument('--model',type=Path,default=ROOT/'artifacts/models/dili_baseline.joblib')
    parser.add_argument('--model-python',type=Path,default=ROOT/'toxicity/.venv/bin/python')
    args=parser.parse_args(argv)
    args.model_python=args.model_python.absolute()
    try:
        return preflight(args) if args.command=='preflight' else execute(args)
    except (ValueError,OSError,ImportError,ContractValidationError,subprocess.TimeoutExpired):
        print('Design stopped: check input contracts, environment and workflow.json. No automatic retry.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
