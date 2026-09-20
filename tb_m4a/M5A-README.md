# M5a — ASHA assignment and care-phase state machine

Backend-only synthetic prototype. No UI changes.

## Scope

M5a establishes the assignment boundary for ASHA support using the existing M0 contract:

- `pre_diagnosis_navigation` may be assigned only after an explicit human verifier/clinician review that requests additional screening or diagnostic referral.
- Pre-diagnosis navigation does not create a diagnosis, treatment task, or medicine-pickup log.
- `treatment_support` requires a clinician-recorded diagnosis, `treatment_plan_confirmed=true`, and an explicit treatment-initiation timestamp.
- Assignment does not change `case_status`; it creates a new revision of the same case.
- ASHA cannot assign itself, diagnose, or independently create treatment support.
- Revisions, consent, provenance and append-only history remain under M1/M0 rules.

## Files

- `asha_engine.py` — M5a operations.
- `test_m5a.py` — 13 unit/contract tests.

## Current boundary

M5a does **not** implement follow-up events, missed visits, medicine pickup events, reassignment, or ASHA-side authorization against a real credential store. Those belong to M5b / trusted-server integration.
