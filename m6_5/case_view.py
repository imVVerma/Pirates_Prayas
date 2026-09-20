"""Thin UI-facing read model for the rural-TB prototype.

This module is a projection only. It never changes a case and never infers a
clinical decision from screening evidence. The canonical M0 snapshot remains
the source of truth.
"""
from __future__ import annotations

from copy import deepcopy


def _latest_pickup(case):
    entries = case["asha_assignment"]["medicine_pickup_log"]
    return entries[-1] if entries else None


def _next_action(case):
    a = case["asha_assignment"]
    if not a["asha_id"]:
        return None
    if a["support_phase"] == "pre_diagnosis_navigation":
        return {"type": "navigation_followup", "label": "Referral / test navigation"}
    entries = a["medicine_pickup_log"]
    completed_dates = {e["scheduled_date"] for e in entries
                       if e["status"] in ("missed", "picked_up")}
    scheduled = [e for e in entries if e["status"] == "scheduled"
                 and e["scheduled_date"] not in completed_dates]
    if scheduled:
        e = sorted(scheduled, key=lambda x: x["scheduled_date"])[0]
        return {"type": "medicine_pickup", "label": "Medicine pickup", "due": e["scheduled_date"]}
    return {"type": "treatment_followup", "label": "Treatment follow-up"}


def _alerts(case):
    alerts = []
    pickups = case["asha_assignment"]["medicine_pickup_log"]
    if any(e["status"] == "missed" for e in pickups):
        alerts.append({"type": "missed_pickup", "severity": "attention", "label": "Previous medicine pickup missed"})
    if case["case_status"] == "pending_additional_test":
        alerts.append({"type": "pending_tests", "severity": "action", "label": "Additional screening tests pending"})
    if case["case_status"] == "routed_for_diagnostics":
        alerts.append({"type": "diagnostic_pending", "severity": "action", "label": "Diagnostic result pending"})
    return alerts


def build_case_view(case):
    """Project a validated canonical case into a stable UI read model."""
    # Import lazily so this file remains a pure projection when copied into a UI service.
    from contract import validate_or_raise
    validate_or_raise(case)

    diagnosis = case["diagnosis"]
    assignment = case["asha_assignment"]
    if assignment["support_phase"] == "treatment_support" and diagnosis and diagnosis["treatment_started_at"]:
        current_stage = "treatment_follow_up"
    elif diagnosis:
        current_stage = "diagnosed"
    elif case["case_status"] == "diagnostic_result_available":
        current_stage = "diagnostic_review"
    elif case["case_status"] == "routed_for_diagnostics":
        current_stage = "awaiting_diagnostic_result"
    elif case["case_status"] == "pending_additional_test":
        current_stage = "awaiting_screening"
    elif case["case_status"] == "ready_for_review":
        current_stage = "needs_review"
    elif case["case_status"] == "closed":
        current_stage = "closed"
    else:
        current_stage = "intake"

    latest_pickup = _latest_pickup(case)
    return {
        "case_id": case["case_id"],
        "revision": case["revision"],
        "current_stage": current_stage,
        "case_status": case["case_status"],
        "patient": {
            "patient_ref": case["patient"]["patient_ref"],
            "age": case["patient"]["demographics"]["age"],
            "sex": case["patient"]["demographics"]["sex"],
            "location": case["patient"]["demographics"]["location"],
        },
        "screening": {
            "xray": {
                "available": case["xray"]["available"],
                "flag": case["xray"]["model_flag"],
                "confidence": case["xray"]["model_confidence"],
                "model_id": case["xray"]["model_id"],
                "captured_at": case["xray"]["captured_at"],
            },
            "esr": {
                "available": case["esr"]["available"],
                "value": case["esr"]["value"],
                "flag": case["esr"]["flag"],
                "reference_range_used": case["esr"]["reference_range_used"],
                "captured_at": case["esr"]["captured_at"],
            },
        },
        "diagnostics": {
            "tests": deepcopy(case["diagnostic_tests"]),
            "routes": deepcopy(case["routes"]),
        },
        "diagnosis": None if diagnosis is None else {
            "status": "clinician_confirmed",
            "classification": diagnosis["classification"],
            "diagnosed_at": diagnosis["diagnosed_at"],
        },
        "treatment": None if diagnosis is None else {
            "plan_confirmed": diagnosis["treatment_plan_confirmed"],
            "started_at": diagnosis["treatment_started_at"],
        },
        "asha": {
            "assigned": assignment["asha_id"] is not None,
            "asha_id": assignment["asha_id"],
            "support_phase": assignment["support_phase"],
            "assigned_at": assignment["assigned_at"],
            "next_action": _next_action(case),
            "latest_pickup": deepcopy(latest_pickup),
        },
        "alerts": _alerts(case),
        "history_count": len(case["status_history"]) + len(case["review_history"]) + len(case["followups"]),
    }
