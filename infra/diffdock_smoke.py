"""Reproduce NVIDIA's public 8G43/ZU6 example; this is not a project target.

Run from the repository root with NVIDIA_API_KEY in the environment:
    python3 infra/diffdock_smoke.py --output-directory artifacts/runs/nvidia-smoke
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "discovery" / "src"))

from toxoracle_discovery.diffdock import (  # noqa: E402
    DiffDockNIMClient, DiffDockRequest, DockingEvidence, MODEL_REFERENCE,
)


EXAMPLE_REFERENCE = "https://build.nvidia.com/mit/diffdock/deploy"
SOURCES = {
    "8G43.pdb": "https://files.rcsb.org/download/8G43.pdb",
    "ZU6_ideal.sdf": "https://files.rcsb.org/ligands/download/ZU6_ideal.sdf",
}


def save(directory: Path, name: str, content: str) -> dict:
    path = directory / name
    data = content.encode("utf-8")
    path.write_bytes(data)
    return {"uri": str(path.resolve()), "checksum": "sha256:" + hashlib.sha256(data).hexdigest()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    directory = args.output_directory
    # Preserve earlier runs, including failed attempts.
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "purpose": "public NVIDIA connectivity example; not a frozen therapeutic target or toxicity assessment",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "example_reference": EXAMPLE_REFERENCE,
        "model_reference": MODEL_REFERENCE,
        "served_model_version": None,
        "served_model_version_status": "not_reported",
        "inputs": {},
        "status": "not_run",
    }
    exit_code = 0
    try:
        client = DiffDockNIMClient.from_environment()
        manifest["service_endpoint"] = client.endpoint
        inputs = {}
        for name, url in SOURCES.items():
            with urlopen(url, timeout=60) as response:
                inputs[name] = response.read().decode("utf-8")
            manifest["inputs"][name] = dict(save(directory, name, inputs[name]), source_ref=url)
        # This selection exactly follows the vendor example. It is not a full
        # protein preparation protocol and makes no cofactor/protonation claim.
        protein = "\n".join(line for line in inputs["8G43.pdb"].splitlines() if line.startswith("ATOM")) + "\n"
        manifest["inputs"]["prepared_protein"] = save(directory, "8G43_atoms.pdb", protein)
        manifest["preparation"] = "Keep ATOM records as in NVIDIA's public example; no other preparation"
        request = DiffDockRequest(protein=protein, ligand=inputs["ZU6_ideal.sdf"], ligand_file_type="sdf", num_poses=1)
        manifest["request_artifact"] = save(directory, "request.json", json.dumps(request.to_payload(), indent=2) + "\n")
        response = client.dock(request)
        evidence = DockingEvidence.from_response("nvidia_example_ZU6", response, directory)
        manifest["evidence_artifact"] = save(directory, "evidence.json", json.dumps(evidence.to_dict(), indent=2, allow_nan=False) + "\n")
        manifest["status"] = evidence.status
        # An empty/unusable response is not a successful smoke test.
        if not evidence.supplementary_metrics or not evidence.structure_artifacts:
            raise ValueError("Service did not return both pose confidence and pose artifacts")
        manifest["response_fields"] = sorted(response)
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = {"type": type(error).__name__, "message": str(error)}
        exit_code = 1
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    save(directory, "run.json", json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": manifest["status"], "manifest": str(directory / "run.json"), "error": manifest.get("error")}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
