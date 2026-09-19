"""Scientifically gated comparison of conventional and human DILI assessments."""

from __future__ import annotations

from typing import Any


FORMULA_VERSION = "comparison_v1"


def _source_reference(stream: str, result: dict[str, Any]) -> dict[str, str]:
    return {
        "stream": stream,
        "compound_id": result["compound_id"],
        "structure_id": result["structure_id"],
        "endpoint_id": result["assessment"]["endpoint_id"],
    }


def _base_result(
    discovery_result: dict[str, Any], toxicity_result: dict[str, Any]
) -> dict[str, Any]:
    return {
        "comparison_mode": "unavailable",
        "status": "unavailable",
        "reason": "",
        "source_assessments": {
            "conventional": _source_reference("discovery", discovery_result),
            "human": _source_reference("toxicity", toxicity_result),
        },
        "formula_version": FORMULA_VERSION,
        "signed_disagreement": None,
        "absolute_disagreement": None,
        "call_disagreement": None,
        "hidden_liability_flag": None,
        "conservative_risk_score": None,
    }


def _same_assessment_target(
    conventional: dict[str, Any], human: dict[str, Any]
) -> bool:
    """Return whether two assessments have the same endpoint and context."""

    fields = (
        "endpoint_id",
        "positive_definition",
        "negative_definition",
        "context",
    )
    return all(conventional[field] == human[field] for field in fields)


def _is_assessed_probability(assessment: dict[str, Any]) -> bool:
    return (
        assessment["score_kind"] == "calibrated_probability"
        and assessment["calibration"]["status"] == "assessed"
        and isinstance(assessment["risk_score"], (int, float))
        and not isinstance(assessment["risk_score"], bool)
    )


def _has_call(assessment: dict[str, Any]) -> bool:
    return assessment["call"] in {"positive", "negative"}


def _numeric_ineligibility_reason(
    conventional: dict[str, Any],
    human: dict[str, Any],
    same_target: bool,
) -> str:
    reasons: list[str] = []
    if not same_target:
        reasons.append("the endpoint definitions or assessment contexts differ")
    if conventional["score_kind"] != "calibrated_probability" or human[
        "score_kind"
    ] != "calibrated_probability":
        reasons.append("both scores are not calibrated probabilities")
    if conventional["calibration"]["status"] != "assessed" or human[
        "calibration"
    ]["status"] != "assessed":
        reasons.append("calibration has not been assessed for both streams")
    if conventional["risk_score"] is None or human["risk_score"] is None:
        reasons.append("one or both risk scores are unavailable")
    return "; ".join(reasons) or "numeric comparison requirements were not met"


def compare_assessments(
    discovery_result: dict[str, Any], toxicity_result: dict[str, Any]
) -> dict[str, Any]:
    """Compare two validated per-compound results using the v1 formula policy."""

    comparison = _base_result(discovery_result, toxicity_result)
    unavailable_streams = [
        stream
        for stream, result in (
            ("discovery", discovery_result),
            ("toxicity", toxicity_result),
        )
        if result["status"] != "ok"
    ]
    if unavailable_streams:
        statuses = ", ".join(
            f"{stream}={result['status']}"
            for stream, result in (
                ("discovery", discovery_result),
                ("toxicity", toxicity_result),
            )
            if stream in unavailable_streams
        )
        comparison["reason"] = (
            "Comparison unavailable because one or more assessments did not "
            f"complete successfully: {statuses}."
        )
        return comparison

    conventional = discovery_result["assessment"]
    human = toxicity_result["assessment"]
    same_target = _same_assessment_target(conventional, human)
    numeric_eligible = (
        same_target
        and _is_assessed_probability(conventional)
        and _is_assessed_probability(human)
    )
    calls_available = _has_call(conventional) and _has_call(human)

    if numeric_eligible:
        signed = human["risk_score"] - conventional["risk_score"]
        comparison.update(
            {
                "comparison_mode": "same_endpoint_probability",
                "status": "available",
                "reason": (
                    "The endpoint definitions and contexts match, and both "
                    "scores are assessed calibrated probabilities."
                ),
                "signed_disagreement": signed,
                "absolute_disagreement": abs(signed),
                "conservative_risk_score": max(
                    human["risk_score"], conventional["risk_score"]
                ),
            }
        )
        if calls_available:
            comparison["call_disagreement"] = int(
                conventional["call"] != human["call"]
            )
            comparison["hidden_liability_flag"] = int(
                conventional["call"] == "negative"
                and human["call"] == "positive"
            )
        return comparison

    if calls_available:
        comparison.update(
            {
                "comparison_mode": (
                    "same_endpoint_calls" if same_target else "cross_endpoint_calls"
                ),
                "status": "available",
                "reason": (
                    "Call comparison is available, but numeric disagreement is "
                    "not eligible because "
                    + _numeric_ineligibility_reason(
                        conventional, human, same_target
                    )
                    + "."
                ),
                "call_disagreement": int(
                    conventional["call"] != human["call"]
                ),
                "hidden_liability_flag": int(
                    conventional["call"] == "negative"
                    and human["call"] == "positive"
                ),
            }
        )
        return comparison

    comparison["reason"] = (
        "Comparison unavailable because one or both endpoint-specific calls are "
        "unavailable and numeric comparison is ineligible because "
        + _numeric_ineligibility_reason(conventional, human, same_target)
        + "."
    )
    return comparison
