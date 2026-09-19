"""Schema and cross-record validation for ToxOracle v2 envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
DEFAULT_CONFIGS_DIR = Path(__file__).resolve().parents[3] / "configs"


class ContractValidationError(ValueError):
    """Raised when an envelope violates the shared schema or identity policy."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages))


def _load_schema(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _json_path(error_path: Any) -> str:
    parts = [str(part) for part in error_path]
    return "$" if not parts else "$." + ".".join(parts)


def _validate_schema(
    document: dict[str, Any], schema_path: Path, document_name: str
) -> None:
    validator = Draft202012Validator(_load_schema(schema_path))
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise ContractValidationError(
            [
                f"{document_name} {_json_path(error.path)}: {error.message}"
                for error in errors
            ]
        )


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_request(
    request: dict[str, Any], contracts_dir: Path = DEFAULT_CONTRACTS_DIR
) -> None:
    """Validate a request schema and enforce unique candidate identifiers."""

    _validate_schema(request, contracts_dir / "request.schema.json", "request")
    duplicate_ids = _duplicates(
        [compound["compound_id"] for compound in request["compounds"]]
    )
    if duplicate_ids:
        raise ContractValidationError(
            [f"request contains duplicate compound_id values: {duplicate_ids}"]
        )


def validate_response(
    response: dict[str, Any], contracts_dir: Path = DEFAULT_CONTRACTS_DIR
) -> None:
    """Validate a response schema and enforce unique candidate records."""

    _validate_schema(response, contracts_dir / "response.schema.json", "response")
    duplicate_ids = _duplicates(
        [result["compound_id"] for result in response["results"]]
    )
    if duplicate_ids:
        raise ContractValidationError(
            [f"response contains duplicate compound_id values: {duplicate_ids}"]
        )


def validate_response_against_request(
    request: dict[str, Any],
    response: dict[str, Any],
    *,
    expected_stream: str | None = None,
    contracts_dir: Path = DEFAULT_CONTRACTS_DIR,
) -> None:
    """Validate response coverage and shared molecular identity against a request."""

    validate_request(request, contracts_dir)
    validate_response(response, contracts_dir)

    messages: list[str] = []
    if response["request_id"] != request["request_id"]:
        messages.append(
            "response request_id does not match the submitted request: "
            f"{response['request_id']!r} != {request['request_id']!r}"
        )
    if expected_stream is not None and response["stream"] != expected_stream:
        messages.append(
            f"expected stream {expected_stream!r}, received {response['stream']!r}"
        )

    requested = {
        compound["compound_id"]: compound for compound in request["compounds"]
    }
    returned = {result["compound_id"]: result for result in response["results"]}
    missing_ids = sorted(set(requested) - set(returned))
    extra_ids = sorted(set(returned) - set(requested))
    if missing_ids:
        messages.append(f"response is missing compound_id values: {missing_ids}")
    if extra_ids:
        messages.append(f"response contains unexpected compound_id values: {extra_ids}")

    for compound_id in sorted(set(requested) & set(returned)):
        compound = requested[compound_id]
        result = returned[compound_id]
        evidence = result["structural_evidence"]
        comparisons = (
            ("structure_id", result["structure_id"], compound["structure_id"]),
            (
                "canonical_smiles",
                evidence["canonical_smiles"],
                compound["canonical_smiles"],
            ),
            (
                "atom_mapped_smiles",
                evidence["atom_mapped_smiles"],
                compound["atom_mapped_smiles"],
            ),
            (
                "standardization_version",
                evidence["standardization_version"],
                compound["standardization_version"],
            ),
        )
        for field, actual, expected in comparisons:
            if actual != expected:
                messages.append(
                    f"{compound_id} {field} mismatch: {actual!r} != {expected!r}"
                )

    if messages:
        raise ContractValidationError(messages)


def validate_policy(
    policy: dict[str, Any], configs_dir: Path = DEFAULT_CONFIGS_DIR
) -> None:
    """Validate a triage policy before it can affect candidate priorities."""

    _validate_schema(policy, configs_dir / "triage.schema.json", "triage policy")
    promising = {value.lower() for value in policy["promising_values"]}
    weak = {value.lower() for value in policy["weak_values"]}
    overlap = sorted(promising & weak)
    if overlap:
        raise ContractValidationError(
            [f"triage policy priority values overlap: {overlap}"]
        )


def validate_combined_report(
    combined: dict[str, Any], contracts_dir: Path = DEFAULT_CONTRACTS_DIR
) -> None:
    """Validate the generated combined report envelope."""

    _validate_schema(
        combined, contracts_dir / "combined-report.schema.json", "combined report"
    )
