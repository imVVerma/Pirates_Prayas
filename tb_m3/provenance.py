"""Fail-closed source and time validation. No synthetic/implicit timestamps."""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite


class EvidenceError(ValueError):
    """Screening evidence missing, malformed or contradictory."""


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f'{field} must be a nonempty source-provided string')
    return value.strip()


def aware_time(value, field):
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f'{field} must be a source-provided RFC3339 timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('timezone missing')
    except ValueError as exc:
        raise EvidenceError(f'{field} must have a real date/time with explicit offset') from exc
    return parsed.astimezone(timezone.utc)


def number(value, field, *, minimum=0, maximum=None):
    if type(value) not in (int, float) or not isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise EvidenceError(f'{field} must be a finite numeric reading between {minimum} and {maximum if maximum is not None else "infinity"}')
    return float(value)
