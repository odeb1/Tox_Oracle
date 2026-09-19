"""Normalize discovery-only evidence without turning it into toxicity evidence."""

from __future__ import annotations

from typing import Any

from .validation import ContractValidationError, validate_request


EVIDENCE_STREAM = "discovery_evidence"
NORMALIZED_STREAM = "normalized_discovery_evidence"
ALLOWED_STATUSES = {"ok", "invalid_input", "unsupported", "failed", "not_run"}
STRUCTURE_ORIGINS = {"experimental", "predicted", "generated"}


def _error(message: str) -> ContractValidationError:
    return ContractValidationError([message])


def _list_field(source: dict[str, Any], field: str, compound_id: str) -> list[Any]:
    value = source.get(field, [])
    if not isinstance(value, list):
        raise _error(f"{compound_id} {field} must be an array")
    return value


def _normalize_metric(metric: Any, compound_id: str) -> dict[str, Any]:
    required = ("name", "value", "unit", "direction", "meaning", "source_ref")
    if not isinstance(metric, dict) or any(field not in metric for field in required):
        raise _error(f"{compound_id} discovery metric is missing required fields")
    if not isinstance(metric["name"], str) or not metric["name"]:
        raise _error(f"{compound_id} discovery metric name must be non-empty")
    if not isinstance(metric["meaning"], str) or not metric["meaning"]:
        raise _error(f"{compound_id} discovery metric meaning must be non-empty")
    if not isinstance(metric["source_ref"], str) or not metric["source_ref"]:
        raise _error(f"{compound_id} discovery metric source_ref must be non-empty")
    return {field: metric[field] for field in required}


