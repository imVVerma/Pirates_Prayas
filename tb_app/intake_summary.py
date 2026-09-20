"""M8 intake summary pipeline.

Typed text and speech-transcribed text enter this module through the same
function.  The default implementation is deterministic and deliberately
non-diagnostic.  A future model provider can replace the summarizer behind the
same interface without changing the field-worker contract.
"""
from __future__ import annotations
import re
from typing import Any


def _state(value: Any, label: str) -> str:
    if value is True:
        return f"{label}: reported"
    if value is False:
        return f"{label}: not reported"
    return f"{label}: unknown"


def deterministic_summary(raw_text: str | None, structured: dict[str, Any]) -> dict[str, Any]:
    """Return a factual, rule-based summary. Never infer a symptom from prose."""
    cough = structured.get("cough_present")
    duration = structured.get("cough_duration_days")
    cough_line = _state(cough, "Cough")
    if cough is True:
        cough_line += f" ({duration} day(s))" if duration else " (duration unknown)"

    lines = [
        cough_line,
        _state(structured.get("fever"), "Fever"),
        _state(structured.get("night_sweats"), "Night sweats"),
        _state(structured.get("weight_loss"), "Weight loss"),
    ]
    narrative = (raw_text or "").strip()
    if narrative:
        lines.append(f"Worker-entered text (verbatim): {narrative}")
    return {
        "summary": "Structured intake summary: " + "; ".join(lines) + ".",
        "method": "deterministic_fallback",
        "diagnostic": False,
        "raw_text_preserved": bool(narrative),
    }


def summarize(raw_text: str | None, structured: dict[str, Any]) -> dict[str, Any]:
    """Single entry point for both typed and speech-transcribed intake text."""
    # M8 intentionally has no external model dependency. A future provider can
    # be inserted here after data-governance and evaluation gates are approved.
    return deterministic_summary(raw_text, structured)
