"""Deterministic, evidence-linked candidate prioritization."""

from __future__ import annotations

from typing import Any


def _assessment_ref(stream: str, result: dict[str, Any]) -> str:
    return f"{stream}:{result['compound_id']}:assessment"


def _discovery_priority(
    discovery_result: dict[str, Any], policy: dict[str, Any]
) -> tuple[str, str | None]:
    metric_name = policy["discovery_priority_metric"]
    matches = [
        metric
        for metric in discovery_result["supplementary_metrics"]
        if metric["name"] == metric_name
    ]
    if len(matches) != 1 or not isinstance(matches[0]["value"], str):
        return "unavailable", None

    value = matches[0]["value"].strip().lower()
    if value in {item.lower() for item in policy["promising_values"]}:
        return "promising", matches[0]["source_ref"]
    if value in {item.lower() for item in policy["weak_values"]}:
        return "weak", matches[0]["source_ref"]
    return "unavailable", matches[0]["source_ref"]


def _toxicity_reliability(
    toxicity_result: dict[str, Any], policy: dict[str, Any]
) -> tuple[str, str]:
    settings = policy["toxicity_reliability"]
    applicability = toxicity_result["assessment"]["applicability"]
    expected_method = settings["applicability_method"]
    minimum = settings["credible_minimum"]

    if minimum is None:
        return (
            "unknown",
            "The applicability threshold is not configured or scientifically approved.",
        )
    if applicability["method"] != expected_method:
        return (
            "unknown",
            "The returned applicability method does not match the triage policy.",
        )
    value = applicability["value"]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unknown", "The applicability value is unavailable."
    if value >= minimum:
        return "credible", "The configured applicability criterion is met."
    return "outside_supported_space", "The configured applicability criterion is not met."


def _experiment(policy: dict[str, Any], name: str) -> dict[str, Any]:
    experiment = policy["experiments"][name]
    return {
        "question": experiment["question"],
        "assay": experiment["assay"],
        "readouts": list(experiment["readouts"]),
    }


def _base_priority(
    discovery_result: dict[str, Any],
    toxicity_result: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    return {
        "policy_version": policy["policy_version"],
        "policy_status": policy["status"],
        "status": "unavailable",
        "original_priority": "unavailable",
        "revised_priority": "assessment_incomplete",
        "recommendation": "Assessment incomplete; retry or review the unavailable inputs.",
        "toxicity_reliability": "unknown",
        "evidence_refs": [
            _assessment_ref("discovery", discovery_result),
            _assessment_ref("toxicity", toxicity_result),
        ],
        "limitations": [],
        "proposed_experiment": None,
    }


def prioritize_candidate(
    discovery_result: dict[str, Any],
    toxicity_result: dict[str, Any],
    comparison: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Apply the versioned triage policy to one validated candidate pair."""

    priority = _base_priority(discovery_result, toxicity_result, policy)
    original_priority, discovery_ref = _discovery_priority(discovery_result, policy)
    priority["original_priority"] = original_priority
    if discovery_ref is not None:
        priority["evidence_refs"].append(discovery_ref)

    incomplete = [
        f"{stream}={result['status']}"
        for stream, result in (
            ("discovery", discovery_result),
            ("toxicity", toxicity_result),
        )
        if result["status"] != "ok"
    ]
    if incomplete:
        priority["limitations"].append(
            "One or more required assessments did not complete: "
            + ", ".join(incomplete)
            + "."
        )
        return priority

    if original_priority == "unavailable":
        priority["recommendation"] = (
            "Discovery priority is unavailable; apply the agreed discovery "
            "criterion before revising candidate priority."
        )
        priority["limitations"].append(
            "The required discovery_priority supplementary metric is missing or invalid."
        )
        return priority

    human = toxicity_result["assessment"]
    call = human["call"]
    reliability, reliability_reason = _toxicity_reliability(toxicity_result, policy)
    priority["toxicity_reliability"] = reliability
    priority["limitations"].append(reliability_reason)

    if call == "positive" and reliability == "credible":
        priority["status"] = "available"
        priority["proposed_experiment"] = _experiment(
            policy, "targeted_liver_validation"
        )
        if original_priority == "promising":
            priority["revised_priority"] = "hold_for_safety_validation"
            priority["recommendation"] = (
                "Consider targeted human-relevant liver validation before advancement."
            )
        else:
            priority["revised_priority"] = "deprioritize"
            priority["recommendation"] = (
                "Deprioritize unless other evidence justifies further work."
            )
        return priority

    if call == "negative" and reliability == "credible":
        priority["status"] = "available"
        priority["revised_priority"] = (
            "continue_evaluation" if original_priority == "promising" else "low_priority"
        )
        priority["recommendation"] = (
            "Continue planned evaluation; lower predicted concern does not establish safety."
        )
        return priority

    priority["status"] = "available"
    priority["revised_priority"] = "safety_evidence_required"
    priority["recommendation"] = (
        "Gather additional safety evidence with an assay that can resolve the uncertainty."
    )
    priority["proposed_experiment"] = _experiment(
        policy, "resolve_safety_uncertainty"
    )
    if call == "unavailable":
        priority["limitations"].append("The human DILI call is unavailable.")
    if comparison["status"] == "unavailable":
        priority["limitations"].append(
            "The joint comparison is unavailable: " + comparison["reason"]
        )
    return priority
