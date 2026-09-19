"""Loopback researcher workspace, sharing the local privacy gateway's approval gate."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from privacy.engine import MAX_FIELD, PrivacyError, parse, toxicity_request
from privacy.server import create_app as privacy_app
from toxoracle_discovery.boltz2 import validate_target

from .screen_cli import ROOT, load
from .screening import validate_screening_report
from .validation import ContractValidationError, validate_request
from .workspace_jobs import JobManager, WorkspaceConfig, WorkspaceError, check_execution

STATIC = Path(__file__).parent / "web_static"
ORIGIN = "http://127.0.0.1:8766"
MAX_CANDIDATES = 32


def create_app(config=None, *, detector=None, token=None, manager=None, preflight=check_execution, origin=ORIGIN):
    config = config or WorkspaceConfig()
    from .rosalind import RosalindClient
    assistant = RosalindClient()
    manager = manager or JobManager(config, assistant=assistant)
    app = privacy_app(detector=detector, token=token, origin=origin, static_dir=STATIC)
    app.state.jobs = manager
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            try:
                yield
            finally:
                manager.close()
    app.router.lifespan_context = lifespan

    target = load(ROOT / "discovery/configs/targets/abl1.json")
    validate_target(target)
    example = load(ROOT / "demo/examples/abl1_request.json")
    reference = next(c for c in example["compounds"] if c["compound_id"] == target["reference_compound_id"])
    payload = app.state.privacy_payload
    session = app.state.privacy_session
    reviewed = app.state.privacy_reviewed

    @app.exception_handler(WorkspaceError)
    async def workspace_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/workspace")
    async def workspace(request: Request):
        data = await payload(request)
        session(data)
        return dict(targets=[dict(target_id=target["target_id"], name=target["protein_name"],
            reference_compound_id=target["reference_compound_id"], pdb_id=target["pdb_id"],
            sequence_sha256=target["sequence_sha256"], sequence_length=len(target["sequence"]))],
            checks=dict(dili_model=config.model.is_file(), model_python=config.model_python.is_file(),
                privacy_checkpoint=(ROOT / "artifacts/privacy/checkpoint/manifest.json").is_file(),
                privacy_runtime=importlib.util.find_spec("opf") is not None,
                cache_directory=config.cache.is_dir(),
                nvidia_credentials=bool(os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVIDIA_BIONEMO_API_KEY") or os.environ.get("NGC_API_KEY"))),
            rosalind=assistant.configuration(), runs=manager.for_owner(data["session_id"]),
            max_candidates=MAX_CANDIDATES)

    @app.post("/api/example")
    async def public_example(request: Request):
        session(await payload(request))
        return dict(content=json.dumps(example, indent=2), format="json",
            prompt="Which ABL1 discovery candidates merit follow-up, and how does predicted human DILI concern change that decision?")

    @app.post("/api/rosalind/verify")
    async def verify_rosalind(request: Request):
        session(await payload(request))
        # Explicit connection check sends only a fixed, non-scientific greeting.
        return await run_in_threadpool(assistant.verify)

    @app.post("/api/study/scan")
    async def scan_study(request: Request):
        data = await payload(request)
        state = session(data)
        # Even a malformed edit invalidates any older approval.
        state.update(version=state["version"] + 1, snapshot=None, approved=None)
        if data.get("target_id") != target["target_id"]:
            raise WorkspaceError("unsupported_target")
        if data.get("mode") not in {"live", "cached"} or type(data.get("use_rosalind")) is not bool:
            raise WorkspaceError("invalid_execution_mode")
        if data["mode"] == "cached" and data["use_rosalind"]:
            raise WorkspaceError("cached_mode_is_offline")
        if data["use_rosalind"] and assistant.configuration()["verification"] != "verified":
            raise WorkspaceError("rosalind_interface_not_verified")
        prompt = data.get("research_prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_FIELD:
            raise WorkspaceError("research_prompt_required")
        if data.get("format") not in {"csv", "json"}:
            raise WorkspaceError("candidate_format_required")
        uploaded = parse(data.get("content"), data["format"])
        envelope = uploaded if isinstance(uploaded, dict) else {"compounds": uploaded}
        compounds = envelope.get("compounds")
        if not isinstance(compounds, list) or not 2 <= len(compounds) <= MAX_CANDIDATES or any(not isinstance(c, dict) for c in compounds):
            raise WorkspaceError("candidate_count_invalid")
        envelope = dict(envelope, research_prompt=prompt)
        result = await app.state.privacy_scan(dict(session_id=data["session_id"], enabled=True,
            content=json.dumps(envelope, ensure_ascii=False, allow_nan=False), format="json"))
        if result["blocked"]:
            return result
        prepared = await run_in_threadpool(toxicity_request, result)
        # An edit/reset during local preparation must revoke submission as well.
        _, current = reviewed(dict(session_id=data["session_id"], scan_id=result["scan_id"]), False)
        if current is not result:
            raise PrivacyError("scan_invalidated")
        validate_request(prepared)
        actual_reference = next((c for c in prepared["compounds"] if c["compound_id"] == reference["compound_id"]), None)
        if actual_reference is None:
            raise WorkspaceError("reference_required")
        if actual_reference["structure_id"] != reference["structure_id"]:
            raise WorkspaceError("reference_identity_mismatch")
        sanitized = json.loads(result["sanitized"])
        safe_prompt = sanitized.get("research_prompt")
        if not isinstance(safe_prompt, str) or not safe_prompt.strip():
            raise WorkspaceError("research_prompt_required")
        result["study"] = dict(research_prompt=safe_prompt, request=prepared,
            target_id=target["target_id"], target_sequence_sha256=target["sequence_sha256"],
            mode=data["mode"], use_rosalind=data["use_rosalind"])
        result["audit"]["study_sha256"] = hashlib.sha256(json.dumps(result["study"], sort_keys=True).encode()).hexdigest()
        return result

    @app.post("/api/study/submit")
    async def submit_study(request: Request):
        data = await payload(request)
        state, snapshot = reviewed(data)
        if "study" not in snapshot:
            raise PrivacyError("study_review_required")
        old = manager.existing(data["session_id"], snapshot["scan_id"])
        if old:
            return old.snapshot()
        study = snapshot["study"]
        await run_in_threadpool(preflight, config, study["request"], target, study["mode"])
        # Do not start a paid operation if approval was revoked while preflight ran.
        _, current = reviewed(data)
        if current is not snapshot or state["snapshot"] is not snapshot:
            raise PrivacyError("scan_invalidated")
        return manager.submit(data["session_id"], snapshot, deepcopy(target)).snapshot()

    async def owned_job(request):
        data = await payload(request)
        session(data)
        return manager.owned(data["session_id"], data.get("job_id")), data

    @app.post("/api/run/status")
    async def run_status(request: Request):
        job, _ = await owned_job(request)
        return job.snapshot()

    @app.post("/api/run/cancel")
    async def cancel_run(request: Request):
        job, _ = await owned_job(request)
        with job.lock:
            if job.state["status"] in {"queued", "running"}:
                job.stop.set()
                job.update(cancel_requested=True)
        return job.snapshot()

    @app.post("/api/run/report")
    async def run_report(request: Request):
        job, _ = await owned_job(request)
        if not job.snapshot()["report_available"]:
            raise WorkspaceError("report_not_ready")
        report = load(job.directory / "science/combined.json")
        validate_screening_report(report)
        return dict(report=report, run=job.snapshot())

    @app.post("/api/run/download")
    async def download(request: Request):
        job, data = await owned_job(request)
        files = {"report": ("science/combined.json", "application/json"),
                 "html": ("science/combined.html", "text/html"),
                 "discovery": ("science/discovery.json", "application/json"),
                 "approval": ("approved.json", "application/json")}
        kind = data.get("kind")
        if kind not in files:
            raise WorkspaceError("invalid_download_kind")
        relative, mime = files[kind]
        if kind in {"report", "html"} and not job.snapshot()["report_available"]:
            raise WorkspaceError("report_not_ready")
        path = job.directory / relative
        if not path.is_file():
            raise WorkspaceError("artifact_not_ready")
        return dict(content=path.read_text(), filename=f"toxoracle-{job.job_id[:8]}-{path.name}", mime=mime)

    @app.post("/api/report/inspect")
    async def inspect_report(request: Request):
        # Local viewing only; imported reports cannot trigger any provider calls.
        data = await payload(request)
        session(data)
        report = parse(data.get("content"), "json")
        try:
            validate_screening_report(report)
        except (ContractValidationError, KeyError, TypeError, ValueError):
            raise WorkspaceError("invalid_screening_report") from None
        return dict(report=report, run=None)

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--model", type=Path, default=WorkspaceConfig.model)
    parser.add_argument("--model-python", type=Path, default=WorkspaceConfig.model_python)
    parser.add_argument("--cache-dir", type=Path, default=WorkspaceConfig.cache)
    parser.add_argument("--runs-dir", type=Path, default=WorkspaceConfig.runs)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a loopback port between 1024 and 65535")
    config = WorkspaceConfig(args.runs_dir.resolve(), args.model.resolve(), args.model_python.absolute(), args.cache_dir.resolve())
    import uvicorn
    origin = f"http://127.0.0.1:{args.port}"
    print(f"ToxOracle researcher workspace: {origin}")
    uvicorn.run(create_app(config, origin=origin), host="127.0.0.1", port=args.port,
                access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
