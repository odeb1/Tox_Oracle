"""Shared screening executor for the CLI and local researcher workspace."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from .screening import combine_screening, render, summary, validate_discovery
from .validation import ContractValidationError, validate_request

ROOT = Path(__file__).resolve().parents[3]


def load(path):
    return json.loads(Path(path).read_text())


def model_command(args, action, request, output):
    return [str(args.model_python), "-m", "toxicity.src.baseline", action,
            "--input", str(request), "--output", str(output), "--model", str(args.model)]


def run_model(args, action, request, output):
    # Preserve the configured scientific environment; do not print subprocess output,
    # which could contain input structures or local paths in exception messages.
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(model_command(args, action, request, output), cwd=ROOT,
                            env=environment, capture_output=True, timeout=300)
    if result.returncode:
        raise ValueError(f"Local DILI {action} failed; check the pinned scientific environment")


def preflight(args):
    from toxoracle_discovery.boltz2 import validate_target, cache_key, cached_response, BoltzError
    target = load(args.target)
    validate_target(target)
    request = load(args.request)
    validate_request(request)
    writable = args.output_dir.resolve()
    while not writable.exists():
        writable = writable.parent
    checks = {
        "request_schema": True, "target_checksum_and_settings": True,
        "nvidia_credentials_present": bool(os.environ.get("NVIDIA_API_KEY") or os.environ.get("NGC_API_KEY") or os.environ.get("NVIDIA_BIONEMO_API_KEY")),
        "model_artifact": args.model.is_file(), "model_python": args.model_python.is_file(),
        "output_parent_writable": writable.is_dir() and os.access(writable, os.W_OK),
        "reference_in_request": target["reference_compound_id"] in [r["compound_id"] for r in request["compounds"]],
    }
    checks["complete_verified_cache"] = False
    if args.cache_dir:
        try:
            for compound in request["compounds"]:
                key = cache_key(compound, target)
                cached_response(args.cache_dir / (key + ".json"), key)
            checks["complete_verified_cache"] = True
        except (OSError, ValueError, TypeError, AttributeError, BoltzError):
            pass
    try:
        result = subprocess.run([str(args.model_python), "-c",
            "import rdkit,joblib,sklearn,numpy,shap; print('scientific_dependencies_ready')"],
            cwd=ROOT, capture_output=True, timeout=60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        checks["scientific_dependencies"] = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        checks["scientific_dependencies"] = False
    requirements = [value for name, value in checks.items() if name not in {"nvidia_credentials_present", "complete_verified_cache"}]
    ready = all(requirements) and (checks["nvidia_credentials_present"] or checks["complete_verified_cache"])
    print(json.dumps({"checks": checks, "ready_for_execution": ready,
                      "ready_for_live_run": all(requirements) and checks["nvidia_credentials_present"],
                      "network_and_entitlement": "not_tested", "credentials": "presence_only"}, indent=2))
    return 0 if ready else 2


def failed_toxicity(request):
    template = load(ROOT / "contracts/examples/toxicity.not-run.json")["results"][0]
    results = []
    for compound in request["compounds"]:
        row = deepcopy(template)
        row.update(compound_id=compound["compound_id"], structure_id=compound["structure_id"], status="failed",
                   error={"code": "local_inference_failed", "message": "Local DILI inference failed"})
        row["structural_evidence"].update({k: compound[k] for k in ("canonical_smiles", "atom_mapped_smiles", "standardization_version")})
        row["warnings"] = ["DILI inference did not complete; no safety conclusion can be made."]
        results.append(row)
    return dict(schema_version="2.0", request_id=request["request_id"], stream="toxicity", results=results)


class ScreeningCancelled(Exception):
    """Cooperative stop between scientific operations; never cancels a remote call."""


def execute(args, client=None, *, progress=None, cancelled=None, quiet=False):
    from toxoracle_discovery.boltz2 import (BoltzClient, BoltzError, digest, save,
        validate_target, predict_candidate, failed_candidate, rank_candidates)
    target = load(args.target)
    validate_target(target)
    request = load(args.request)
    validate_request(request)
    if target["reference_compound_id"] not in [r["compound_id"] for r in request["compounds"]]:
        raise ValueError("The reference compound must be present in the submitted batch")
    if args.command == "run" and not args.model.is_file():
        raise ValueError("Missing local DILI model artifact; inference never retrains automatically")
    output = args.output_dir.resolve()
    # Never overwrite a previous scientific run, even if it failed.
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "running", "command": args.command,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "target_sha256": hashlib.sha256(args.target.read_bytes()).hexdigest(),
                "request_sha256": hashlib.sha256(args.request.read_bytes()).hexdigest(),
                "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest() if args.model.is_file() else None,
                "git_commit": None}
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        manifest["git_commit"] = revision.stdout.strip() if revision.returncode == 0 else None
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        manifest["working_tree_dirty"] = bool(dirty.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        manifest["working_tree_dirty"] = None
    save(output / "run.json", manifest)
    def checkpoint(stage, **details):
        if cancelled and cancelled():
            raise ScreeningCancelled()
        if progress:
            progress(dict(stage=stage, **details))

    try:
        save(output / "request.json", request)
        save(output / "target.json", target)
        # Prepare/validate each shared structure locally before any external call.
        # Existing v2 fields must match exactly: do not silently rewrite a handoff.
        valid, problems = {}, {}
        checkpoint("preparing", total=len(request["compounds"]))
        for index, compound in enumerate(request["compounds"]):
            checkpoint("preparing", completed=index, total=len(request["compounds"]))
            one = dict(schema_version="2.0", request_id=request["request_id"], compounds=[compound])
            input_path, prepared_path = output / f"prepare_{index}.input.json", output / f"prepare_{index}.json"
            save(input_path, one)
            try:
                run_model(args, "prepare", input_path, prepared_path)
                prepared = load(prepared_path)["compounds"][0]
                if prepared != compound:
                    raise ValueError("Submitted canonical identity differs from standardisation")
                valid[compound["compound_id"]] = compound
            except (ValueError, OSError, subprocess.TimeoutExpired, KeyError):
                problems[compound["compound_id"]] = failed_candidate(compound, "invalid_structure", "Structure is invalid, unsupported or inconsistent with shared identity", "invalid_input")
        if client is None:
            # Lazy construction permits credential-free reuse of a validated cache.
            class LazyClient:
                def predict(self, payload):
                    return BoltzClient().predict(payload)
            client = LazyClient()
        records = dict(problems)
        reference = target["reference_compound_id"]
        order = [reference] + [r["compound_id"] for r in request["compounds"] if r["compound_id"] != reference]
        reference_ok = False
        for cid in order:
            checkpoint("reference" if cid == reference else "screening",
                       compound_id=cid, completed=len(records), total=len(request["compounds"]))
            if args.command == "reference-check" and cid != reference:
                continue
            if cid in problems:
                checkpoint("candidate_finished", compound_id=cid, status=records[cid]["status"],
                           completed=len(records), total=len(request["compounds"]))
                continue
            compound = valid[cid]
            if cid != reference and not reference_ok:
                records[cid] = failed_candidate(compound, "reference_check_failed", "Panel execution stopped: reference lacked usable structure and affinity")
                checkpoint("candidate_finished", compound_id=cid, status=records[cid]["status"],
                           completed=len(records), total=len(request["compounds"]))
                continue
            try:
                records[cid] = predict_candidate(compound, target, output / "boltz2" / digest(cid), client,
                                                  cache=args.cache_dir)
            except BoltzError as error:
                records[cid] = failed_candidate(compound, "boltz2_failed", str(error))
            except (ValueError, OSError, TypeError):
                records[cid] = failed_candidate(compound, "boltz2_failed", "Boltz-2 request or artifact validation failed; no prediction available")
            if cid == reference:
                r = records[cid]
                reference_ok = r["status"] == "ok" and r["binding_probability"] is not None and (r["affinity_pic50"] is not None or r["affinity_pred_value"] is not None)
            checkpoint("candidate_finished", compound_id=cid, status=records[cid]["status"],
                       binding_probability=records[cid]["binding_probability"],
                       structural_confidence=records[cid]["structural_confidence"],
                       completed=len(records), total=len(request["compounds"]))
        if args.command == "reference-check":
            save(output / "reference.json", records[reference])
            manifest["status"] = "complete" if reference_ok else "failed"
            if not quiet:
                print(json.dumps({"reference_passed": reference_ok, "output_dir": str(output)}))
            return 0 if reference_ok else 2
        discovery = dict(schema_version="3.0", stream="discovery", request_id=request["request_id"],
            target={"target_id": target["target_id"], "sequence_sha256": target["sequence_sha256"],
                    "manifest_sha256": manifest["target_sha256"], "reference_compound_id": reference},
            ranking_rule="mean_binder_desc_top2_v1",
            results=rank_candidates([records[r["compound_id"]] for r in request["compounds"]]))
        validate_discovery(request, discovery)
        # This immutable discovery snapshot is written BEFORE DILI is invoked.
        save(output / "discovery.json", discovery)
        checkpoint("shortlist_frozen", shortlist=[r["compound_id"] for r in sorted(
            discovery["results"], key=lambda r: r["rank"] or float("inf")) if r["shortlisted"]],
            discovery_sha256=hashlib.sha256((output / "discovery.json").read_bytes()).hexdigest())
        checkpoint("toxicity")
        try:
            run_model(args, "predict", output / "request.json", output / "toxicity.json")
            toxicity = load(output / "toxicity.json")
        except (ValueError, OSError, subprocess.TimeoutExpired):
            toxicity = failed_toxicity(request)
            save(output / "toxicity.json", toxicity)
        checkpoint("reporting")
        report = combine_screening(request, discovery, toxicity)
        save(output / "combined.json", report)
        (output / "combined.html").write_text(render(report))
        (output / "summary.txt").write_text(summary(report))
        complete = reference_ok and all(r["status"] == "ok" and r["rank"] is not None for r in discovery["results"]) and all(r["status"] == "ok" for r in toxicity["results"])
        manifest["status"] = "complete" if complete else "partial"
        if not quiet:
            print(summary(report))
            print(f"Report: {output / 'combined.html'}")
        return 0 if complete else 2
    except ScreeningCancelled:
        manifest["status"] = "cancelled"
        raise
    except Exception:
        manifest["status"] = "failed"
        raise
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(output / "run.json", manifest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "reference-check", "run"):
        p = commands.add_parser(name)
        p.add_argument("--request", type=Path, required=True)
        p.add_argument("--target", type=Path, required=True)
        p.add_argument("--output-dir", type=Path, required=True)
        p.add_argument("--model", type=Path, default=ROOT / "artifacts/models/dili_baseline.joblib")
        p.add_argument("--model-python", type=Path, default=ROOT / "toxicity/.venv/bin/python")
        p.add_argument("--cache-dir", type=Path, help="Explicit exact-input cache; omit for live-only execution")
    args = parser.parse_args(argv)
    for name in ("request", "target", "model"):
        setattr(args, name, getattr(args, name).resolve())
    # Resolving a venv interpreter symlink would silently select the base environment.
    args.model_python = args.model_python.absolute()
    try:
        return preflight(args) if args.command == "preflight" else execute(args)
    except (ContractValidationError, ValueError, OSError, ImportError, subprocess.TimeoutExpired) as error:
        # Controlled local error text only; no HTTP bodies or credentials.
        print(f"Screening stopped: {type(error).__name__}. Check input contracts, environment and run manifest.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
