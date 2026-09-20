"""M3 revision-safe attachment of optional screening observations to M0 cases.

No UI, network, implicit clock, automatic diagnosis, or case-level medical rule.
The authoritative M0 validator and M1 cross-snapshot contract are reused.
"""
from __future__ import annotations
from copy import deepcopy
from provenance import EvidenceError, aware_time, require_text
from contract import validate_or_raise, check_next

_ALLOWED_ACTORS = frozenset({'pharmacist', 'lab', 'clinician', 'verifier'})


def _validate_block(name, block):
    if not isinstance(block, dict):
        raise EvidenceError(f'{name} must be the complete M0 test object')
    if name == 'xray':
        expected = ('available', 'image_ref', 'model_flag', 'model_confidence',
                    'heatmap_ref', 'model_id', 'captured_at')
        evidence_fields = ('image_ref', 'captured_at')
    else:
        expected = ('available', 'value', 'flag', 'reference_range_used', 'captured_at')
        evidence_fields = ('value', 'captured_at')
    if set(block) != set(expected):
        raise EvidenceError(f'{name} must have exactly M0 keys; missing={sorted(set(expected)-set(block))}; extra={sorted(set(block)-set(expected))}')
    if type(block['available']) is not bool:
        raise EvidenceError(f'{name}.available must be boolean')
    if block['available']:
        for field in evidence_fields:
            if block[field] is None:
                raise EvidenceError(f'{name}.{field} required when available')
        aware_time(block['captured_at'], f'{name}.captured_at')
        if name == 'xray':
            require_text(block['image_ref'], 'xray.image_ref')
            if block['model_flag'] is not None:
                require_text(block['model_id'], 'xray.model_id')
                if block['model_confidence'] is None:
                    raise EvidenceError('xray.model_confidence requires raw model score')
        elif block['flag'] is not None:
            require_text(block['reference_range_used'], 'esr.reference_range_used')
    elif any(block[k] is not None for k in expected if k != 'available'):
        raise EvidenceError(f'{name} cannot contain observations if available=false')


def _merge(name, old, candidate):
    if candidate == old:
        return old, False
    if not candidate['available']:
        if old['available']:
            raise EvidenceError(f'{name}: already recorded evidence cannot be removed')
        return old, False
    if not old['available']:
        return candidate, True
    # A chest radiograph captured but not yet processed can later acquire a
    # model result for the *same* immutable image and capture timestamp.
    if name == 'xray' and old['model_flag'] is None:
        if (old['image_ref'], old['captured_at']) != (candidate['image_ref'], candidate['captured_at']):
            raise EvidenceError('xray: a different image requires an explicit future multi-image schema')
        if candidate['model_flag'] is None or candidate['model_id'] is None:
            raise EvidenceError('xray: only enrichment with attributable inference is supported')
        return candidate, True
    raise EvidenceError(f'{name}: conflicting evidence cannot silently overwrite an existing result')


def attach_screening_tests(existing_case, xray=None, esr=None, *,
                           actor_id, actor_role, event_at=None):
    """Return a *validated* M0 next revision; return unchanged copy on retry.

    - Missing input means unchanged; `{available:false...}` does not clear data.
    - For pending cases, partial results keep case pending. Once EVERY screening
      test explicitly requested in the most recent review is available, perform
      pending_additional_test -> ready_for_review (requires explicit event_at).
    - Intake / pre-review states are not modified by this adapter.
    - Case summary remains the *timestamped intake brief*, not a live report:
      dashboards must read live xray/esr; never trust summary as latest evidence.
    """
    validate_or_raise(existing_case)
    require_text(actor_id, 'actor_id')
    if actor_role not in _ALLOWED_ACTORS:
        raise EvidenceError('screening attachment actor must be pharmacist/lab/verifier/clinician; authorization is enforced upstream')
    if xray is None and esr is None:
        raise EvidenceError('at least one screening block must be supplied')
    if existing_case['case_status'] not in ('ready_for_review', 'pending_additional_test'):
        raise EvidenceError('screening attachment is allowed only before referral/diagnosis and after intake submission')
    proposed = deepcopy(existing_case)
    changed = False
    for name, candidate in (('xray', xray), ('esr', esr)):
        if candidate is None:
            continue
        _validate_block(name, candidate)
        proposed[name], delta = _merge(name, proposed[name], candidate)
        changed |= delta
    if not changed:
        return proposed  # idempotent; do not create duplicate revisions

    if existing_case['case_status'] == 'pending_additional_test':
        latest = existing_case['review_history'][-1]
        missing = [name for name in latest['requested_tests'] if not proposed[name]['available']]
        if not missing:
            if event_at is None:
                raise EvidenceError('event_at required for pending -> ready; no invented timestamp')
            at = aware_time(event_at, 'event_at')
            last_state = aware_time(existing_case['status_history'][-1]['at'], 'last state timestamp')
            last_review = aware_time(latest['decided_at'], 'last review timestamp')
            if at < max(last_state, last_review):
                raise EvidenceError('event_at cannot precede clinical review/state change')
            for name in latest['requested_tests']:
                if at < aware_time(proposed[name]['captured_at'], f'{name}.captured_at'):
                    raise EvidenceError('event_at cannot precede requested test capture')
            if actor_role not in ('pharmacist', 'lab', 'verifier', 'clinician'):
                raise EvidenceError('actor cannot resubmit case')
            proposed['case_status'] = 'ready_for_review'
            proposed['status_history'].append({
                'from': 'pending_additional_test', 'to': 'ready_for_review',
                'at': event_at, 'actor_id': actor_id, 'actor_role': actor_role,
            })
        elif event_at is not None:
            raise EvidenceError('event_at denotes resubmission, but requested tests still unavailable')
    elif event_at is not None:
        raise EvidenceError('event_at is only for pending -> ready; ordinary evidence is timestamped at capture')
    proposed['revision'] += 1
    validate_or_raise(proposed)
    check_next(existing_case, proposed)
    # Only these fields may differ, even when caller inputs other mutable objects.
    allowed = {'revision', 'xray', 'esr', 'status_history', 'case_status'}
    if any(proposed[k] != existing_case[k] for k in existing_case if k not in allowed):
        raise EvidenceError('unexpected unrelated case mutation')
    return proposed
