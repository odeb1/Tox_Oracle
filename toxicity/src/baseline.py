"""Offline DILI baseline. Run from any directory; artifacts contain public data only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import sys

import joblib
import numpy as np
from rdkit import Chem, DataStructs, rdBase
from rdkit.Chem import rdFingerprintGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix,
                             roc_auc_score, balanced_accuracy_score)
from sklearn.model_selection import StratifiedGroupKFold

from toxicity.src.ingest_dilirank import standardize, POLICY

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / 'artifacts/models/dili_baseline.joblib'
DATA = ROOT / 'data/processed/dilirank2_model_ready.csv'
GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048, includeChirality=True)
# RDKit parser diagnostics can echo raw user input. Use fixed application error codes.
rdBase.DisableLog('rdApp.*')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def fingerprint(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError('invalid_smiles')
    return GEN.GetFingerprintAsNumPy(mol)


def prepare_compound(row):
    """Prepare once, or validate supplied v2 identity without silently rewriting it."""
    cid = row.get('compound_id')
    if not isinstance(cid, str) or not cid.strip() or len(cid) > 128:
        raise ValueError('invalid_compound_id')
    smiles = row.get('canonical_smiles', row.get('smiles'))
    if not isinstance(smiles, str) or len(smiles) > 10000 or any(c.isspace() for c in smiles) or '|' in smiles:
        raise ValueError('invalid_smiles')
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError('invalid_smiles')
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    clean = Chem.MolToSmiles(mol, isomericSmiles=True)
    info = standardize(clean)
    for key, expected in [('structure_id', info['structure_id']), ('standardization_version', POLICY)]:
        if row.get(key) is not None and row[key] != expected:
            raise ValueError('identity_mismatch')
    canonical = info['canonical_smiles']
    mapped = row.get('atom_mapped_smiles')
    if mapped is not None:
        if not isinstance(mapped,str) or any(c.isspace() for c in mapped) or '|' in mapped:
            raise ValueError('atom_map_mismatch')
        mapped_mol = Chem.MolFromSmiles(mapped)
        if mapped_mol is None:
            raise ValueError('atom_map_mismatch')
        ids = [a.GetAtomMapNum() for a in mapped_mol.GetAtoms()]
        if any(i <= 0 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('atom_map_mismatch')
        copy = Chem.Mol(mapped_mol)
        for atom in copy.GetAtoms():
            atom.SetAtomMapNum(0)
        if Chem.MolToSmiles(copy, isomericSmiles=True) != canonical:
            raise ValueError('atom_map_mismatch')
    else:
        mapped_mol = Chem.MolFromSmiles(canonical)
        for i, atom in enumerate(mapped_mol.GetAtoms(), 1):
            atom.SetAtomMapNum(i)
        mapped = Chem.MolToSmiles(mapped_mol, isomericSmiles=True)
    return dict(compound_id=cid, canonical_smiles=canonical, atom_mapped_smiles=mapped,
                structure_id=info['structure_id'], standardization_version=POLICY)


def make_groups(rows, scaffold=True):
    # Union by both scaffold and connectivity, including transitive overlaps.
    parents = list(range(len(rows)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    seen = {}
    for i, row in enumerate(rows):
        keys = ['connectivity:' + row['connectivity_group']]
        if scaffold:
            sm = MurckoScaffold.MurckoScaffoldSmiles(smiles=row['canonical_smiles'])
            if sm:
                keys.append('scaffold:' + sm)
        for key in keys:
            if key in seen:
                parents[find(i)] = find(seen[key])
            seen[key] = i
    return np.array([find(i) for i in range(len(rows))])


def split_data(rows, y):
    for use_scaffold in (True, False):
        groups = make_groups(rows, use_scaffold)
        folds = list(StratifiedGroupKFold(5, shuffle=True, random_state=42).split(np.zeros(len(y)), y, groups))
        test, valid = folds[0][1], folds[1][1]
        train = np.array(sorted(set(range(len(y))) - set(test) - set(valid)))
        if all(len(set(y[idx])) == 2 for idx in (train, valid, test)):
            return train, valid, test, groups, 'scaffold_and_connectivity' if use_scaffold else 'connectivity_only'
    raise ValueError('cannot_create_class_complete_splits')


def metrics(y, score, threshold):
    tn, fp, fn, tp = confusion_matrix(y, score >= threshold, labels=[0, 1]).ravel()
    return dict(n=len(y), positives=int(sum(y)), auroc=float(roc_auc_score(y, score)),
                average_precision=float(average_precision_score(y, score)),
                brier=float(brier_score_loss(y, score)), threshold=float(threshold),
                sensitivity=float(tp / (tp + fn)), specificity=float(tn / (tn + fp)),
                confusion_matrix=[[int(tn), int(fp)], [int(fn), int(tp)]])


def choose_threshold(y, p):
    values = np.unique(np.r_[0., p, 1.])
    return float(max(values, key=lambda t: (balanced_accuracy_score(y, p >= t),
                                           np.mean(p[y == 1] >= t), -t)))


def train(data=DATA, output=MODEL):
    rows = sorted(list(csv.DictReader(Path(data).open())), key=lambda r: r['structure_id'])
    source = json.loads((ROOT / 'data/manifests/dilirank2_acquisition_report.json').read_text())
    if digest(data) != source['artifacts']['dilirank2_model_ready.csv']:
        raise ValueError('dataset_manifest_checksum_mismatch')
    y = np.array([int(r['dili_label']) for r in rows])
    X = np.array([fingerprint(r['canonical_smiles']) for r in rows])
    tr, va, te, groups, split_kind = split_data(rows, y)
    search, best = [], None
    for depth, leaf, weight in itertools.product([None, 12], [2, 5], [None, 'balanced']):
        params = dict(n_estimators=500, max_depth=depth, min_samples_leaf=leaf,
                      class_weight=weight, random_state=42, n_jobs=-1)
        rf = RandomForestClassifier(**params).fit(X[tr], y[tr])
        ap = float(average_precision_score(y[va], rf.predict_proba(X[va])[:, 1]))
        search.append(dict(params=params, validation_average_precision=ap))
        if best is None or ap > best[0]:
            best = (ap, rf, params)
    rf = best[1]
    folds = list(StratifiedGroupKFold(3, shuffle=True, random_state=42).split(X[tr], y[tr], groups[tr]))
    if not all(len(set(y[tr][idx])) == 2 for pair in folds for idx in pair):
        raise ValueError('calibration_folds_missing_class')
    calibrated = CalibratedClassifierCV(RandomForestClassifier(**best[2]), method='sigmoid',
                                        cv=folds, ensemble=False).fit(X[tr], y[tr])
    raw = rf.predict_proba(X[va])[:, 1]
    cal = calibrated.predict_proba(X[va])[:, 1]
    use_cal = brier_score_loss(y[va], cal) < brier_score_loss(y[va], raw)
    predictor = calibrated if use_cal else rf
    vp = predictor.predict_proba(X[va])[:, 1]
    threshold = choose_threshold(y[va], vp)
    lr = LogisticRegression(C=1, max_iter=3000, random_state=42).fit(X[tr], y[tr])
    lr_threshold = choose_threshold(y[va], lr.predict_proba(X[va])[:, 1])
    artifact = dict(rf=rf, predictor=predictor, lr=lr, threshold=threshold, lr_threshold=lr_threshold,
                    calibrated=bool(use_cal), data_sha256=digest(data), rows=rows,
                    train_indices=tr, validation_indices=va, test_indices=te, groups=groups,
                    train_fingerprints=X[tr], split_kind=split_kind, fingerprint='Morgan radius=2 bits=2048 chirality=true',
                    rdkit_version=rdBase.rdkitVersion, model_id='toxoracle_dili_rf_v1')
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    report = dict(data_sha256=artifact['data_sha256'], split_kind=split_kind, fingerprint=artifact['fingerprint'],
                  counts={k:dict(n=len(idx), positive=int(sum(y[idx]))) for k, idx in [('train',tr),('validation',va),('test',te)]},
                  search=search, selected_params=best[2], calibration_selected=bool(use_cal),
                  validation_brier_raw=float(brier_score_loss(y[va], raw)),
                  validation_brier_calibrated=float(brier_score_loss(y[va], cal)),
                  validation=metrics(y[va],vp,threshold), model_sha256=digest(output))
    save_json(ROOT/'evaluation/reports/baseline_selection.json', report)
    membership = {int(i):name for name,idx in [('train',tr),('validation',va),('test',te)] for i in idx}
    save_json(ROOT/'data/manifests/dili_baseline_split.json', dict(seed=42, data_sha256=digest(data), method=split_kind,
              records=[dict(structure_id=r['structure_id'], compound_id=r['compound_id'], group=int(groups[i]),
                            partition=membership[i]) for i,r in enumerate(rows)]))
    print(json.dumps(report['counts']))


def evaluate(model=MODEL):
    a = joblib.load(model)
    idx = a['test_indices']
    y = np.array([int(a['rows'][i]['dili_label']) for i in idx])
    X = np.array([fingerprint(a['rows'][i]['canonical_smiles']) for i in idx])
    selected = a['predictor'].predict_proba(X)[:,1]
    raw = a['rf'].predict_proba(X)[:,1]
    lp = a['lr'].predict_proba(X)[:,1]
    report = dict(model_sha256=digest(model), data_sha256=a['data_sha256'],
                  random_forest=metrics(y,selected,a['threshold']),
                  raw_random_forest_brier=float(brier_score_loss(y,raw)),
                  logistic_reference=metrics(y,lp,a['lr_threshold']),
                  limitations=['Small retrospective drug-label dataset; not patient incidence or dose-response.',
                               'Demo cases selected after evaluation; not prespecified independent evidence.',
                               'Calibration is population-dependent; no guarantee under distribution shift.'])
    save_json(ROOT/'evaluation/reports/baseline_test.json', report)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5,4))
    ax.plot([0,1],[0,1], '--', color='gray')
    for title,p in [('RF raw',raw),('RF selected',selected),('Logistic reference',lp)]:
        observed,predicted = calibration_curve(y,p,n_bins=5,strategy='quantile')
        ax.plot(predicted,observed,'o-',label=title)
    ax.set(xlabel='Mean predicted score',ylabel='Observed DILI-positive fraction',xlim=(0,1),ylim=(0,1))
    ax.legend(); fig.tight_layout(); fig.savefig(ROOT/'evaluation/reports/baseline_reliability.png'); plt.close(fig)
    # Deterministic illustrative examples: first test negative, first positive, next remaining.
    chosen = [next(int(i) for i in idx if int(a['rows'][i]['dili_label']) == label) for label in (0,1)]
    chosen.append(next(int(i) for i in idx if i not in chosen))
    request = dict(schema_version='2.0', request_id='heldout_demo_v1',
                   compounds=[prepare_compound(a['rows'][i]) for i in chosen])
    save_json(ROOT/'demo/examples/dili_request.json',request)
    save_json(ROOT/'demo/examples/dili_response.json',predict(request,a))
    print(json.dumps(report,indent=2))


def empty_result(row):
    return dict(compound_id=row.get('compound_id') if isinstance(row.get('compound_id'),str) else None,
      structure_id=row.get('structure_id') if isinstance(row.get('structure_id'),str) else None, status='failed',
      assessment=dict(endpoint_id='human_dili_binary_v1', positive_definition='Most or Less DILI concern',
        negative_definition='No DILI concern', context=dict(species='human',system='drug_level_annotation',conditions=None),
        evidence_type='model_prediction',risk_score=None,score_kind='unavailable',direction='higher_is_more_toxic',
        threshold=None,call='unavailable',calibration=dict(status='not_assessed',reference=None),
        uncertainty=dict(method='not_implemented',value=None),applicability=dict(method='nearest_train_tanimoto',value=None)),
      structural_evidence=dict(canonical_smiles=None,atom_mapped_smiles=None,standardization_version=POLICY,
        attribution_status='unavailable',attribution_method=None,attribution_target=None,attribution_scale=None,
        attribution_reference=None,fragments=[],structure_artifacts=[],interactions=[],mechanism_hypotheses=[]),
      supplementary_metrics=[],provenance=dict(method_id='toxoracle_dili_rf_v1',model_origin='trained',
        data_version='curated_dilirank2_v1',training_membership='unknown',evidence_refs=[]),
      warnings=['No patient incidence, exposure response or causal mechanism is inferred.', 'Uncertainty intervals are not implemented.'],error=None)


def fragments(rf, prepared, x):
    import shap
    mol = Chem.MolFromSmiles(prepared['atom_mapped_smiles'])
    atom_ids = [a.GetAtomMapNum() for a in mol.GetAtoms()]
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    extra = rdFingerprintGenerator.AdditionalOutput(); extra.AllocateBitInfoMap()
    fp = GEN.GetFingerprint(mol, additionalOutput=extra)
    explainer = shap.TreeExplainer(rf, feature_perturbation='tree_path_dependent', model_output='raw')
    values = explainer.shap_values(x[None,:])[0,:,1]
    result = []
    for bit in sorted(extra.GetBitInfoMap(),key=lambda b: abs(values[b]),reverse=True)[:10]:
        environments = extra.GetBitInfoMap()[bit]
        for n,(center,radius) in enumerate(environments):
            bonds = list(Chem.FindAtomEnvironmentOfRadiusN(mol,radius,center))
            atoms = {center}
            for b in bonds:
                atoms.update([mol.GetBondWithIdx(b).GetBeginAtomIdx(),mol.GetBondWithIdx(b).GetEndAtomIdx()])
            result.append(dict(fragment_id=f'bit_{bit}_env_{n}',atom_map_ids=sorted(atom_ids[i] for i in atoms),
              pattern=Chem.MolFragmentToSmiles(mol,atomsToUse=sorted(atoms),bondsToUse=bonds),
              contribution=float(values[bit]),evidence_kind='feature_attribution',
              source_ref=f'Morgan_bit_{bit}',mapping_ambiguous=len(environments)>1))
    return result, float(explainer.expected_value[1])


def predict(request, artifact=None):
    if request.get('schema_version') != '2.0' or not isinstance(request.get('compounds'),list):
        raise ValueError('invalid_request_envelope')
    if not isinstance(request.get('request_id'),str) or not request['request_id']:
        raise ValueError('invalid_request_id')
    if not 1 <= len(request['compounds']) <= 1000:
        raise ValueError('invalid_batch_size')
    a = artifact if artifact is not None else joblib.load(MODEL)
    rows = request['compounds']
    if any(not isinstance(r,dict) for r in rows):
        raise ValueError('invalid_compound_record')
    ids = [r.get('compound_id') for r in rows]
    train_smiles = {a['rows'][i]['canonical_smiles'] for i in a['train_indices']}
    validation_smiles = {a['rows'][i]['canonical_smiles'] for i in a['validation_indices']}
    results = []
    for row in rows:
        out = empty_result(row)
        try:
            if ids.count(row.get('compound_id')) > 1:
                raise ValueError('duplicate_compound_id')
            prepared = prepare_compound(row)
            x = fingerprint(prepared['canonical_smiles'])
            score = float(a['predictor'].predict_proba(x[None,:])[0,1])
            intersection = np.sum(a['train_fingerprints'] & x,axis=1)
            union = np.sum(a['train_fingerprints'] | x,axis=1)
            similarity = float(np.max(intersection/np.maximum(union,1)))
            out.update(structure_id=prepared['structure_id'],status='ok')
            out['assessment'].update(risk_score=score,score_kind='calibrated_probability' if a['calibrated'] else 'uncalibrated_score',
                threshold=a['threshold'],call='positive' if score >= a['threshold'] else 'negative',
                calibration=dict(status='assessed_sigmoid' if a['calibrated'] else 'assessed_raw_retained',reference='evaluation/reports/baseline_test.json'),
                applicability=dict(method='nearest_train_tanimoto',value=similarity))
            out['structural_evidence'].update({k:prepared[k] for k in ['canonical_smiles','atom_mapped_smiles','standardization_version']})
            try:
                fr,base = fragments(a['rf'],prepared,x)
                import shap
                out['structural_evidence'].update(attribution_status='available',attribution_method=f'TreeSHAP {shap.__version__} tree_path_dependent',
                    attribution_target='raw_random_forest_positive_class',attribution_scale='raw_class_probability',
                    attribution_reference=dict(expected_value=base,background='training tree path counts'),fragments=fr)
                out['warnings'].append('Fragment evidence shows top present fingerprint features only; repeated bit contributions must not be summed. Calibrated scores have a different explanation scale.')
            except Exception:
                out['warnings'].append('Attribution computation failed; score remains available.')
            out['provenance'].update(data_version=a['data_sha256'],
                training_membership='included' if prepared['canonical_smiles'] in train_smiles else 'excluded',
                evidence_refs=['data/manifests/dili_baseline_split.json','evaluation/reports/baseline_test.json'])
            if prepared['canonical_smiles'] in validation_smiles:
                out['warnings'].append('Compound used for model selection and thresholding; not an unseen evaluation case.')
        except ValueError as e:
            allowed = {'invalid_smiles','invalid_compound_id','identity_mismatch','atom_map_mismatch','duplicate_compound_id'}
            reason = str(e) if str(e) in allowed else 'unsupported_structure'
            out.update(status='invalid_input' if reason in allowed else 'unsupported',error=reason)
        except Exception:
            out.update(status='failed',error='prediction_failed')
        results.append(out)
    return dict(schema_version='2.0',request_id=request['request_id'],stream='toxicity',results=results)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['train','evaluate','prepare','predict'])
    p.add_argument('--input',type=Path); p.add_argument('--output',type=Path); p.add_argument('--model',type=Path,default=MODEL)
    args = p.parse_args()
    if args.command == 'train':
        train(args.input or DATA,args.model)
    elif args.command == 'evaluate':
        evaluate(args.model)
    else:
        if not args.input or not args.output:
            p.error('--input and --output are required')
        request = json.loads(args.input.read_text())
        if args.command == 'prepare':
            result = dict(schema_version='2.0',request_id=request.get('request_id','prepared_v1'),
                          compounds=[prepare_compound(r) for r in request['compounds']])
        else:
            result = predict(request,joblib.load(args.model))
        save_json(args.output,result)


if __name__ == '__main__':
    main()
