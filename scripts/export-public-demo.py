#!/usr/bin/env python3
"""Export only the two explicitly reviewed public recordings. Never calls providers."""
import base64
import csv
import hashlib
import io
import json
import re
import runpy
from pathlib import Path
from toxoracle_app.screening import validate_screening_report, render
from toxoracle_app.workspace_results import candidate_evidence, model_context

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'generated': 'bf3e06a08c46441facc6e51def76b04d', 'supplied': 'd8ee241e77134215a8bfe0b3b6bcdc7a'}
OUT = ROOT / 'demo/public/studies'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def safe_bytes(data):
    if re.search(rb'/Users/|/home/|artifacts/web/|nvapi-[A-Za-z0-9_-]+|Bearer [A-Za-z0-9_.-]+|"(?:session_id|owner_id|launch_token|api_key)"', data):
        raise ValueError('Private material in public export')
    return data

def encode(value):
    return safe_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())

def export(slug, run_id):
    source = ROOT / 'artifacts/web/runs' / run_id
    job = json.loads((source / 'job.json').read_text())
    approved = json.loads((source / 'approved.json').read_text())
    report_bytes = (source / 'science/combined.json').read_bytes()
    report = json.loads(report_bytes)
    validate_screening_report(report)
    folder = OUT / slug
    folder.mkdir(parents=True, exist_ok=True)
    assets = {}
    def write(name, data):
        data = safe_bytes(data)
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        assets[name] = {'sha256': digest(data), 'bytes': len(data)}
    evidence = {}
    for row in report['results']:
        cid = row['compound_id']
        discovery = row['discovery_result']
        for i, artifact in enumerate(discovery['structures']):
            path = Path(artifact['uri']).resolve()
            if not path.is_relative_to((source / 'science').resolve()):
                raise ValueError('Structure outside selected source')
            data = path.read_bytes()
            if digest(data) != artifact['sha256']:
                raise ValueError('Pose integrity failure')
            artifact['uri'] = f'poses/{cid}-{i}.cif'
            write(artifact['uri'], data)
        if discovery['raw_response']:
            # A non-resolving content identifier preserves provenance, not provider payloads.
            discovery['raw_response']['uri'] = 'urn:sha256:' + discovery['raw_response']['sha256']
        base = candidate_evidence(report, cid)
        evidence[cid] = {'features': base['features'], 'attribution_status': base['attribution_status'], 'images': {}}
        for feature in [None] + [g['source'] for g in base['features']]:
            for labels in [False, True]:
                view = candidate_evidence(report, cid, feature, labels)
                key = (feature or 'molecule') + ('-labels' if labels else '')
                if view['image']:
                    name = f'molecules/{cid}/{key}.svg'
                    write(name, base64.b64decode(view['image'].split(',', 1)[1]))
                    evidence[cid]['images'][key] = name
    validate_screening_report(report)
    # Explicit source fields; ownership and approval capabilities are not exported.
    public_job = {k: job[k] for k in ('job_id','status','created_at','finished_at','events','candidates','candidate_count','target_id','workflow','mode','research_prompt','shortlist','discovery_sha256','assistant') if k in job}
    for value in public_job['assistant'].values():
        if isinstance(value, dict):
            value.pop('response_id', None)
    if job.get('generation'):
        public_job['generation'] = job['generation']
    review = {k: approved[k] for k in ('research_prompt','request','target_id','workflow','approved_at') if k in approved}
    review['audit'] = {k: approved['approval'][k] for k in ('policy_version','model_revision','category_counts','reviewed_scientific_fields_retained')}
    data = {'version': 1, 'slug': slug, 'report': report, 'run': public_job, 'review': review, 'evidence': evidence, 'model': model_context(report)}
    write('study.json', encode(data))
    write('report.json', encode(report))
    write('report.html', render(report).encode())
    if slug == 'supplied':
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, lineterminator='\n'); writer.writerow(['compound_id', 'smiles'])
        writer.writerows((r['compound_id'], r['canonical_smiles']) for r in report['results'])
        write('example.csv', stream.getvalue().encode())
    manifest = {'version':1, 'slug':slug, 'source_run':run_id, 'source_report_sha256':digest(report_bytes), 'execution_mode':job['mode'], 'status':job['status'], 'raw_responses':'Not published; URNs identify original content hashes.', 'assets':assets}
    (folder / 'manifest.json').write_bytes(encode(manifest))
    # Reject stale/unreviewed files rather than accidentally packaging them.
    derived = {'cohort-study.json', 'cohort-report.json', 'cohort-report.html'} if slug == 'generated' else set()
    if {str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()} - derived != set(assets) | {'manifest.json'}:
        raise ValueError('Unexpected public files; review and remove obsolete assets')
    print(f'{slug}: {len(report["results"])} candidates; {sum(len(r["discovery_result"]["structures"]) for r in report["results"])} verified poses; {len(assets)} assets')
    return {'slug':slug, 'manifest_sha256':digest(encode(manifest))}

if __name__ == '__main__':
    studies = [export(slug, rid) for slug, rid in SOURCES.items()]
    (OUT / 'index.json').write_bytes(encode({'version':1, 'studies':studies}))

    runpy.run_path(str(ROOT / 'scripts/export-demo-cohort.py'), run_name='__main__')
