"""M4b diagnostic workflow core for the synthetic rural-TB prototype.

Headless only. No UI, no automated diagnosis, no treatment decisions.
M4a creates the human referral; M4b records diagnostic orders/results and
an explicit clinician diagnosis decision while preserving M1 revision rules.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from contract import check_next, validate_or_raise
from validate_cases import stamp
from review_engine import CapacityRegistry


class DiagnosticError(ValueError):
    pass


@dataclass(frozen=True)
class Principal:
    actor_id: str
    role: str


def _time(when):
    if when is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        stamp(when)
    except (ValueError, TypeError, AttributeError) as exc:
        raise DiagnosticError("event time needs an offset-aware timestamp") from exc
    return when


def _base_checks(case, principal, expected_revision, allowed_roles):
    validate_or_raise(case)
    if not isinstance(principal, Principal) or principal.role not in allowed_roles or not principal.actor_id:
        raise DiagnosticError("trusted authorized principal required")
    if type(expected_revision) is not int or expected_revision != case["revision"]:
        raise DiagnosticError("stale expected revision; reload case before changing the case")
    if not case["consent"]["data_collection"] or not case["consent"]["share_with_verifier"]:
        raise DiagnosticError("required case-sharing consent is missing")


def _last_route(case, purpose="diagnostic_testing"):
    routes = [r for r in case["routes"] if r["purpose"] == purpose and r["status"] != "cancelled"]
    return routes[-1] if routes else None


def order_diagnostic_test(case, *, principal, expected_revision, test_type,
                          lab_id, specimen_ref=None, collected_at=None, when=None):
    """Record a diagnostic test request on an already human-routed case.

    This does not create a result or diagnosis. Lab identity/site must match
    the latest active diagnostic route selected by the verifier.
    """
    _base_checks(case, principal, expected_revision, {"verifier", "clinician"})
    if case["case_status"] != "routed_for_diagnostics":
        raise DiagnosticError("diagnostic test can only be ordered from routed_for_diagnostics")
    allowed = {"xpert_mtb_rif", "xpert_ultra", "truenat", "culture",
               "smear_microscopy", "other_who_recommended_rapid_test"}
    if test_type not in allowed:
        raise DiagnosticError("unsupported diagnostic test type")
    if not isinstance(lab_id, str) or not lab_id.strip():
        raise DiagnosticError("lab_id is required")
    route = _last_route(case)
    if route is None or route["site_id"] != lab_id or route["status"] not in {"planned", "completed"}:
        raise DiagnosticError("lab must match an active diagnostic route")
    if any(t["test_type"] == test_type and t["result"] == "pending" for t in case["diagnostic_tests"]):
        raise DiagnosticError("same diagnostic test already has a pending order")
    at = _time(when)
    if stamp(at) < stamp(case["status_history"][-1]["at"]):
        raise DiagnosticError("test order cannot predate the latest case transition")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["diagnostic_tests"].append({
        "test_id": str(uuid4()),
        "test_type": test_type,
        "result": "pending",
        "lab_id": lab_id,
        "specimen_ref": specimen_ref,
        "collected_at": collected_at,
        "result_at": None,
    })
    validate_or_raise(updated)
    check_next(case, updated)
    return updated


def record_diagnostic_result(case, *, principal, expected_revision, test_id,
                             result, specimen_ref=None, collected_at=None,
                             when=None):
    """Attach an immutable diagnostic result supplied by an authorized lab."""
    _base_checks(case, principal, expected_revision, {"lab"})
    if result not in {"positive", "negative", "indeterminate"}:
        raise DiagnosticError("result must be positive, negative, or indeterminate")
    matches = [t for t in case["diagnostic_tests"] if t["test_id"] == test_id]
    if len(matches) != 1:
        raise DiagnosticError("diagnostic test not found")
    existing = matches[0]
    if existing["result"] != "pending":
        raise DiagnosticError("diagnostic result already recorded and cannot be overwritten")
    if case["case_status"] != "routed_for_diagnostics":
        raise DiagnosticError("case must be routed for diagnostics")
    if specimen_ref is not None and not isinstance(specimen_ref, str):
        raise DiagnosticError("specimen_ref must be a string or omitted")
    at = _time(when)
    if stamp(at) < stamp(case["status_history"][-1]["at"]):
        raise DiagnosticError("result cannot predate the latest case transition")

    updated = deepcopy(case)
    updated["revision"] += 1
    target = next(t for t in updated["diagnostic_tests"] if t["test_id"] == test_id)
    target["result"] = result
    if specimen_ref is not None:
        target["specimen_ref"] = specimen_ref
    if collected_at is not None:
        stamp(collected_at)
        target["collected_at"] = collected_at
    target["result_at"] = at
    for route in updated["routes"]:
        if route["purpose"] == "diagnostic_testing" and route["status"] == "planned":
            route["status"] = "completed"
            break
    updated["case_status"] = "diagnostic_result_available"
    updated["status_history"].append({
        "from": "routed_for_diagnostics",
        "to": "diagnostic_result_available",
        "at": at,
        "actor_id": principal.actor_id,
        "actor_role": principal.role,
    })
    validate_or_raise(updated)
    check_next(case, updated)
    return updated


def record_clinician_diagnosis(case, *, principal, expected_revision,
                               classification, supporting_test_ids=(),
                               clinical_rationale=None, full_course_treatment_decided=False,
                               treatment_plan_confirmed=False, when=None):
    """Record an explicit clinician diagnosis after diagnostic review.

    Bacteriological confirmation requires a positive supporting diagnostic test.
    Clinical diagnosis requires a non-empty clinician rationale. This function
    does not decide treatment or create ASHA treatment support.
    """
    _base_checks(case, principal, expected_revision, {"clinician"})
    if case["case_status"] != "diagnostic_result_available":
        raise DiagnosticError("clinician diagnosis requires diagnostic_result_available")
    if case["diagnosis"] is not None:
        raise DiagnosticError("diagnosis already recorded")
    if classification not in {"bacteriologically_confirmed", "clinically_diagnosed"}:
        raise DiagnosticError("unsupported diagnosis classification")
    ids = list(supporting_test_ids)
    if len(ids) != len(set(ids)):
        raise DiagnosticError("supporting_test_ids must be unique")
    tests = {t["test_id"]: t for t in case["diagnostic_tests"]}
    if any(tid not in tests for tid in ids):
        raise DiagnosticError("supporting test not found")
    if any(tests[tid]["result"] == "pending" for tid in ids):
        raise DiagnosticError("supporting tests must have final results")
    if classification == "bacteriologically_confirmed":
        if not any(tests[tid]["result"] == "positive" for tid in ids):
            raise DiagnosticError("bacteriologically_confirmed requires a positive supporting test")
        rationale = None
    else:
        if not isinstance(clinical_rationale, str) or not clinical_rationale.strip():
            raise DiagnosticError("clinical diagnosis requires a nonempty rationale")
        rationale = clinical_rationale.strip()
        if not full_course_treatment_decided or not treatment_plan_confirmed:
            raise DiagnosticError("clinical diagnosis requires explicit treatment decision and confirmed care plan")
    at = _time(when)
    if stamp(at) < stamp(case["status_history"][-1]["at"]):
        raise DiagnosticError("diagnosis cannot predate the available result")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["diagnosis"] = {
        "classification": classification,
        "clinician_id": principal.actor_id,
        "diagnosed_at": at,
        "supporting_test_ids": ids,
        "clinical_rationale": rationale,
        "full_course_treatment_decided": bool(full_course_treatment_decided),
        "treatment_plan_confirmed": bool(treatment_plan_confirmed),
        "treatment_started_at": None,
    }
    updated["case_status"] = "diagnosed"
    updated["status_history"].append({
        "from": "diagnostic_result_available",
        "to": "diagnosed",
        "at": at,
        "actor_id": principal.actor_id,
        "actor_role": principal.role,
    })
    validate_or_raise(updated)
    check_next(case, updated)
    return updated
