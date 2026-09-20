"""Bounded, local background execution of approved studies. No raw uploads here."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid

from .assistant import AssistantError
from .screen_cli import ROOT, ScreeningCancelled, execute, load
from .screening import validate_discovery, validate_screening_report


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    """Atomic local artifacts, including progress polled during execution."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


@dataclass(frozen=True)
class WorkspaceConfig:
    runs: Path = ROOT / "artifacts/web/runs"
    model: Path = ROOT / "artifacts/models/dili_baseline.joblib"
    model_python: Path = ROOT / "toxicity/.venv/bin/python"
    cache: Path = ROOT / "artifacts/cache/boltz2"


class WorkspaceError(ValueError):
    """Fixed user-facing codes; never include subprocess or provider response bodies."""


class CachedOnlyClient:
    def generate(self, payload):
        from toxoracle_discovery.generation import GenerationError
        raise GenerationError("Cached-only generation has no network fallback")

    def predict(self, payload):
        from toxoracle_discovery.boltz2 import BoltzError
        raise BoltzError("Cached-only execution has no network fallback")


def check_execution(config, request, target, mode):
    """Run before persisting an approved job; checks do not contact providers."""
    if not config.model.is_file():
        raise WorkspaceError("dili_model_missing")
    if not config.model_python.is_file():
        raise WorkspaceError("model_python_missing")
    try:
        result = subprocess.run([str(config.model_python), "-c", "import rdkit,joblib,sklearn,numpy,shap"],
                                capture_output=True, timeout=60, cwd=ROOT,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if result.returncode:
            raise WorkspaceError("scientific_environment_unavailable")
    except (OSError, subprocess.TimeoutExpired):
        raise WorkspaceError("scientific_environment_unavailable") from None
    if mode == "cached" and request.get("mode") == "generate_screen":
        # Every later dynamic cache lookup has a network-denying client.
        if not (config.cache.parent / "genmol").is_dir():
            raise WorkspaceError("complete_cache_required")
    elif mode == "cached":
        from toxoracle_discovery.boltz2 import cache_key, cached_response, BoltzError
        try:
            for compound in request["compounds"]:
                key = cache_key(compound, target)
                cached_response(config.cache / (key + ".json"), key)
        except (OSError, ValueError, TypeError, AttributeError, BoltzError):
            raise WorkspaceError("complete_cache_required") from None
    elif mode == "live":
        if not any(os.environ.get(k) for k in ("NVIDIA_API_KEY", "NVIDIA_BIONEMO_API_KEY", "NGC_API_KEY")):
            raise WorkspaceError("nvidia_credentials_missing")
    else:
        raise WorkspaceError("invalid_execution_mode")


@dataclass
class Job:
    job_id: str
    owner: str
    scan_id: str
    directory: Path
    state: dict
    stop: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def snapshot(self):
        with self.lock:
            return deepcopy(self.state)

    def update(self, **values):
        with self.lock:
            self.state.update(values)
            self.state["updated_at"] = now()
            write_json(self.directory / "job.json", self.state)

    def progress(self, event):
        with self.lock:
            self.state["events"].append(dict(event, at=now()))
            if event["stage"] == "candidates_ready":
                self.state["candidates"] = event["candidates"]
                self.state["candidate_count"] = len(event["candidates"])
            if event["stage"] == "shortlist_frozen":
                self.state["shortlist"] = event["shortlist"]
                self.state["discovery_sha256"] = event["discovery_sha256"]
            self.update(stage=event["stage"])


class JobManager:
    def __init__(self, config, *, runner=execute, assistant=None, design_runner=None):
        from .design_cli import execute as design_execute
        self.design_runner = design_runner or design_execute
        self.config, self.runner, self.assistant = config, runner, assistant
        self.jobs = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="toxoracle")

    def owned(self, owner, job_id):
        with self.lock:
            job = self.jobs.get(job_id) if isinstance(job_id, str) else None
            if job is None or job.owner != owner:
                raise WorkspaceError("run_not_found")
            return job

    def for_owner(self, owner):
        with self.lock:
            return [j.snapshot() for j in self.jobs.values() if j.owner == owner]

    def existing(self, owner, scan_id):
        with self.lock:
            return next((j for j in self.jobs.values() if j.owner == owner and j.scan_id == scan_id), None)

    def submit(self, owner, snapshot, target):
        with self.lock:
            # Retransmission after a lost HTTP response must not repeat paid inference.
            old = next((j for j in self.jobs.values() if j.owner == owner and j.scan_id == snapshot["scan_id"]), None)
            if old:
                return old
            if any(j.state["status"] in {"queued", "running", "awaiting_plan"} for j in self.jobs.values()):
                raise WorkspaceError("workspace_busy")
            if len(self.jobs) >= 32:
                raise WorkspaceError("run_limit_reached")
            job_id = uuid.uuid4().hex
            directory = self.config.runs / job_id
            directory.mkdir(parents=True, mode=0o700, exist_ok=False)
            approved = deepcopy(snapshot["study"])
            approved.update(approval=dict(snapshot["audit"], decision="approved"), approved_at=now())
            # Persist only the reviewed projection, never the original dataset or findings.
            write_json(directory / "approved.json", approved)
            write_json(directory / "request.json", approved["request"])
            write_json(directory / "target.json", target)
            job = Job(job_id, owner, snapshot["scan_id"], directory, dict(
                job_id=job_id, status="queued", stage="queued", created_at=now(), events=[],
                candidates=[dict(compound_id=c["compound_id"], canonical_smiles=c["canonical_smiles"]) for c in approved["request"].get("compounds", [])],
                candidate_count=len(approved["request"].get("compounds", [])), target_id=target["target_id"],
                workflow=approved.get("workflow", "screen"), requested_count=approved["request"].get("count"),
                mode=approved["mode"], research_prompt=approved["research_prompt"],
                shortlist=None, discovery_sha256=None, report_available=False, error=None,
                assistant={"status": "pending" if approved["use_assistant"] else "off"}))
            self.jobs[job_id] = job
            job.update()
            self.pool.submit(self._run, job, approved)
            return job

    def _assistant_call(self, job, action, approved, report=None):
        if job.stop.is_set():
            raise ScreeningCancelled()
        try:
            result = getattr(self.assistant, action)(approved, report) if action == "explain" else self.assistant.plan(approved)
            with job.lock:
                state = dict(job.state["assistant"], status="complete", **{action: result})
            job.update(assistant=state)
            return result
        except Exception as error:
            # Interpretation is optional; scientific evidence remains available on failure.
            with job.lock:
                state = dict(job.state["assistant"], status="unavailable", error=str(error) if isinstance(error, AssistantError) else "assistant_request_failed")
            job.update(assistant=state)

    def continue_without_assistant(self, owner, job_id):
        job = self.owned(owner, job_id)
        with job.lock:
            if job.state.get("assistant_override") == "researcher_selected_fixed_protocol":
                return job
            if job.state["status"] != "awaiting_plan" or not job.state.get("can_continue"):
                raise WorkspaceError("continuation_not_available")
            if job.stop.is_set():
                raise WorkspaceError("continuation_not_available")
            approved = load(job.directory / "approved.json")
            job.update(status="queued", stage="queued", can_continue=False,
                       assistant_override="researcher_selected_fixed_protocol")
            self.pool.submit(self._run, job, approved, skip_assistant=True)
        return job

    def _run(self, job, approved, skip_assistant=False):
        try:
            job.update(status="running")
            if job.stop.is_set():
                raise ScreeningCancelled()
            if approved["use_assistant"] and not skip_assistant:
                job.progress({"stage": "planning"})
                plan = self._assistant_call(job, "plan", approved)
                if job.stop.is_set():
                    raise ScreeningCancelled()
                if plan is None or not plan["supported"]:
                    job.update(status="awaiting_plan", stage="planning_paused", can_continue=plan is None)
                    return
            args = argparse.Namespace(command="run", request=job.directory / "request.json",
                target=job.directory / "target.json", output_dir=job.directory / "science",
                model=self.config.model, model_python=self.config.model_python,
                cache_dir=self.config.cache if approved["mode"] == "cached" else None)
            generating = approved.get("workflow") == "generate_screen"
            if generating:
                args.resume = False
                args.cache_dir = self.config.cache.parent if approved["mode"] == "cached" else None
                offline = CachedOnlyClient() if approved["mode"] == "cached" else None
                status = self.design_runner(args, genmol_client=offline, boltz_client=offline,
                    progress=job.progress, cancelled=job.stop.is_set, quiet=True)
                wrapper = load(args.output_dir / "design-report.json")
                job.update(generation=wrapper.get("generation"), workflow_limitations=wrapper["limitations"])
                if not (args.output_dir / "combined.json").exists():
                    job.update(status="partial", stage="failed", error="generation_no_assessment", finished_at=now())
                    return
            else:
                status = self.runner(args, client=CachedOnlyClient() if approved["mode"] == "cached" else None,
                                     progress=job.progress, cancelled=job.stop.is_set, quiet=True)
            report = load(args.output_dir / "combined.json")
            validate_screening_report(report)
            # The report must still be based on the discovery artifact frozen before DILI.
            frozen = args.output_dir / "discovery.json"
            if not job.state["discovery_sha256"] or hashlib.sha256(frozen.read_bytes()).hexdigest() != job.state["discovery_sha256"]:
                raise WorkspaceError("frozen_discovery_changed")
            discovery = load(frozen)
            validate_discovery(load(args.output_dir / "request.json") if generating else approved["request"], discovery)
            if (report["target"] != discovery["target"] or
                    [r["discovery_result"] for r in report["results"]] != discovery["results"]):
                raise WorkspaceError("report_discovery_mismatch")
            if approved["use_assistant"] and not skip_assistant and not job.stop.is_set():
                job.progress({"stage": "explaining"})
                self._assistant_call(job, "explain", approved, report)
            job.update(status="complete" if status == 0 else "partial", stage="finished",
                       report_available=True, finished_at=now())
        except ScreeningCancelled:
            job.update(status="cancelled", stage="cancelled", finished_at=now())
        except Exception:
            job.update(status="failed", stage="failed", error="screening_failed", finished_at=now())

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job.stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
