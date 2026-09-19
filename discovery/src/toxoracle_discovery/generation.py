"""Bounded GenMol transport and single-cut SAFE templates; no toxicity optimization."""
from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .boltz2 import digest, save

ENDPOINT = 'https://health.api.nvidia.com/v1/biology/nvidia/genmol/generate'
PROTOCOL = 'abl1_fragment_generation_v1'


class GenerationError(ValueError):
    pass


def credentials_present():
    return any(os.environ.get(k) for k in ('NVIDIA_API_KEY', 'NGC_API_KEY', 'NVIDIA_BIONEMO_API_KEY'))


class GenMolClient:
    def generate(self, payload):
        key = next((os.environ[k] for k in ('NVIDIA_API_KEY', 'NGC_API_KEY', 'NVIDIA_BIONEMO_API_KEY') if os.environ.get(k)), None)
        if not key:
            raise GenerationError('NVIDIA credential missing')
        request = Request(ENDPOINT, data=json.dumps(payload).encode(), method='POST', headers={
            'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with urlopen(request, timeout=180) as response:
                if response.status != 200:
                    raise GenerationError('GenMol returned an incomplete response')
                result = json.loads(response.read(8 * 1024 * 1024))
        except HTTPError as error:
            raise GenerationError(f'GenMol HTTP {error.code}; request not retried') from None
        except (URLError, socket.timeout, TimeoutError, OSError):
            raise GenerationError('GenMol connection failed or timed out; request not retried') from None
        except (ValueError, UnicodeError):
            raise GenerationError('GenMol returned invalid JSON') from None
        return result


def validate_response(raw, count):
    if not isinstance(raw, dict) or raw.get('status') != 'success' or not isinstance(raw.get('molecules'), list):
        raise GenerationError('GenMol did not return a successful molecule list')
    if len(raw['molecules']) > count:
        raise GenerationError('GenMol exceeded the requested proposal budget')
    try:
        digest(raw)
    except (ValueError, TypeError):
        raise GenerationError('Non-finite or malformed GenMol response') from None
    return raw['molecules']


def payload(template, count=20):
    return dict(smiles=template['safe_input'], num_molecules=count, temperature='1.0',
                noise='1.0', step_size=1, scoring='QED', unique=False)


def generate_batch(template, index, directory, client=None, cache=None):
    """Cache identity includes batch index so repeated payloads remain distinct draws."""
    request = payload(template)
    identity = dict(protocol=PROTOCOL, endpoint=ENDPOINT, template=template, batch_index=index, payload=request)
    key = digest(identity)
    path = Path(cache) / (key + '.json') if cache else None
    mode = 'live'
    if path and path.exists():
        entry = json.loads(path.read_text())
        if not isinstance(entry, dict) or entry.get('key') != key or digest(entry.get('response')) != entry.get('response_sha256'):
            raise GenerationError('Generation cache integrity failure')
        raw = entry['response']
        mode = 'cached'
    else:
        raw = (client or GenMolClient()).generate(request)
    directory = Path(directory)
    save(directory / 'request.json', request)
    # Save complete vendor evidence even for rejected responses, without auth headers.
    save(directory / 'response.json', raw)
    molecules = validate_response(raw, request['num_molecules'])
    if path and mode == 'live':
        save(path, dict(key=key, response=raw, response_sha256=digest(raw)))
    version = raw.get('model_version')
    version = version if isinstance(version, str) and version else None
    return molecules, dict(batch_index=index, template_id=template['template_id'], endpoint=ENDPOINT,
        execution_mode=mode, cache_key=key, response_sha256=digest(raw),
        served_model_version=version, version_status='reported' if version else 'unreported',
        requested_count=request['num_molecules'], returned_count=len(molecules))


def parse_molecule(smiles):
    from rdkit import Chem, rdBase
    if not isinstance(smiles, str) or not smiles or len(smiles) > 10000 or any(c.isspace() for c in smiles) or '|' in smiles:
        raise GenerationError('invalid_smiles')
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise GenerationError('invalid_smiles')
    if len(Chem.GetMolFrags(mol)) != 1:
        raise GenerationError('multicomponent_structure')
    if any(a.GetAtomicNum() not in {1, 5, 6, 7, 8, 9, 14, 15, 16, 17, 35, 53} or a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        raise GenerationError('unsupported_elements_or_radicals')
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    return mol


def _open_fragment(fragment):
    """Encode exactly one cut as a SAFE ring closure, verified by seed reconstruction.

    No general SAFE encoder is claimed. RDKit serializes each connected fragment;
    a terminal isotope-90 dummy becomes the unpaired closure %90.
    """
    from rdkit import Chem
    dummy = next(a.GetIdx() for a in fragment.GetAtoms() if a.GetAtomicNum() == 0)
    text = Chem.MolToSmiles(fragment, canonical=False, rootedAtAtom=dummy, isomericSmiles=True)
    if not text.startswith('[90*]'):
        raise GenerationError('Unsupported fragment serialization')
    rest = text[len('[90*]'):]
    match = re.match(r'(\[[^\]]+\]|Br|Cl|[A-Za-z])', rest)
    if not match:
        raise GenerationError('Unsupported attachment atom')
    return rest[:match.end()] + '%90' + rest[match.end():]


def make_template(seed, *, cut_atoms=None, retain_atom=None):
    """Default uses a recorded cut; user seeds choose a deterministic BRICS cut."""
    from rdkit import Chem
    from rdkit.Chem import BRICS
    mol = parse_molecule(seed['canonical_smiles'])
    if mol.GetNumHeavyAtoms() > 100:
        raise GenerationError('Seed exceeds the small-molecule protocol limit')
    choices = []
    cuts = [tuple(cut_atoms)] if cut_atoms is not None else [pair for pair, _ in BRICS.FindBRICSBonds(mol)]
    for a, b in cuts:
        bond = mol.GetBondBetweenAtoms(a, b)
        if bond is None or bond.IsInRing() or bond.GetBondType() != Chem.BondType.SINGLE:
            continue
        fragmented = Chem.FragmentOnBonds(mol, [bond.GetIdx()], dummyLabels=[(90, 90)])
        atom_groups = Chem.GetMolFrags(fragmented)
        fragments = Chem.GetMolFrags(fragmented, asMols=True)
        if len(fragments) != 2:
            continue
        for i, kept in enumerate(fragments):
            if retain_atom is not None and retain_atom not in atom_groups[i]:
                continue
            size = kept.GetNumHeavyAtoms()
            other = fragments[1-i]
            if not 8 <= size <= 30 or other.GetNumHeavyAtoms() < 3:
                continue
            left, right = _open_fragment(kept), _open_fragment(other)
            # Use the smallest free single-digit closure, as in ordinary SAFE
            # encodings. High artificial labels are poorly supported by GenMol.
            ring_text = re.sub(r'\[[^\]]+\]', '', (left + right).replace('%90',''))
            used = set(re.findall(r'\d',ring_text))
            closure = next((str(n) for n in range(1,10) if str(n) not in used),None)
            if closure is None:
                continue
            left, right = left.replace('%90',closure), right.replace('%90',closure)
            full = Chem.MolFromSmiles(left + '.' + right)
            if full is None or Chem.MolToSmiles(full) != Chem.MolToSmiles(mol):
                raise GenerationError('SAFE reconstruction differs from seed')
            choices.append((abs(size - 20), left, right, a, b, kept))
    if not choices:
        raise GenerationError('No supported single-cut fragment; seed preparation required')
    _, left, right, a, b, kept = min(choices, key=lambda x: x[:5])
    template = dict(seed=seed, cut_atom_indices=[a, b], atom_index_basis='zero-based RDKit canonical_smiles',
        retained_fragment_with_dummy=Chem.MolToSmiles(kept),
        reconstruction_safe=left + '.' + right, safe_input=left + '.[*{15-25}]',
        mask_bounds=[15, 25], method='verified_single_cut_safe_v1',
        attachment='One single bond at the unmatched SAFE closure; verify retained fragment and external attachment in every output')
    template['template_id'] = digest(template)
    return template


def chemical_checks(smiles, template=None):
    from rdkit import Chem
    mol = parse_molecule(smiles)
    if not 8 <= mol.GetNumHeavyAtoms() <= 70:
        raise GenerationError('heavy_atom_count_outside_8_70')
    if template:
        query = Chem.MolFromSmiles(template['retained_fragment_with_dummy'])
        # A query wildcard must match an actual attached atom; terminal retained
        # fragment alone cannot pass. All other atom/bond identities remain fixed.
        query = Chem.MolFromSmarts(Chem.MolToSmiles(query).replace('[90*]', '[*]'))
        if not mol.HasSubstructMatch(query, useChirality=True):
            raise GenerationError('retained_fragment_or_attachment_missing')
    warnings = []
    if any(s.specified == Chem.StereoSpecified.Unspecified for s in Chem.FindPotentialStereo(mol)):
        warnings.append('Unspecified stereochemistry; no stereoisomer was invented.')
    return warnings


def diverse_subset(compounds, count):
    """Greedy max-min Morgan/Tanimoto; canonical structure ID breaks every tie."""
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048, includeChirality=True)
    remaining = sorted(compounds, key=lambda c: (c['structure_id'], c['compound_id']))
    fps = {c['structure_id']: gen.GetFingerprint(Chem.MolFromSmiles(c['canonical_smiles'])) for c in remaining}
    chosen = []
    while remaining and len(chosen) < count:
        if chosen:
            remaining.sort(key=lambda c: (-min(1 - DataStructs.TanimotoSimilarity(fps[c['structure_id']], fps[x['structure_id']]) for x in chosen), c['structure_id'], c['compound_id']))
        chosen.append(remaining.pop(0))
    return chosen


def chemistry_metrics(compounds, seeds):
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048, includeChirality=True)
    fp = lambda c: gen.GetFingerprint(Chem.MolFromSmiles(c['canonical_smiles']))
    fps = [fp(c) for c in compounds]
    seed_fps = [fp(c) for c in seeds]
    distances = [1 - DataStructs.TanimotoSimilarity(a, b) for i, a in enumerate(fps) for b in fps[:i]]
    return dict(diversity_mean_pairwise_distance=sum(distances)/len(distances) if distances else None,
                diversity_pair_count=len(distances),
                maximum_seed_similarity={c['compound_id']: max(DataStructs.TanimotoSimilarity(f, s) for s in seed_fps) for c, f in zip(compounds, fps)} if seed_fps else {},
                fingerprint='Morgan radius 2, 2048 bits, chirality; Tanimoto', synthesis_feasibility='unassessed')
