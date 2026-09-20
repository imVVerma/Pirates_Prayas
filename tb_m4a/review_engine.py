"""Headless, SYNTHETIC-only TB verifier decision engine (M4a).

Consumes M0 case snapshots (M2 cases and M3 test attachments share this contract).
Provides an explicit-human-review action, never an automated diagnosis or risk score.

This module is NOT a secure authentication boundary: caller must supply a principal
resolved by trusted middleware. M1's existing HTTP endpoint remains unauthenticated
and can bypass this service until server-side authorization is added.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from contract import check_next, validate_or_raise
from validate_cases import stamp


class ReviewError(ValueError):
    """The requested reviewer action was not permitted or not consistent."""


@dataclass(frozen=True)
class Principal:
    """Resolved by trusted server/session code, NEVER by a submitted case payload."""
    actor_id: str
    role: str


@dataclass(frozen=True)
class Site:
    site_id: str
    purposes: frozenset[str]
    area: str
    estimated_travel_minutes: int
    capacity_available: bool
    reachable: bool


class CapacityRegistry:
    """In-memory synthetic availability snapshot, NOT a live NTEP site directory.

    Treat missing site / stale-unverified capacity as unavailable. No invented
    geographic 'nearest' result: compare only manually supplied travel estimates.
    """
    def __init__(self, sites):
        self.sites = {s.site_id: s for s in sites}
        if len(self.sites) != len(sites):
            raise ValueError('duplicate site id')

    def options(self, area, purpose):
        return sorted(
            [s for s in self.sites.values() if s.area == area and purpose in s.purposes
             and s.capacity_available and s.reachable],
            key=lambda s: (s.estimated_travel_minutes, s.site_id)
        )

    def require(self, site_id, area, purpose):
        match = [site for site in self.options(area, purpose) if site.site_id == site_id]
        if not match:
            raise ReviewError('selected synthetic site is not verified reachable/available for area and purpose')
        return match[0]


def _now(when):
    if when is None:
        return datetime.now(timezone.utc).isoformat()
    # M0 insists on aware, RFC3339-compatible timestamps.
    try:
        stamp(when)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReviewError('review time needs an offset-aware timestamp') from exc
    return when


def _require_permissions(case, principal, expected_revision):
    validate_or_raise(case)
    if not isinstance(principal, Principal) or principal.role not in ('verifier', 'clinician') or not principal.actor_id:
        raise ReviewError('only a trusted verifier/clinician principal may record screening review')
    if type(expected_revision) is not int or expected_revision != case['revision']:
        raise ReviewError('stale expected revision; reload case before making a decision')
    if not case['consent']['data_collection'] or not case['consent']['share_with_verifier']:
        raise ReviewError('review-sharing consent required')
    if case['case_status'] not in ('ready_for_review', 'pending_additional_test'):
        raise ReviewError('case is not in a reviewer decision state')


def review_case(case, *, principal, expected_revision, decision, notes,
                requested_tests=(), site_id=None, registry=None, when=None):
    """Return the *next* validated M0 snapshot, without side effects.

    All decisions and choices are supplied explicitly by the human reviewer.
    The registry verifies a *chosen* synthetic site rather than auto-deciding
    diagnostic eligibility. 'more_tests_needed' can be recorded without a site
    while mobile scheduling/capacity is pending.
    """
    _require_permissions(case, principal, expected_revision)
    if not isinstance(notes, str) or not notes.strip():
        raise ReviewError('human reviewer must supply a nonempty rationale')
    if not isinstance(requested_tests, (list, tuple)):
        raise ReviewError('requested_tests must be a list of explicit test types')
    tests = list(requested_tests)
    if len(set(tests)) != len(tests) or set(tests) - {'xray', 'esr'}:
        raise ReviewError('requested_tests may only contain unique xray/esr entries')
    at = _now(when)
    if stamp(at) < stamp(case['status_history'][-1]['at']):
        raise ReviewError('review cannot predate most recent clinical state transition')
    if case['review_history'] and stamp(at) < stamp(case['review_history'][-1]['decided_at']):
        raise ReviewError('review cannot predate last recorded human review')
    current = case['case_status']
    next_case = deepcopy(case)
    next_case['revision'] += 1

    if decision == 'more_tests_needed':
        if current != 'ready_for_review':
            raise ReviewError('already pending screening; wait for result or refer directly for diagnostics')
        if not tests:
            raise ReviewError('human must explicitly request at least one optional screening test')
        purpose = 'additional_screening'
        target = 'pending_additional_test'
    elif decision == 'intervention_required':
        if tests:
            raise ReviewError('diagnostic referral cannot carry optional-screening requests')
        if not site_id:
            raise ReviewError('M0 currently requires an actual selected diagnostic site; do not invent one')
        purpose = 'diagnostic_testing'
        target = 'routed_for_diagnostics'
    elif decision == 'not_required':
        if current != 'ready_for_review':
            raise ReviewError('pending additional screening cannot be closed by no-referral shortcut')
        if tests or site_id is not None:
            raise ReviewError('no-referral decision cannot also request a route/test')
        purpose = None
        target = 'closed'
    else:
        raise ReviewError('unknown human review decision')

    if site_id is not None:
        if registry is None:
            raise ReviewError('selected site requires a capacity registry')
        registry.require(site_id, case['patient']['demographics']['location'], purpose)
    elif purpose == 'diagnostic_testing':
        raise ReviewError('diagnostic site required by M0')

    next_case['review_history'].append({
        'review_id': str(uuid4()), 'reviewer_id': principal.actor_id,
        'reviewer_role': principal.role, 'decision': decision,
        'requested_tests': tests, 'notes': notes.strip(), 'decided_at': at,
    })
    if site_id is not None:
        next_case['routes'].append({
            'route_id': str(uuid4()), 'purpose': purpose,
            'site_id': site_id, 'status': 'planned', 'routed_at': at,
        })
    next_case['status_history'].append({
        'from': current, 'to': target, 'at': at,
        'actor_id': principal.actor_id, 'actor_role': principal.role,
    })
    next_case['case_status'] = target
    validate_or_raise(next_case)
    check_next(case, next_case)
    return next_case


def attach_pending_screening_route(case, *, principal, expected_revision,
                                   site_id, registry, when=None):
    """Append optional-screening route when a scheduled site becomes available.

    No forced clinical status transition or model result. M3 will own evidence
    attachment and return-to-review, not this independent module.
    """
    validate_or_raise(case)
    if not isinstance(principal, Principal) or principal.role not in ('verifier', 'clinician') or not principal.actor_id:
        raise ReviewError('route requires trusted verifier/clinician')
    if type(expected_revision) is not int or expected_revision != case['revision']:
        raise ReviewError('stale revision')
    if case['case_status'] != 'pending_additional_test' or not case['review_history']:
        raise ReviewError('no pending human screening request')
    if not case['review_history'][-1]['requested_tests']:
        raise ReviewError('no screening test was requested')
    registry.require(site_id, case['patient']['demographics']['location'], 'additional_screening')
    at = _now(when)
    if stamp(at) < stamp(case['status_history'][-1]['at']):
        raise ReviewError('route cannot predate review')
    updated = deepcopy(case)
    updated['revision'] += 1
    updated['routes'].append({'route_id':str(uuid4()),'purpose':'additional_screening',
                              'site_id':site_id,'status':'planned','routed_at':at})
    validate_or_raise(updated)
    check_next(case, updated)
    return updated
