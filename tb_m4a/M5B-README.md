# M5b — ASHA follow-up and continuity engine

Backend-only synthetic prototype. No UI changes.

## Scope

M5b extends the M5a ASHA assignment boundary into continuity-of-care events while preserving the existing M0 contract.

### Follow-up events

- Planned navigation/treatment follow-ups are appended to `followups` as `Scheduled:` entries.
- Actual ASHA interactions are appended as later `followups` entries.
- Existing follow-up records are never edited in place.
- Only the assigned ASHA can record an actual follow-up interaction.
- Treatment follow-ups require `treatment_support` assignment.
- Voice follow-ups require the existing audio-recording consent.

The frozen M0 follow-up object has no separate event-status or event-ID fields, so M5b deliberately does not invent a new schema. Scheduled and completed interactions are represented as separate append-only records.

### Medicine pickup continuity

- Pickup scheduling appends a `scheduled` entry.
- Completion appends a `picked_up` entry without modifying the original scheduled record.
- A missed pickup appends a `missed` outcome.
- If a replacement date is supplied for a missed pickup, the new `scheduled` entry is appended in the same revision.
- Duplicate outcomes and duplicate open schedules are rejected.

### Safety / workflow boundaries

- M5b never changes `case_status`.
- M5b cannot create a diagnosis or treatment plan.
- Treatment-support continuity remains dependent on the M5a clinician-recorded diagnosis and explicit treatment initiation boundary.
- Stale revisions, missing consent and unauthorized roles are rejected.

## Files

- `followup_engine.py` — M5b operations.
- `test_m5b.py` — 11 unit/contract tests.
- `M5B-RESULTS.txt` — verification record.

## Core API

```python
schedule_followup(...)
record_followup(...)
schedule_medicine_pickup(...)
record_medicine_pickup(...)
```

## Verification

M5b: 11/11 passed.

Regression executed in the current package:

- M0 contract: PASS
- M1 persistence: 10/10
- M3: 50/50
- M4a + M4b + M5a + M5b: 43/43

M2's prior core result remains 11/11; its packaged browser smoke test has the previously documented legacy-file environment mismatch and was not silently changed here.
