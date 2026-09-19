"""Bounded hosted Boltz-2 inference; no toxicity meaning is assigned to affinity."""
from __future__ import annotations

import hashlib
import json
import math
import os
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://health.api.nvidia.com/v1/biology/mit/boltz2/predict"
SETTINGS = {
    "recycling_steps": 3, "sampling_steps": 50, "diffusion_samples": 1,
    "sampling_steps_affinity": 200, "diffusion_samples_affinity": 5,
    "output_format": "mmcif", "affinity_mw_correction": False,
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


class BoltzError(RuntimeError):
    pass


class BoltzClient:
    def __init__(self, key=None, timeout=600):
        self.key = key or os.environ.get("NVIDIA_API_KEY") or os.environ.get("NGC_API_KEY") or os.environ.get("NVIDIA_BIONEMO_API_KEY")
        if not self.key:
            raise BoltzError("Missing NVIDIA_API_KEY or NGC_API_KEY in the execution environment")
        self.timeout = timeout

    def predict(self, payload):
        request = Request(ENDPOINT, data=json.dumps(payload).encode(), method="POST",
                          headers={"Authorization": "Bearer " + self.key,
                                   "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                # Do not interpret an async acknowledgement as an inference result.
                if response.status != 200:
                    raise BoltzError("NVIDIA did not return a completed synchronous result")
                result = json.loads(response.read())
        except HTTPError as error:
            # Vendor error bodies can contain request data. Never log them or auth headers.
            raise BoltzError(f"NVIDIA HTTP {error.code}; no completed prediction") from None
        except (URLError, socket.timeout, TimeoutError, OSError):
            raise BoltzError("NVIDIA connection failed or timed out; no automatic retry") from None
        except (ValueError, UnicodeError):
            raise BoltzError("NVIDIA returned invalid JSON") from None
        if not isinstance(result, dict):
            raise BoltzError("NVIDIA returned an invalid response object")
        return result


def numbers(value, probability=False):
    if not isinstance(value, list) or not value:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
           or (probability and not 0 <= v <= 1) for v in value):
        return None
    return value


def validate_target(target):
    if not isinstance(target, dict):
        raise ValueError("Target manifest must be an object")
    if target.get("schema_version") != "1.0":
        raise ValueError("Unsupported target manifest version")
    sequence = target.get("sequence", "")
    if not isinstance(sequence, str) or not sequence or len(sequence) > 4096 or any(c not in "ACDEFGHIKLMNPQRSTVWYX" for c in sequence):
        raise ValueError("Invalid target sequence")
    if hashlib.sha256(sequence.encode()).hexdigest() != target.get("sequence_sha256"):
        raise ValueError("Target sequence checksum mismatch")
    if target.get("inference_settings") != SETTINGS:
        raise ValueError("Target settings do not match the frozen Boltz-2 protocol")
    if any(not isinstance(target.get(k), str) or not target[k] for k in ("target_id", "reference_compound_id")):
        raise ValueError("Missing target or reference identity")


def request_payload(compound, target):
    return dict(target["inference_settings"],
                   polymers=[{"id": "A", "molecule_type": "protein", "sequence": target["sequence"]}],
                   ligands=[{"id": "L1", "smiles": compound["canonical_smiles"], "predict_affinity": True}])


def cache_key(compound, target):
    return digest({"adapter_version": "boltz2_v1", "endpoint": ENDPOINT,
                   "target": target, "compound": compound, "payload": request_payload(compound, target)})


def cached_response(path, key):
    entry = json.loads(Path(path).read_text())
    if not isinstance(entry, dict) or not isinstance(entry.get("response"), dict) or entry.get("key") != key or digest(entry.get("response")) != entry.get("response_sha256"):
        raise BoltzError("Cache integrity check failed")
    return entry["response"]


def predict_candidate(compound, target, directory, client, *, cache=None):
    """Persist raw response and artifacts. Cache reuse is explicit and integrity checked."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = request_payload(compound, target)
    key = cache_key(compound, target)
    cache_path = Path(cache) / (key + ".json") if cache else None
    mode = "live"
    if cache_path and cache_path.is_file():
        raw = cached_response(cache_path, key)
        mode = "cached"
    else:
        raw = client.predict(payload)
    # Reject non-finite vendor data before saving it to standards-compliant JSON.
    try:
        response_digest = digest(raw)
    except (ValueError, TypeError):
        raise BoltzError("Non-finite or invalid vendor response") from None
    save(directory / "request.json", payload)
    save(directory / "response.json", raw)
    raw_artifact = {"uri": str((directory / "response.json").resolve()),
                    "sha256": hashlib.sha256((directory / "response.json").read_bytes()).hexdigest()}
    structures = []
    for i, item in enumerate(raw.get("structures", []) if isinstance(raw.get("structures"), list) else []):
        if not isinstance(item, dict) or item.get("format") not in {"mmcif", "cif"}:
            continue
        content = item.get("structure")
        if not isinstance(content, str) or not content.strip().startswith("data_") or "_atom_site." not in content:
            continue
        path = directory / f"complex_{i + 1}.cif"
        path.write_text(content)
        structures.append({"uri": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "format": "mmcif", "origin": "predicted", "atom_mapping_status": "unavailable"})
    affinity = raw.get("affinities", {}).get("L1", {}) if isinstance(raw.get("affinities"), dict) else {}
    affinity = affinity if isinstance(affinity, dict) else {}
    binder = numbers(affinity.get("affinity_probability_binary"), probability=True)
    confidence = numbers(raw.get("confidence_scores"), probability=True)
    version = raw.get("model_version")
    version = version if isinstance(version, str) and version else None
    record = dict(compound, status="ok" if structures else "failed",
                  binding_probability=binder, mean_binding_probability=sum(binder)/len(binder) if binder else None,
                  affinity_pic50=numbers(affinity.get("affinity_pic50")),
                  affinity_pred_value=numbers(affinity.get("affinity_pred_value")),
                  structural_confidence=confidence, rank=None, shortlisted=False,
                  structures=structures, raw_response=raw_artifact,
                  provenance={"method_id": "nvidia_nim_boltz2", "endpoint": ENDPOINT,
                              "execution_mode": mode, "cache_key": key, "response_digest": response_digest,
                              "served_model_version": version, "version_status": "reported" if version else "not_reported"},
                  warnings=["Binding predictions are not measured affinity or therapeutic efficacy.",
                            "Predicted-pose atom mapping and contacts are unavailable; shared input atom IDs are retained."],
                  error=None)
    if not structures:
        record["error"] = {"code": "missing_structure", "message": "No usable predicted complex returned"}
    if binder is None:
        record["warnings"].append("Binding likelihood missing or invalid; candidate remains unranked.")
    if mode == "cached":
        record["warnings"].append("Reused exact-input cached result; current hosted model version was not rechecked.")
    if cache_path and mode == "live" and record["status"] == "ok" and binder is not None:
        save(cache_path, {"key": key, "response_sha256": response_digest, "response": raw})
    return record


def failed_candidate(compound, code, message, status="failed"):
    return dict(compound, status=status, binding_probability=None, mean_binding_probability=None,
                affinity_pic50=None, affinity_pred_value=None, structural_confidence=None,
                rank=None, shortlisted=False, structures=[], raw_response=None,
                provenance={"method_id": "nvidia_nim_boltz2", "endpoint": ENDPOINT,
                            "execution_mode": "not_run", "cache_key": None, "response_digest": None,
                            "served_model_version": None, "version_status": "not_reported"},
                warnings=[], error={"code": code, "message": message})


def rank_candidates(records, shortlist_size=2):
    for row in records:
        row.update(rank=None, shortlisted=False)
    eligible = sorted((r for r in records if r["status"] == "ok" and r["mean_binding_probability"] is not None),
                      key=lambda r: (-r["mean_binding_probability"], r["compound_id"]))
    for rank, row in enumerate(eligible, 1):
        row.update(rank=rank, shortlisted=rank <= shortlist_size)
    return records