def _normalize_artifact(
    artifact: Any, compound_id: str, structure_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    required = ("artifact_id", "format", "uri", "checksum")
    if not isinstance(artifact, dict) or any(
        not isinstance(artifact.get(field), str) or not artifact[field]
        for field in required
    ):
        raise _error(f"{compound_id} structure artifact is missing required fields")

    origin = artifact.get("origin")
    mapping_ref = artifact.get("atom_mapping_ref")
    warning = None
    is_shared_graph = (
        artifact["format"].lower() == "json"
        and artifact["artifact_id"].endswith("_atom_mapping")
    )
    if origin is None and mapping_ref is None and is_shared_graph:
        origin = "generated"
        mapping_ref = structure_id
        warning = (
            f"Artifact {artifact['artifact_id']} was normalized as an input-derived "
            "atom-mapping graph."
        )

    if origin not in STRUCTURE_ORIGINS:
        return None, (
            f"Artifact {artifact['artifact_id']} was excluded because its structural "
            "origin is missing or unsupported."
        )
    if not isinstance(mapping_ref, str) or not mapping_ref:
        return None, (
            f"Artifact {artifact['artifact_id']} was excluded because atom mapping "
            "has not been declared."
        )

    normalized = {
        "artifact_id": artifact["artifact_id"],
        "format": artifact["format"],
        "uri": artifact["uri"],
        "checksum": artifact["checksum"],
        "origin": origin,
        "atom_mapping_ref": mapping_ref,
    }
    for optional in ("model_id", "target_id", "conformer_id"):
        if optional in artifact:
            normalized[optional] = artifact[optional]
    return normalized, warning


def _normalize_interaction(interaction: Any, compound_id: str) -> dict[str, Any]:
    if not isinstance(interaction, dict):
        raise _error(f"{compound_id} interaction must be an object")
    chain_id = interaction.get("chain_id", interaction.get("chain"))
    residue_id = interaction.get("residue_id")
    if residue_id is None:
        name = interaction.get("residue_name")
        number = interaction.get("residue_number")
        insertion = interaction.get("insertion_code", "")
        if name is not None and number is not None:
            residue_id = f"{name}:{number}{insertion}"

    normalized = {
        "atom_map_ids": interaction.get("atom_map_ids"),
        "target_id": interaction.get("target_id"),
        "chain_id": chain_id,
        "residue_id": residue_id,
        "interaction_type": interaction.get("interaction_type"),
        "distance_angstrom": interaction.get("distance_angstrom"),
        "artifact_ref": interaction.get("artifact_ref"),
    }
    missing = [
        field
        for field in (
            "atom_map_ids",
            "target_id",
            "chain_id",
            "residue_id",
            "interaction_type",
            "artifact_ref",
        )
        if normalized[field] in (None, "", [])
    ]
    if missing:
        raise _error(
            f"{compound_id} interaction is missing required fields: {missing}"
        )
    return normalized


def _normalize_error(error: Any, compound_id: str, status: str) -> dict[str, Any] | None:
    if error is None:
        if status in {"invalid_input", "unsupported", "failed"}:
            raise _error(f"{compound_id} status {status} requires an error")
        return None
    if not isinstance(error, dict):
        raise _error(f"{compound_id} error must be an object or null")
    code = error.get("code", error.get("type"))
    message = error.get("message")
    if not isinstance(code, str) or not code or not isinstance(message, str) or not message:
        raise _error(f"{compound_id} error requires a code/type and message")
    normalized = {"code": code, "message": message}
    if "details" in error:
        normalized["details"] = error["details"]
    return normalized


def normalize_discovery_evidence(
    request: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    """Normalize DiffDock-style evidence for later merging with a comparator.

    The returned envelope intentionally has no ``assessment`` field and is not a
    valid final discovery response. A conventional toxicity comparator must be
    merged separately before the shared v2 response can be produced.
    """

    validate_request(request)
    if evidence.get("schema_version") != "2.0":
        raise _error("discovery evidence schema_version must be 2.0")
    if evidence.get("request_id") != request["request_id"]:
        raise _error("discovery evidence request_id does not match the request")
    if evidence.get("stream") != EVIDENCE_STREAM:
        raise _error(f"discovery evidence stream must be {EVIDENCE_STREAM!r}")
    source_results = evidence.get("results")
    if not isinstance(source_results, list):
        raise _error("discovery evidence results must be an array")
    if any(not isinstance(result, dict) for result in source_results):
        raise _error("every discovery evidence result must be an object")

    source_ids = [result.get("compound_id") for result in source_results]
    if any(not isinstance(compound_id, str) or not compound_id for compound_id in source_ids):
        raise _error("every discovery evidence result requires a non-empty compound_id")
    if len(source_ids) != len(set(source_ids)):
        raise _error("discovery evidence contains duplicate compound_id values")
    requested = {
        compound["compound_id"]: compound for compound in request["compounds"]
    }
    returned = {result.get("compound_id"): result for result in source_results}
    missing = sorted(set(requested) - set(returned))
    extra = sorted(set(returned) - set(requested), key=str)
    if missing or extra:
        raise ContractValidationError(
            [
                message
                for values, message in (
                    (missing, f"discovery evidence is missing compound IDs: {missing}"),
                    (extra, f"discovery evidence has unexpected compound IDs: {extra}"),
                )
                if values
            ]
        )

    normalized_results = []
    for compound in request["compounds"]:
        compound_id = compound["compound_id"]
        source = returned[compound_id]
        status = source.get("status")
        if status not in ALLOWED_STATUSES:
            raise _error(f"{compound_id} has unsupported discovery evidence status")
        source_structure_id = source.get("structure_id")
        if source_structure_id is not None and source_structure_id != compound["structure_id"]:
            raise _error(f"{compound_id} discovery evidence structure_id mismatch")

        metrics = [
            _normalize_metric(metric, compound_id)
            for metric in _list_field(source, "supplementary_metrics", compound_id)
        ]
        source_structural = source.get("structural_evidence", {})
        if not isinstance(source_structural, dict):
            raise _error(f"{compound_id} structural_evidence must be an object")
        artifacts = []
        source_warnings = _list_field(source, "warnings", compound_id)
        warnings = [
            warning
            for warning in source_warnings
            if isinstance(warning, str) and warning
        ]
        structural_artifacts = source_structural.get("structure_artifacts", [])
        interactions_source = source_structural.get("interactions", [])
        if not isinstance(structural_artifacts, list):
            raise _error(f"{compound_id} structure_artifacts must be an array")
        if not isinstance(interactions_source, list):
            raise _error(f"{compound_id} interactions must be an array")
        for artifact in structural_artifacts:
            normalized, warning = _normalize_artifact(
                artifact, compound_id, compound["structure_id"]
            )
            if normalized is not None:
                artifacts.append(normalized)
            if warning is not None:
                warnings.append(warning)
        interactions = [
            _normalize_interaction(interaction, compound_id)
            for interaction in interactions_source
        ]
        source_provenance = source.get("provenance", {})
        if not isinstance(source_provenance, dict):
            raise _error(f"{compound_id} provenance must be an object")
        provenance = dict(source_provenance)
        provenance["evidence_role"] = "therapeutic_discovery_only"
        provenance["source_stream"] = EVIDENCE_STREAM

        normalized_results.append(
            {
                "compound_id": compound_id,
                "structure_id": compound["structure_id"],
                "status": status,
                "supplementary_metrics": metrics,
                "structural_evidence": {
                    "canonical_smiles": compound["canonical_smiles"],
                    "atom_mapped_smiles": compound["atom_mapped_smiles"],
                    "standardization_version": compound[
                        "standardization_version"
                    ],
                    "attribution_status": "unavailable",
                    "attribution_method": None,
                    "attribution_target": None,
                    "attribution_scale": None,
                    "attribution_reference": None,
                    "fragments": [],
                    "structure_artifacts": artifacts,
                    "interactions": interactions,
                    "mechanism_hypotheses": [],
                },
                "service_artifacts": _list_field(
                    source, "service_artifacts", compound_id
                ),
                "provenance": provenance,
                "target": source.get("target", evidence.get("target")),
                "warnings": warnings,
                "error": _normalize_error(source.get("error"), compound_id, status),
            }
        )

    return {
        "schema_version": "2.0",
        "request_id": request["request_id"],
        "stream": NORMALIZED_STREAM,
        "target": evidence.get("target"),
        "results": normalized_results,
        "warnings": [
            "Normalized therapeutic discovery evidence only; this is not the final "
            "conventional-toxicity assessment envelope."
        ],
    }
