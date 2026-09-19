"""Identity-preserving join for discovery and toxicity responses."""

from __future__ import annotations

from typing import Any

from .comparison import compare_assessments
from .prioritization import prioritize_candidate
from .validation import validate_response_against_request


def combine_responses(
    request: dict[str, Any],
    discovery_response: dict[str, Any],
    toxicity_response: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Validate and combine one result from each stream for every candidate."""

    validate_response_against_request(
        request, discovery_response, expected_stream="discovery"
    )
    validate_response_against_request(
        request, toxicity_response, expected_stream="toxicity"
    )

    discovery_by_id = {
        result["compound_id"]: result for result in discovery_response["results"]
    }
    toxicity_by_id = {
        result["compound_id"]: result for result in toxicity_response["results"]
    }

    results: list[dict[str, Any]] = []
    for compound in request["compounds"]:
        compound_id = compound["compound_id"]
        discovery_result = discovery_by_id[compound_id]
        toxicity_result = toxicity_by_id[compound_id]
        comparison = compare_assessments(discovery_result, toxicity_result)
        results.append(
            {
                "compound_id": compound_id,
                "structure_id": compound["structure_id"],
                "canonical_smiles": compound["canonical_smiles"],
                "atom_mapped_smiles": compound["atom_mapped_smiles"],
                "standardization_version": compound["standardization_version"],
                "identity_status": "matched",
                "discovery_result": discovery_result,
                "toxicity_result": toxicity_result,
                "comparison": comparison,
                "priority": prioritize_candidate(
                    discovery_result,
                    toxicity_result,
                    comparison,
                    policy,
                ),
            }
        )

    return {
        "schema_version": "2.0",
        "request_id": request["request_id"],
        "policy_version": policy["policy_version"],
        "results": results,
    }
