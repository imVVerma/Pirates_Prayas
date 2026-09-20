"""M5a ASHA assignment and care-phase state machine.

Backend-only synthetic prototype. No UI and no automatic medical decisions.
The engine enforces the M0 boundary:
- pre-diagnosis ASHA work is navigation only and requires an authorized
  verifier referral/request context;
- treatment-support assignment requires a clinician-recorded diagnosis,
  confirmed care plan, and explicit treatment initiation;
- assignment itself never changes clinical case_status.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from contract import check_next, validate_or_raise
from validate_cases import stamp


class ASHAError(ValueError):
    pass


class Principal:
    def __init__(self, actor_id: str, role: str):
        self.actor_id = actor_id
        self.role = role


def _time(when):
    if when is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        stamp(when)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ASHAError("event time needs an offset-aware timestamp") from exc
    return when


def _base(case, principal, expected_revision, roles):
    validate_or_raise(case)
    if not hasattr(principal, "role") or principal.role not in roles or not getattr(principal, "actor_id", None):
        raise ASHAError("trusted authorized principal required")
    if type(expected_revision) is not int or expected_revision != case["revision"]:
        raise ASHAError("stale expected revision; reload case before changing the case")
    if not case["consent"]["data_collection"] or not case["consent"]["share_with_verifier"]:
        raise ASHAError("required case-sharing consent is missing")


def _last_review(case):
    return case["review_history"][-1] if case["review_history"] else None


def assign_pre_diagnosis_navigation(case, *, principal, expected_revision,
                                    asha_id, when=None):
    """Assign ASHA navigation after an explicit verifier referral/request.

    This phase is strictly for testing/referral logistics. It cannot create
    treatment support, diagnosis, medicine pickup tracking, or a case-status
    transition.
    """
    _base(case, principal, expected_revision, {"verifier", "clinician"})
    if case["asha_assignment"]["asha_id"] is not None:
        raise ASHAError("an ASHA assignment already exists")
    if not isinstance(asha_id, str) or not asha_id.strip():
        raise ASHAError("asha_id is required")
    if case["case_status"] not in {"pending_additional_test", "routed_for_diagnostics"}:
        raise ASHAError("pre-diagnosis navigation requires a pending test request or diagnostic referral")
    review = _last_review(case)
    if review is None:
        raise ASHAError("ASHA navigation requires a recorded human review")
    if case["case_status"] == "pending_additional_test":
        if review["decision"] != "more_tests_needed":
            raise ASHAError("pending navigation requires an explicit additional-test request")
    elif review["decision"] != "intervention_required":
        raise ASHAError("diagnostic navigation requires an explicit human diagnostic referral")

    at = _time(when)
    if stamp(at) < stamp(case["status_history"][-1]["at"]):
        raise ASHAError("assignment cannot predate the latest case transition")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["asha_assignment"] = {
        "asha_id": asha_id.strip(),
        "assigned_at": at,
        "support_phase": "pre_diagnosis_navigation",
        "medicine_pickup_log": [],
    }
    validate_or_raise(updated)
    check_next(case, updated)
    return updated


def mark_treatment_started(case, *, principal, expected_revision, when=None):
    """Record explicit treatment initiation after a clinician care plan.

    This is not a prescription engine. It records only the clinician-authorized
    initiation event needed before treatment-support assignment becomes legal.
    """
    _base(case, principal, expected_revision, {"clinician"})
    if case["case_status"] != "diagnosed" or case["diagnosis"] is None:
        raise ASHAError("treatment initiation requires a diagnosed case")
    diagnosis = case["diagnosis"]
    if not diagnosis["treatment_plan_confirmed"]:
        raise ASHAError("confirmed treatment plan required before treatment initiation")
    if diagnosis["treatment_started_at"] is not None:
        raise ASHAError("treatment initiation is already recorded")
    at = _time(when)
    if stamp(at) < stamp(diagnosis["diagnosed_at"]):
        raise ASHAError("treatment initiation cannot predate diagnosis")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["diagnosis"]["treatment_started_at"] = at
    validate_or_raise(updated)
    check_next(case, updated)
    return updated


def confirm_treatment_plan(case, *, principal, expected_revision, when=None):
    """Record explicit clinician confirmation of the treatment plan.

    This is a revision-safe prerequisite for treatment initiation. It does not
    prescribe, start treatment, assign an ASHA, or change case_status.
    """
    _base(case, principal, expected_revision, {"clinician"})
    if case["case_status"] != "diagnosed" or case["diagnosis"] is None:
        raise ASHAError("treatment-plan confirmation requires a diagnosed case")
    diagnosis = case["diagnosis"]
    if diagnosis["treatment_plan_confirmed"]:
        raise ASHAError("treatment plan is already confirmed")
    if diagnosis["treatment_started_at"] is not None:
        raise ASHAError("treatment plan cannot be confirmed after treatment has started")
    at = _time(when)
    if stamp(at) < stamp(diagnosis["diagnosed_at"]):
        raise ASHAError("treatment-plan confirmation cannot predate diagnosis")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["diagnosis"]["treatment_plan_confirmed"] = True
    updated["diagnosis"]["full_course_treatment_decided"] = True
    validate_or_raise(updated)
    check_next(case, updated)
    return updated

def assign_treatment_support(case, *, principal, expected_revision,
                             asha_id, when=None):
    """Assign ASHA treatment support only after actual treatment initiation."""
    _base(case, principal, expected_revision, {"clinician"})
    if case["case_status"] != "diagnosed" or case["diagnosis"] is None:
        raise ASHAError("treatment support requires a diagnosed case")
    diagnosis = case["diagnosis"]
    if not diagnosis["treatment_plan_confirmed"]:
        raise ASHAError("confirmed treatment plan required")
    if diagnosis["treatment_started_at"] is None:
        raise ASHAError("actual treatment initiation must be recorded before treatment support")
    if case["asha_assignment"]["asha_id"] is not None:
        raise ASHAError("an ASHA assignment already exists")
    if not isinstance(asha_id, str) or not asha_id.strip():
        raise ASHAError("asha_id is required")
    at = _time(when)
    if stamp(at) < stamp(diagnosis["treatment_started_at"]):
        raise ASHAError("assignment cannot predate treatment initiation")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["asha_assignment"] = {
        "asha_id": asha_id.strip(),
        "assigned_at": at,
        "support_phase": "treatment_support",
        "medicine_pickup_log": [],
    }
    validate_or_raise(updated)
    check_next(case, updated)
    return updated
