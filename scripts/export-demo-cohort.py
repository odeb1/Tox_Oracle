#!/usr/bin/env python3
"""Derive a complete-evidence demo cohort without altering the original export."""
import copy
import hashlib
import json
from pathlib import Path
from toxoracle_app.screening import validate_screening_report, render

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'demo/public/studies/generated'

def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

def derive(study):
    data = copy.deepcopy(study)
    rows = [r for r in data['report']['results'] if r['discovery_result']['status'] == 'ok' and r['toxicity_result']['status'] == 'ok']
    ids = {r['compound_id'] for r in rows}
    if not set(data['report']['discovery_shortlist']) <= ids:
        raise ValueError('Cohort selection must preserve the entire discovery shortlist')
    excluded = [r['compound_id'] for r in study['report']['results'] if r['compound_id'] not in ids]
    cohort = {'version': 1, 'selection': 'Successful discovery and toxicity assessments',
              'source_candidate_count': len(study['report']['results']), 'candidate_count': len(rows),
              'excluded_compound_ids': excluded, 'source_study': 'study.json', 'source_report': 'report.json'}
    data['report']['results'] = rows
    data['report']['limitations'].append(f"Demo cohort: {len(rows)} successfully screened candidates from the original {len(study['report']['results'])}-candidate run. Original source evidence is preserved separately; scores, ranks and shortlist are unchanged.")
    run = data['run']
    run['demo_cohort'] = cohort
    run['candidate_count'] = len(rows)
    run['candidates'] = [c for c in run['candidates'] if c['compound_id'] in ids]
    # Status describes this derived cohort; the source run retains its original status.
    run['status'] = 'complete'
    run.pop('generation', None)  # Original generation ledger remains in source study.json.
    run['events'] = [e for e in run['events'] if e.get('compound_id') not in excluded]
    completed = 0
    for event in run['events']:
        if 'candidates' in event:
            event['candidates'] = [c for c in event['candidates'] if c['compound_id'] in ids]
        if event['stage'] == 'candidate_finished':
            completed += 1
        if 'completed' in event:
            event['completed'] = completed
        if 'total' in event:
            event['total'] = len(rows)
    data['evidence'] = {cid: value for cid, value in data['evidence'].items() if cid in ids}
    # The privacy review and agent text are original historical evidence, not rewritten.
    validate_screening_report(data['report'])
    return data

def export():
    source = (FOLDER / 'study.json').read_bytes()
    data = derive(json.loads(source))
    manifest = json.loads((FOLDER / 'manifest.json').read_text())
    files = {'cohort-study.json': encode(data), 'cohort-report.json': encode(data['report']),
             'cohort-report.html': render(data['report']).encode()}
    for name, raw in files.items():
        (FOLDER / name).write_bytes(raw)
        manifest['assets'][name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    manifest['presentation'] = {'study': 'cohort-study.json', 'report': 'cohort-report.json',
                                'html': 'cohort-report.html', 'source_study_sha256': hashlib.sha256(source).hexdigest()}
    raw = encode(manifest)
    (FOLDER / 'manifest.json').write_bytes(raw)
    index_path = FOLDER.parent / 'index.json'
    index = json.loads(index_path.read_text())
    next(e for e in index['studies'] if e['slug'] == 'generated')['manifest_sha256'] = hashlib.sha256(raw).hexdigest()
    index_path.write_bytes(encode(index))
    print(f"Derived demo cohort: {len(data['report']['results'])} candidates, original recording preserved.")

if __name__ == '__main__':
    export()
