"""M5b ASHA follow-up and continuity event engine.

Backend-only synthetic prototype. It deliberately uses the existing M0
``followups`` and ``medicine_pickup_log`` arrays as append-only event history.
No UI, diagnosis, prescription, or automatic clinical decision-making.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from contract import check_next, validate_or_raise
from validate_cases import stamp


class FollowUpError(ValueError):
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
        raise FollowUpError("event time needs an offset-aware timestamp") from exc
    return when


def _base(case, principal, expected_revision):
    validate_or_raise(case)
    if not getattr(principal, "actor_id", None) or not getattr(principal, "role", None):
        raise FollowUpError("trusted authorized principal required")
    if type(expected_revision) is not int or expected_revision != case["revision"]:
        raise FollowUpError("stale expected revision; reload case before changing the case")
    if not case["consent"]["data_collection"] or not case["consent"]["share_with_verifier"]:
        raise FollowUpError("required case-sharing consent is missing")
    if case["asha_assignment"]["asha_id"] is None:
        raise FollowUpError("an active ASHA assignment is required")


def _assigned_asha(case, principal):
    if principal.role != "asha" or principal.actor_id != case["asha_assignment"]["asha_id"]:
        raise FollowUpError("only the assigned ASHA may record follow-up events")


def _phase_allows_kind(case, kind):
    phase = case["asha_assignment"]["support_phase"]
    if kind == "navigation" and phase not in {"pre_diagnosis_navigation", "treatment_support"}:
        raise FollowUpError("navigation follow-up requires an ASHA assignment")
    if kind == "treatment" and phase != "treatment_support":
        raise FollowUpError("treatment follow-up requires treatment-support ASHA assignment")


def _append_revision(case, updated):
    validate_or_raise(updated)
    check_next(case, updated)
    return updated


def schedule_followup(case, *, principal, expected_revision, kind,
                      scheduled_at, summary="Follow-up scheduled"):
    """Record a planned follow-up as an immutable history entry.

    M0's frozen follow-up shape has no separate event-status field, so a
    scheduled event is represented by a normal follow-up entry whose summary
    explicitly starts with ``Scheduled:``. Completion is a later appended
    follow-up entry, never an in-place edit.
    """
    _base(case, principal, expected_revision)
    if principal.role not in {"clinician", "verifier", "asha"}:
        raise FollowUpError("role is not allowed to schedule follow-up")
    if kind not in {"navigation", "treatment"}:
        raise FollowUpError("follow-up kind must be navigation or treatment")
    _phase_allows_kind(case, kind)
    at = _time(scheduled_at)
    if stamp(at) < stamp(case["asha_assignment"]["assigned_at"]):
        raise FollowUpError("follow-up cannot be scheduled before ASHA assignment")
    if not isinstance(summary, str) or not summary.strip():
        raise FollowUpError("summary is required")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["followups"].append({
        "date": at,
        "kind": kind,
        "source": "text",
        "raw_transcript": None,
        "summary": f"Scheduled: {summary.strip()}",
        "trend": None,
    })
    return _append_revision(case, updated)


def record_followup(case, *, principal, expected_revision, kind,
                    summary, trend=None, when=None, raw_transcript=None,
                    source="text"):
    """Append an actual ASHA follow-up interaction to immutable history."""
    _base(case, principal, expected_revision)
    _assigned_asha(case, principal)
    if kind not in {"navigation", "treatment"}:
        raise FollowUpError("follow-up kind must be navigation or treatment")
    _phase_allows_kind(case, kind)
    if source not in {"text", "voice"}:
        raise FollowUpError("source must be text or voice")
    if not isinstance(summary, str) or not summary.strip():
        raise FollowUpError("summary is required")
    if trend not in {None, "improving", "no_change", "concerning"}:
        raise FollowUpError("invalid follow-up trend")
    if source == "voice" and not case["consent"]["audio_recording"]:
        raise FollowUpError("voice follow-up needs explicit recording consent")
    if raw_transcript is not None and not isinstance(raw_transcript, str):
        raise FollowUpError("raw_transcript must be text or null")
    at = _time(when)
    if stamp(at) < stamp(case["asha_assignment"]["assigned_at"]):
        raise FollowUpError("follow-up cannot predate ASHA assignment")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["followups"].append({
        "date": at,
        "kind": kind,
        "source": source,
        "raw_transcript": raw_transcript,
        "summary": summary.strip(),
        "trend": trend,
    })
    return _append_revision(case, updated)


def schedule_medicine_pickup(case, *, principal, expected_revision,
                              scheduled_date):
    """Append a planned medicine pickup. Treatment support is required."""
    _base(case, principal, expected_revision)
    if case["asha_assignment"]["support_phase"] != "treatment_support":
        raise FollowUpError("medicine pickup requires treatment-support ASHA assignment")
    if principal.role not in {"clinician", "asha"}:
        raise FollowUpError("only clinician or assigned ASHA may schedule medicine pickup")
    try:
        datetime.strptime(scheduled_date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise FollowUpError("scheduled_date must be YYYY-MM-DD") from exc
    if any(e["scheduled_date"] == scheduled_date and e["status"] == "scheduled"
           for e in case["asha_assignment"]["medicine_pickup_log"]):
        raise FollowUpError("medicine pickup is already scheduled for this date")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["asha_assignment"]["medicine_pickup_log"].append({
        "scheduled_date": scheduled_date,
        "status": "scheduled",
        "logged_at": None,
    })
    return _append_revision(case, updated)


def record_medicine_pickup(case, *, principal, expected_revision,
                           scheduled_date, status, when=None,
                           reschedule_date=None):
    """Append a pickup outcome without mutating prior pickup history.

    If ``status=missed`` and ``reschedule_date`` is supplied, the missed event
    and the next scheduled pickup are appended atomically in the same revision.
    This is the M5b missed-pickup continuity path.
    """
    _base(case, principal, expected_revision)
    _assigned_asha(case, principal)
    if case["asha_assignment"]["support_phase"] != "treatment_support":
        raise FollowUpError("medicine pickup requires treatment-support ASHA assignment")
    if status not in {"picked_up", "missed"}:
        raise FollowUpError("pickup outcome must be picked_up or missed")
    try:
        datetime.strptime(scheduled_date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise FollowUpError("scheduled_date must be YYYY-MM-DD") from exc
    entries = case["asha_assignment"]["medicine_pickup_log"]
    scheduled = [e for e in entries if e["scheduled_date"] == scheduled_date and e["status"] == "scheduled"]
    if not scheduled:
        raise FollowUpError("no open scheduled pickup exists for this date")
    if any(e["scheduled_date"] == scheduled_date and e["status"] in {"picked_up", "missed"} for e in entries):
        raise FollowUpError("pickup outcome for this date is already recorded")
    at = _time(when)
    if stamp(at) < stamp(case["asha_assignment"]["assigned_at"]):
        raise FollowUpError("pickup outcome cannot predate ASHA assignment")

    if reschedule_date is not None:
        if status != "missed":
            raise FollowUpError("reschedule_date is only valid for a missed pickup")
        try:
            datetime.strptime(reschedule_date, "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise FollowUpError("reschedule_date must be YYYY-MM-DD") from exc
        if reschedule_date <= scheduled_date:
            raise FollowUpError("rescheduled pickup must be later than missed pickup date")
        if any(e["scheduled_date"] == reschedule_date and e["status"] == "scheduled" for e in entries):
            raise FollowUpError("rescheduled pickup date is already scheduled")

    updated = deepcopy(case)
    updated["revision"] += 1
    updated["asha_assignment"]["medicine_pickup_log"].append({
        "scheduled_date": scheduled_date,
        "status": status,
        "logged_at": at,
    })
    if reschedule_date is not None:
        updated["asha_assignment"]["medicine_pickup_log"].append({
            "scheduled_date": reschedule_date,
            "status": "scheduled",
            "logged_at": None,
        })
    return _append_revision(case, updated)
