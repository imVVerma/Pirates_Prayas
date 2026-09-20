"""
esr_adapter.py — M3: literature-sourced ESR threshold lookup -> the "esr"
block of case-schema.json (M0). Not a trained model; a lookup rule, per
the original spec.

=======================================================================
AUDIT FINDINGS (full detail in ../LIMITATIONS.md)
=======================================================================
Two concrete bugs in the old esr_rule.py, both of which M0's own
invalid-fixtures/03-wrong-esr-field.json exists specifically to catch:

  1. Field name mismatch. The old `to_schema_block()` emitted
     "value_mm_hr"; case-schema.json's real field is "esr.value"
     (case-schema.json's `esr` object is `additionalProperties: false`,
     so the wrong key fails schema validation outright).
  2. Extra key. The old block also included a "citation" key. The schema
     has exactly 5 keys: available, value, flag, reference_range_used,
     captured_at. Citation text now lives in AUDIT_NOTE below and in
     LIMITATIONS.md, not in the synced case JSON.

Clinical-appropriateness review (explicitly requested by M0's
CLINICAL-WORKFLOW-AND-DECISIONS.md: "The older esr_rule.py threshold is
not approved by M0; M3 must review its clinical appropriateness."):

  - The age/sex-adjusted Westergren normal ranges (Men <50: <=15,
    Men >=50: <=20, Women <50: <=20, Women >=50: <=30 mm/hr) are standard,
    uncontroversial clinical reference values. Retained unchanged.
  - The old module's docstring/citation described the >=100 mm/hr tier as
    a "TB adjunct signal specifically." That overstates what its own
    citation supports: Levay & Viljoen 2005 is a single South African
    cohort correlational study, and a separate cited study
    (Al-Marri & Kirkpatrick 2000) found ~33% of confirmed childhood TB
    cases had a completely NORMAL ESR at diagnosis. The schema's
    three-tier enum (normal/elevated/markedly_elevated) is frozen by M0
    and is kept, but the language attached to it below no longer frames
    >=100 mm/hr as a TB-specific finding -- only as a very high
    nonspecific reading warranting clinical attention.
  - Per CLINICAL-WORKFLOW-AND-DECISIONS.md: ESR must NEVER be used as TB
    confirmation, rule-out, or a required gate for molecular (NAAT)
    referral. This module has no coupling whatsoever to case_status,
    routing, or referral logic -- it only fills a descriptive field --
    and callers must keep it that way.
=======================================================================
"""

from __future__ import annotations

from typing import Literal, Optional

ESRFlag = Literal["normal", "elevated", "markedly_elevated"]

MARKEDLY_ELEVATED_THRESHOLD = 100.0  # mm/hr

AUDIT_NOTE = (
    "Age/sex Westergren normal ranges are standard clinical reference "
    "values. The >=100 mm/hr 'markedly_elevated' tier reflects a single "
    "correlational cohort study (Levay & Viljoen, S Afr Med J 2005) "
    "and is a nonspecific-inflammation flag, not a TB-specific finding: "
    "a pediatric observational series found normal ESR in some confirmed TB cases (Al-Marri & Kirkpatrick, "
    "Int J Tuberc Lung Dis 2000). ESR is never used here to confirm, "
    "rule out, or gate referral for TB."
)


def _normal_upper_limit(age: int, sex: str) -> float:
    """Age/sex-adjusted normal ESR upper limit (Westergren), in mm/hr."""
    sex = sex.strip().upper()
    if sex not in ("M", "F"):
        raise ValueError(f"sex must be 'M' or 'F', got {sex!r}")
    if sex == "M":
        return 20.0 if age >= 50 else 15.0
    return 30.0 if age >= 50 else 20.0


def _reference_range_description(age: Optional[int], sex: Optional[str]) -> str:
    """Short free-text description for the schema's `reference_range_used`
    field -- deliberately does not claim a TB-diagnostic cutoff, matching
    M0's own fixture language ('synthetic lab-reported reference, not a
    TB diagnostic cutoff')."""
    if age is not None and sex is not None:
        upper = _normal_upper_limit(age, sex)
        sex_word = "male" if sex.strip().upper() == "M" else "female"
        return (
            f"Age/sex Westergren normal upper limit for {sex_word}, age {age}: "
            f"<= {upper:.0f} mm/hr (nonspecific inflammatory marker, not a "
            f"TB-specific test). >=100 mm/hr recorded as 'markedly_elevated' "
            f"-- a very high nonspecific reading, not a TB diagnostic threshold."
        )
    return (
        "Generic adult Westergren normal upper limit (age/sex unknown): "
        "<= 20 mm/hr (nonspecific; reduced confidence without age/sex). "
        ">=100 mm/hr recorded as 'markedly_elevated', not a TB diagnostic "
        "threshold."
    )


def _flag_for(value: float, age: Optional[int], sex: Optional[str]) -> ESRFlag:
    if value >= MARKEDLY_ELEVATED_THRESHOLD:
        return "markedly_elevated"
    upper = _normal_upper_limit(age, sex) if (age is not None and sex is not None) else 20.0
    return "elevated" if value > upper else "normal"


def build_esr_block(
    *,
    available: bool,
    value: Optional[float] = None,
    age: Optional[int] = None,
    sex: Optional[str] = None,
    captured_at: Optional[str] = None,
) -> dict:
    """Builds the case-schema.json "esr" object exactly: 5 keys
    (available, value, flag, reference_range_used, captured_at) -- no
    "value_mm_hr", no "citation" (see AUDIT_NOTE above for that text)."""
    if not available:
        return {
            "available": False,
            "value": None,
            "flag": None,
            "reference_range_used": None,
            "captured_at": None,
        }

    if value is None or not captured_at:
        raise ValueError("available ESR requires a value and captured_at")
    if value < 0:
        raise ValueError("ESR value cannot be negative")

    return {
        "available": True,
        "value": float(value),
        "flag": _flag_for(value, age, sex),
        "reference_range_used": _reference_range_description(age, sex),
        "captured_at": captured_at,
    }


def unavailable_esr_block() -> dict:
    """Use when ESR was not measured for this case (ESR is optional)."""
    return build_esr_block(available=False)

# M3 contract API expected by this foundation's own README, demo and 50 tests.
# The older build_esr_block() is preserved for compatibility with earlier chats.
def make_esr(*, value_mm_hr=None, captured_at=None, lab_report_ref=None,
             upper_limit_mm_hr=None, lab_reference_description=None):
    """Lab-sourced ESR; no generic TB cutoff or inferred lab provenance."""
    from provenance import EvidenceError, aware_time, number, require_text
    if (value_mm_hr is None and captured_at is None and lab_report_ref is None
            and upper_limit_mm_hr is None and lab_reference_description is None):
        return unavailable_esr_block()
    value = number(value_mm_hr, 'esr.value_mm_hr', minimum=0, maximum=500)
    upper = number(upper_limit_mm_hr,'esr.upper_limit_mm_hr',minimum=0.00001,maximum=250)
    require_text(lab_report_ref,'esr.lab_report_ref')
    description = require_text(lab_reference_description,'esr.lab_reference_description')
    aware_time(captured_at,'esr.captured_at')
    flag=('markedly_elevated' if value >= MARKEDLY_ELEVATED_THRESHOLD else
          'elevated' if value > upper else 'normal')
    return {'available':True,'value':value,'flag':flag,
            'reference_range_used':f'{lab_report_ref}: {description}; '
                f'upper limit {upper:g} mm/hr (not a TB cutoff)',
            'captured_at':captured_at}
