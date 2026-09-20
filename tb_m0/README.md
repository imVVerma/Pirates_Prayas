# M0 — executable case contract and state-transition gate

This package is the foundation layer for the rural TB-detection hackathon prototype. It makes **no UI edits** and downloads **no AI model**. All example values, site IDs and worker IDs are synthetic; none are patient data.

## Contents

- `case-schema.json` — JSON Schema Draft 2020-12 for a case **snapshot**, with `schema_version=1.0.0`.
- `fixtures/01-symptoms-only.json` — Branch A initial review, no X-ray/ESR.
- `fixtures/02-tests-upfront.json` — Branch B, screening tests already available.
- `fixtures/03-more-tests-loop.json` — same `case_id` from request → extra X-ray → re-review → diagnostic referral, pre-diagnosis ASHA **navigation only**.
- `fixtures/04-diagnostic-result.json` — positive Xpert Ultra, clinician-recorded bacteriological confirmation, clinician-confirmed treatment plan, recorded actual treatment start, then ASHA treatment support.
- `invalid-fixtures/` — seven explicitly malformed JSON cases (shape, age, units, flags and timestamps) that must **fail JSON Schema** validation.
- `validate_cases.py` — validates schema **and** cross-field/temporal/clinical-state invariants; includes 15 additional mutation-rejection tests and a positive constructed *clinically diagnosed* scenario.
- `CLINICAL-WORKFLOW-AND-DECISIONS.md` — exact design decisions, a decision table, role/action table, schema migration notes, source links and clinical-signoff caveats.
- `TEST-RESULTS.txt` — captured validation run.

## Run the gate

```bash
python -m pip install 'jsonschema>=4.18,<5'
cd tb_m0
python validate_cases.py
# Expected final line: M0 GATE: PASS
python validate_cases.py --case fixtures/03-more-tests-loop.json
```

**Two layers of validation:** JSON Schema catches required fields, unknown keys, incorrect types, illegal enums, age <18, negative numeric values and malformed RFC 3339 timestamps. Python catches dependencies JSON Schema cannot express cleanly (history consistency, role per transition, diagnostic evidence links, ASHA/treatment gating, voice consent and temporal order). A schema-pass alone is **not** a clinically valid case; downstream writes must use the combined validator.

## Contract rules for the next modules

- Same `case_id` for a loop-back; different `patient_ref` for different synthetic patients. Real identity/contact mapping stays outside this portable case payload.
- Preserve all `review_history` and `status_history` entries when updating a case. Increment `revision` on each new persisted case snapshot; M1 must compare a prior version to enforce append-only behavior.
- Keep device-local `sync_status` and ACK/retry metadata **outside** this clinical case snapshot.
- `null` symptom = unknown, `false` = explicitly absent; `available=false` X-ray/ESR means no test evidence, not normal. Prior X-ray/ESR may have been taken before `created_at`; the case attaches their actual capture times.
- Missing X-ray/ESR never blocks clinically indicated molecular referral. No ESR threshold is endorsed by this milestone.
- The existing HTML intake and sync and the old Python X-ray/ESR fragment **do not yet conform** to this contract. M1/M2/M3 should add **small explicit adapters**, preserving the underlying prototype rather than refactoring UI.
- Authorization in M0 is modelled using auditable actor-role claims in state history. **Do not trust those fields as authentication**: the future server must derive roles from verified user credentials.

Clinical assumptions are proposed M0 design defaults pending clinician/NTEP confirmation, not validated care guidance. See `CLINICAL-WORKFLOW-AND-DECISIONS.md` for source links and boundaries.
