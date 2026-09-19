"""Small client for the public NVIDIA NIM DiffDock endpoint.

The adapter deliberately separates transport from record construction.  It makes
the live service optional in tests and prevents pose confidence from being
misrepresented as affinity, efficacy, or a toxicity score.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "https://health.api.nvidia.com/v1/biology/mit/diffdock"
MODEL_REFERENCE = "https://docs.api.nvidia.com/nim/reference/mit-diffdock-infer"
SUPPORTED_LIGAND_TYPES = {"smiles", "sdf", "mol2"}


class DiffDockError(RuntimeError):
    """A request could not be submitted to, or understood from, DiffDock."""

    def __init__(self, message: str, kind: str = "diffdock_request_failed") -> None:
        super().__init__(message)
        self.kind = kind


Transport = Callable[[str, Mapping[str, str], Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class DiffDockRequest:
    """A documented request to NVIDIA's DiffDock NIM endpoint."""

    protein: str
    ligand: str
    ligand_file_type: str = "smiles"
    num_poses: int = 10
    time_divisions: int = 20
    steps: int = 18
    save_trajectory: bool = False
    skip_gen_conformer: bool = False
    is_staged: bool = False

    def __post_init__(self) -> None:
        if not self.protein.strip():
            raise ValueError("protein PDB content must not be empty")
        if not self.ligand.strip():
            raise ValueError("ligand must not be empty")
        if self.ligand_file_type not in SUPPORTED_LIGAND_TYPES:
            raise ValueError(
                "ligand_file_type must be one of " + ", ".join(sorted(SUPPORTED_LIGAND_TYPES))
            )
        if not 1 <= self.num_poses <= 100:
            raise ValueError("num_poses must be between 1 and 100")
        if not 3 <= self.time_divisions <= 20:
            raise ValueError("time_divisions must be between 3 and 20")
        if not 1 <= self.steps <= 18:
            raise ValueError("steps must be between 1 and 18")

    def to_payload(self) -> Dict[str, Any]:
        return {
            "protein": self.protein,
            "ligand": self.ligand,
            "ligand_file_type": self.ligand_file_type,
            "num_poses": self.num_poses,
            "time_divisions": self.time_divisions,
            "steps": self.steps,
            "save_trajectory": self.save_trajectory,
            "skip_gen_conformer": self.skip_gen_conformer,
            "is_staged": self.is_staged,
        }


