"""Local-only detection and format-preserving redaction. Never log inputs."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import threading
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'toxoracle_privacy_v1'
REVISION = '7ffa9a043d54d1be65afb281eddf0ffbe629385b'
MAX_BYTES = 1_000_000
MAX_FIELD = 6000
IDENTIFYING = re.compile(r'^(patient|subject|donor|participant)[ _-]?(id|identifier|name)$|^(name|full[ _-]?name|email|phone|address|date[ _-]?of[ _-]?birth|dob|password|api[ _-]?key|ssn|nhs[ _-]?(number|id))$', re.I)
ESSENTIAL = {'compound_id','canonical_smiles','smiles','atom_mapped_smiles','structure_id','standardization_version'}
PATTERNS = [
    ('private_email', re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',re.I)),
    ('private_phone', re.compile(r'(?<!\w)\+\d[\d ()-]{8,}\d')),
    ('subject_identifier', re.compile(r'(?i)\b(?:patient|subject|donor|participant)[ _-]?(?:id|identifier)\s*[:=]\s*([^\s,;"}]+)')),
]


class PrivacyError(ValueError):
    """Messages are fixed codes, never input excerpts."""


class LocalDetector:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()

    def detect(self, text):
        if not text:
            return []
        if len(text) > MAX_FIELD + 256:
            raise PrivacyError('field_too_long')
        with self._lock:
            try:
                if self._model is None:
                    os.environ['HF_HUB_OFFLINE'] = '1'
                    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
                    os.environ['TIKTOKEN_CACHE_DIR'] = str(ROOT/'artifacts/privacy/cache/tiktoken')
                    path = ROOT/'artifacts/privacy/checkpoint'
                    manifest = json.loads((path/'manifest.json').read_text())
                    if manifest['checkpoint_revision'] != REVISION:
                        raise PrivacyError('checkpoint_revision_mismatch')
                    # Validate local assets before importing the model. Missing tokenizer
                    # cache must fail closed rather than trigger tiktoken's HTTP fallback.
                    if not manifest.get('tokenizer_files'):
                        raise PrivacyError('tokenizer_cache_missing')
                    for name,expected in manifest['tokenizer_files'].items():
                        p=ROOT/'artifacts/privacy/cache/tiktoken'/name
                        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
                            raise PrivacyError('tokenizer_cache_invalid')
                    for name,expected in manifest['files'].items():
                        p=path/'original'/name
                        h=hashlib.sha256()
                        with p.open('rb') as handle:
                            for block in iter(lambda:handle.read(8*1024*1024),b''):
                                h.update(block)
                        if h.hexdigest()!=expected:
                            raise PrivacyError('checkpoint_integrity_failed')
                    import torch
                    torch.set_num_threads(min(4, os.cpu_count() or 1))
                    from opf import OPF
                    self._model = OPF(model=path/'original', device='cpu',context_window_length=8192)
                result = self._model.redact(text)
                if result.warning:
                    raise PrivacyError('tokenizer_roundtrip_mismatch')
                return [dict(start=s.start,end=s.end,label=s.label,detector='openai_privacy_filter') for s in result.detected_spans]
            except PrivacyError:
                raise
            except Exception:
                raise PrivacyError('local_detector_failed') from None


def detect(text, detector):
    spans = detector.detect(text)  # Mandatory; never silently fall back to rules.
    for label, pattern in PATTERNS:
        for match in pattern.finditer(text):
            start,end = match.span(1) if label == 'subject_identifier' else match.span()
            spans.append(dict(start=start,end=end,label=label,detector='rule'))
    for span in spans:
        if not 0 <= span['start'] < span['end'] <= len(text):
            raise PrivacyError('invalid_detector_offsets')
    unique={}
    for s in spans:
        k=(s['start'],s['end'],s['label'])
        if k in unique:
            unique[k]['detector']+='+'+s['detector']
        else:
            unique[k]=dict(s)
    return list(unique.values())


def mask(text, spans):
    # Merge overlaps rather than applying overlapping offsets to modified text.
    merged=[]
    for s in sorted(spans,key=lambda s:(s['start'],s['end'])):
        if merged and s['start'] < merged[-1]['end']:
            merged[-1]['end']=max(merged[-1]['end'],s['end'])
        else:
            merged.append(dict(s))
    for s in reversed(merged):
        text=text[:s['start']]+'[REDACTED]'+text[s['end']:]
    return text


def parse(content, format):
    if not isinstance(content,str) or len(content.encode('utf8')) > MAX_BYTES:
        raise PrivacyError('input_too_large')
    if '\x00' in content:
        raise PrivacyError('unsupported_encoding')
    try:
        if format == 'text':
            if len(content)>MAX_FIELD:
                raise PrivacyError('field_too_long')
            return content
        if format == 'json':
            def pairs(items):
                d={}
                for k,v in items:
                    if k in d:
                        raise PrivacyError('duplicate_json_key')
                    d[k]=v
                return d
            result=json.loads(content,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(PrivacyError('nonfinite_number')))
            return result
        if format == 'csv':
            reader=csv.DictReader(io.StringIO(content),strict=True)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise PrivacyError('invalid_csv_header')
            rows=list(reader)
            if any(None in r or any(v is None for v in r.values()) for r in rows):
                raise PrivacyError('invalid_csv_row')
            return rows
    except PrivacyError:
        raise
    except Exception:
        raise PrivacyError('invalid_format') from None
    raise PrivacyError('unsupported_format')


def serialize(value, format):
    if format == 'text':
        return value
    if format == 'json':
        return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)
    if not value:
        raise PrivacyError('empty_csv')
    stream=io.StringIO()
    keys=list(dict.fromkeys(k for r in value for k in r))
    writer=csv.DictWriter(stream,fieldnames=keys); writer.writeheader(); writer.writerows(value)
    return stream.getvalue()


def scan(content, format, detector):
    from rdkit import rdBase
    rdBase.DisableLog('rdApp.*')
    value=parse(content,format)
    findings=[]; blocked=[]; review_fields=[]; counts=Counter(); cache={}; leaves=0
    def inspect(text):
        if text not in cache:
            cache[text]=detect(text,detector)
        return cache[text]
    def walk(v,path='',key='',depth=0,scientific_valid=False):
        nonlocal leaves
        if depth>16:
            raise PrivacyError('nesting_too_deep')
        if isinstance(v,dict):
            out={}
            valid_keys=set()
            # Eligibility is derived from chemical/identity validation, not merely a
            # user-provided field name. Retention still requires a separate acknowledgement.
            if 'compound_id' in v and ('smiles' in v or 'canonical_smiles' in v):
                try:
                    from toxicity.src.baseline import prepare_compound
                    prepared=prepare_compound(v)
                    for field in ESSENTIAL & set(v):
                        value=v[field]
                        if not isinstance(value,str):
                            continue
                        if field in {'smiles','canonical_smiles','atom_mapped_smiles'}:
                            if any(c.isspace() for c in value) or '|' in value:
                                continue
                            from rdkit import Chem
                            mol=Chem.MolFromSmiles(value)
                            if mol is None:continue
                            for atom in mol.GetAtoms():atom.SetAtomMapNum(0)
                            from toxicity.src.ingest_dilirank import standardize
                            if standardize(Chem.MolToSmiles(mol))['canonical_smiles']!=prepared['canonical_smiles']:
                                continue
                        if field=='compound_id' and not re.fullmatch(r'(?=.*\d)[A-Za-z][A-Za-z0-9_.-]{0,127}',value):
                            continue
                        valid_keys.add(field)
                except Exception:
                    pass
            for k,child in v.items():
                if len(k)>128:
                    raise PrivacyError('field_name_too_long')
                location=path+'/'+k
                if IDENTIFYING.fullmatch(k):
                    findings.append(dict(path=location,label='identifying_field',detector='field_policy',action='removed'))
                    counts['identifying_field']+=1
                    continue
                key_spans=inspect(k)
                if key_spans:
                    findings.append(dict(path=location,label='sensitive_field_name',detector='combined',action='removed'))
                    counts['sensitive_field_name']+=1
                    if k in ESSENTIAL:
                        blocked.append('essential_field_flagged')
                    continue
                out[k]=walk(child,location,k,depth+1,k in valid_keys)
            return out
        if isinstance(v,list):
            if len(v)>1000:
                raise PrivacyError('too_many_records')
            return [walk(child,path+'/'+str(i),key,depth+1) for i,child in enumerate(v)]
        leaves+=1
        if leaves>20000:
            raise PrivacyError('too_many_fields')
        if isinstance(v,str):
            if len(v)>MAX_FIELD:
                raise PrivacyError('field_too_long')
            prefix=(key+': ') if key else ''
            spans=[]
            for s in inspect(prefix+v):
                start=max(0,s['start']-len(prefix)); end=s['end']-len(prefix)
                if end>start:
                    spans.append(dict(s,start=start,end=end))
            if spans:
                for s in spans:
                    action=('review_required' if scientific_valid else 'blocked') if key in ESSENTIAL else 'redacted'
                    findings.append(dict(s,path=path,action=action))
                    counts[s['label']]+=1
                if key in ESSENTIAL:
                    if scientific_valid:
                        review_fields.append(dict(field_id=f'field_{len(review_fields)+1}',path=path,field=key,value=v,
                            reason='Validated scientific syntax/identity; reviewer must confirm it contains no personal identifier.'))
                    else:
                        blocked.append('essential_field_flagged')
                    return v
            if key in {'smiles','canonical_smiles','atom_mapped_smiles'}:
                from rdkit import Chem
                if Chem.MolFromSmiles(v) is None:
                    blocked.append('invalid_molecular_structure')
            return mask(v,spans)
        return v
    sanitized=walk(value)
    output=serialize(sanitized,format)
    # Internal object validation is lazy: generic assay CSV need not be a candidate list.
    records=sanitized.get('compounds') if isinstance(sanitized,dict) else sanitized
    if isinstance(records,list) and any(isinstance(r,dict) and ('smiles' in r or 'canonical_smiles' in r) for r in records):
        try:
            from toxicity.src.baseline import prepare_compound
            prepared=[prepare_compound(r) for r in records]
            if len({r['compound_id'] for r in prepared}) != len(prepared):
                raise ValueError('duplicate_ids')
        except Exception:
            blocked.append('candidate_identity_invalid')
    return dict(sanitized=output,findings=findings,blocked=sorted(set(blocked)),review_fields=review_fields,format=format,
                audit=dict(policy_version=POLICY,model_revision=REVISION,category_counts=dict(counts),
                           sanitized_sha256=hashlib.sha256(output.encode()).hexdigest()))


def toxicity_request(snapshot):
    data=parse(snapshot['sanitized'],snapshot['format'])
    records=data.get('compounds') if isinstance(data,dict) else data
    if not isinstance(records,list) or not records:
        raise PrivacyError('candidate_list_required')
    try:
        from toxicity.src.baseline import prepare_compound
        compounds=[prepare_compound(row) for row in records]
        if len({r['compound_id'] for r in compounds})!=len(compounds):
            raise ValueError('duplicate')
    except Exception:
        raise PrivacyError('candidate_identity_invalid') from None
    return dict(schema_version='2.0',request_id='privacy_'+snapshot['audit']['sanitized_sha256'][:16],compounds=compounds)
