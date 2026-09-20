"""M1 contract boundary: reuse, do not fork, the M0 combined validator."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

M0_DIR = Path(__file__).resolve().parent.parent / 'tb_m0'
if not (M0_DIR / 'validate_cases.py').exists():
    raise RuntimeError('M0 missing: unpack tb_m0 and tb_m1 into the same parent directory')
sys.path.insert(0, str(M0_DIR))
from validate_cases import validate  # noqa: E402

SCHEMA = json.loads((M0_DIR / 'case-schema.json').read_text(encoding='utf-8'))


def canonical(case: dict) -> str:
    return json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(payload: str) -> str:
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def validate_or_raise(case: dict) -> None:
    if not isinstance(case, dict):
        raise ValueError('case must be an object')
    problems = validate(case, SCHEMA)
    if problems:
        raise ValueError('; '.join(problems))


def check_next(previous: dict, proposed: dict) -> None:
    """Cross-snapshot invariants not expressible by M0 snapshot validation.

    Stable identity, exact +1 revision and append-only provenance. Non-history
    objects (e.g. a pending assay result or planned route) can be updated by
    future authorized workflow modules; M1 never decides medical outcomes.
    """
    if proposed['case_id'] != previous['case_id']:
        raise ValueError('case_id cannot change')
    if proposed['revision'] != previous['revision'] + 1:
        raise ValueError('revision must increase by exactly 1')
    for field in ('schema_version', 'created_at', 'patient', 'consent'):
        if proposed[field] != previous[field]:
            raise ValueError(f'field {field} changed; explicit future migration required')
    for field in ('status_history', 'review_history', 'followups'):
        old = previous[field]
        if proposed[field][:len(old)] != old:
            raise ValueError(f'{field} must be append-only')
    # A known test/route may be enriched with a result/status, but it cannot disappear.
    for field, key in (('diagnostic_tests', 'test_id'), ('routes', 'route_id')):
        before = {item[key] for item in previous[field]}
        after = {item[key] for item in proposed[field]}
        if not before.issubset(after):
            raise ValueError(f'{field} cannot delete previously recorded IDs')
    for field, evidence_fields in (
        ('xray', ('image_ref', 'captured_at')),
        ('esr', ('value', 'captured_at')),
    ):
        old = previous[field]
        new = proposed[field]
        if old['available'] and not new['available']:
            raise ValueError(f'{field} cannot lose already-attached evidence')
        if old['available'] and any(old[k] != new[k] for k in evidence_fields):
            raise ValueError(f'{field} captured evidence cannot silently change')