class DiffDockNIMClient:
    """DiffDock NIM client with an injectable transport for offline checks."""

    def __init__(
        self,
        api_key: str,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: int = 120,
        transport: Optional[Transport] = None,
    ) -> None:
        if not api_key:
            raise ValueError("an NVIDIA API key is required for live DiffDock calls")
        self._api_key = api_key
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self._transport = transport or self._urllib_transport
        self.last_response_metadata: Dict[str, Any] = {}

    @classmethod
    def from_environment(cls, environment_variable: str = "NVIDIA_API_KEY") -> "DiffDockNIMClient":
        api_key = os.environ.get(environment_variable, "")
        if not api_key:
            raise DiffDockError(
                "Missing {}. Set it outside the repository before a live request.".format(
                    environment_variable
                )
            )
        return cls(api_key)

    def dock(self, request: DiffDockRequest) -> Mapping[str, Any]:
        self.last_response_metadata = {}
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer {}".format(self._api_key),
            "Content-Type": "application/json",
        }
        return self._transport(self.endpoint, headers, request.to_payload())

    def _urllib_transport(
        self, endpoint: str, headers: Mapping[str, str], payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        encoded = json.dumps(payload).encode("utf-8")
        request = Request(endpoint, data=encoded, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310: configured NIM URL
                # Retain only non-secret response metadata for run provenance.
                self.last_response_metadata = {
                    "http_status": response.status,
                    "request_id": response.headers.get("nvcf-reqid"),
                    "service_date": response.headers.get("Date"),
                }
                body = response.read().decode("utf-8")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            kind = "invalid_input" if error.code in (400, 422) else "diffdock_request_failed"
            raise DiffDockError(
                "DiffDock returned HTTP {}: {}".format(error.code, detail), kind=kind
            ) from error
        except URLError as error:
            raise DiffDockError("DiffDock request failed: {}".format(error.reason)) from error

        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as error:
            raise DiffDockError("DiffDock returned non-JSON content") from error
        if not isinstance(decoded, dict):
            raise DiffDockError("DiffDock returned a JSON value other than an object")
        return decoded


def _finite_numbers(value: Any) -> List[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    numbers: List[float] = []
    for item in value:
        if isinstance(item, bool):
            continue
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            numbers.append(number)
    return numbers


def _write_text_artifact(
    output_directory: Path, artifact_id: str, suffix: str, value: str
) -> Dict[str, str]:
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / (artifact_id + suffix)
    path.write_text(value, encoding="utf-8")
    checksum = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return {
        "artifact_id": artifact_id,
        "format": suffix.lstrip("."),
        "uri": str(path),
        "checksum": "sha256:" + checksum,
        "origin": "predicted",
        "atom_mapping_ref": "unverified_vendor_output",
    }


def _write_json_artifact(output_directory: Path, artifact_id: str, value: Mapping[str, Any]) -> Dict[str, str]:
    output_directory.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path = output_directory / (artifact_id + ".json")
    path.write_text(content, encoding="utf-8")
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "artifact_id": artifact_id,
        "format": "json",
        "uri": str(path),
        "checksum": "sha256:" + checksum,
        "origin": "vendor_response",
    }


@dataclass
class DockingEvidence:
    """The discovery-only evidence contributed by a single docking invocation."""

    compound_id: str
    status: str
    supplementary_metrics: List[Dict[str, Any]]
    structure_artifacts: List[Dict[str, str]]
    service_artifacts: List[Dict[str, str]]
    warnings: List[str]
    error: Optional[Dict[str, str]] = None

    @classmethod
    def from_response(
        cls,
        compound_id: str,
        response: Mapping[str, Any],
        artifact_directory: Optional[Path] = None,
    ) -> "DockingEvidence":
        warnings = [
            "DiffDock pose confidence describes pose reliability; it is not binding affinity, "
            "therapeutic efficacy, or a toxicity score."
        ]
        confidence_field = "pose_confidence" if "pose_confidence" in response else "position_confidence"
        confidence = _finite_numbers(response.get(confidence_field))
        docked_ligand = response.get("docked_ligand")
        if docked_ligand is None and "ligand_positions" in response:
            # The hosted service also returns one SDF string per pose. Each
            # request here contains one ligand, so nested batch output must not
            # be flattened or silently associated with the wrong confidences.
            poses = response["ligand_positions"]
            if not isinstance(poses, list) or not poses or not all(
                isinstance(pose, str) and pose.strip() for pose in poses
            ):
                raise DiffDockError("Expected a non-empty list of ligand pose SDF strings")
            raw_confidence = response.get(confidence_field)
            if (
                not isinstance(raw_confidence, list)
                or len(poses) != len(raw_confidence)
                or len(confidence) != len(poses)
            ):
                raise DiffDockError("Pose count differs from finite confidence count")
            docked_ligand = "".join(
                pose.rstrip() + ("\n" if pose.rstrip().endswith("$$$$") else "\n$$$$\n")
                for pose in poses
            )
        metrics: List[Dict[str, Any]] = []
        if confidence:
            metrics.extend(
                [
                    {
                        "name": "diffdock_best_pose_confidence",
                        "value": max(confidence),
                        "unit": "unitless",
                        "direction": "higher_is_more_confident",
                        "meaning": "Highest confidence among returned DiffDock poses",
                        "source_ref": MODEL_REFERENCE,
                    },
                    {
                        "name": "diffdock_returned_pose_count",
                        "value": len(confidence),
                        "unit": "count",
                        "direction": "not_applicable",
                        "meaning": "Number of finite pose-confidence values returned by DiffDock",
                        "source_ref": MODEL_REFERENCE,
                    },
                ]
            )
        else:
            warnings.append("No finite pose-confidence values were returned by DiffDock.")

        artifacts: List[Dict[str, str]] = []
        service_artifacts: List[Dict[str, str]] = []
        if artifact_directory is not None:
            service_artifacts.append(
                _write_json_artifact(
                    artifact_directory, compound_id + "_diffdock_response", response
                )
            )
            if isinstance(docked_ligand, str) and docked_ligand.strip():
                artifacts.append(
                    _write_text_artifact(
                        artifact_directory,
                        compound_id + "_docked_ligand",
                        ".sdf",
                        docked_ligand,
                    )
                )

            visualization = response.get("visualizations_files", response.get("visualization_files"))
            if isinstance(visualization, str) and visualization.strip():
                artifacts.append(
                    _write_text_artifact(
                        artifact_directory,
                        compound_id + "_visualization",
                        ".pdb",
                        visualization,
                    )
                )

        if artifacts:
            warnings.append(
                "Vendor pose artifacts are retained, but their atom-map preservation has not yet "
                "been verified against the shared input molecule."
            )

        return cls(
            compound_id=compound_id,
            status="ok",
            supplementary_metrics=metrics,
            structure_artifacts=artifacts,
            service_artifacts=service_artifacts,
            warnings=warnings,
        )

    @classmethod
    def failed(
        cls, compound_id: str, message: str, status: str = "failed", error_type: str = "diffdock_request_failed"
    ) -> "DockingEvidence":
        if status == "invalid_input":
            warning = "No discovery conclusion can be made for invalid input."
        elif status == "unsupported":
            warning = "No discovery conclusion can be made for unsupported input."
        else:
            warning = "No discovery conclusion can be made because the DiffDock request failed."
        return cls(
            compound_id=compound_id,
            status=status,
            supplementary_metrics=[],
            structure_artifacts=[],
            service_artifacts=[],
            warnings=[warning],
            error={"type": error_type, "message": message},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compound_id": self.compound_id,
            "status": self.status,
            "supplementary_metrics": self.supplementary_metrics,
            "structural_evidence": {
                "structure_artifacts": self.structure_artifacts,
                "interactions": [],
            },
            "service_artifacts": self.service_artifacts,
            "provenance": {
                "method_id": "nvidia_nim_diffdock",
                "model_reference": MODEL_REFERENCE,
            },
            "warnings": self.warnings,
            "error": self.error,
        }
