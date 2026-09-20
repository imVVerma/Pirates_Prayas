# M4a — verifier decision and synthetic capacity routing (independent of M3)

**Scope:** headless **synthetic-only** domain component, not clinician-facing software or a clinical recommendation engine. Preserves frozen M0 case schema and M1 revision rules; works on M2 symptoms-only records **without** any X-ray, ESR, or diagnostic test results. No UI, no AI scoring, no large dependencies beyond M0/M1.

## What was implemented

- Explicit human `more_tests_needed`, `intervention_required` or `not_required` decision with reviewer identity, rationale, timestamp, revision and status history.
- `more_tests_needed` can await mobile X-ray/ESR scheduling with **no fake site** and add a real selected *synthetic* route as a separate revision later. It cannot be confused with a TB diagnosis.
- `intervention_required` can go directly to the diagnostic route **without waiting for X-ray/ESR**, or from the pending-extra-screening state; keeps `diagnosis=null` and never creates or pretends to have diagnostic results.
- Capacity registry verifies human-selected *demo* site against area, purpose, availability and reachability; does **not** claim actual nearest site, live slots, real travel calculations or verified NTEP sites.
- M0 snapshot validation and M1 `check_next` run before returning a candidate revision. SQLite persistence can be added by `CentralReceiver.ingest` and retries are idempotent at `(case_id, revision, content_hash)`.

## Run

Keep the existing folders as siblings `tb_m0/`, `tb_m1/`, `tb_m2/`, `tb_m4a/`. From the project root:

```bash
python -m pip install 'jsonschema>=4.18,<5'
PYTHONPATH=tb_m0:tb_m1:tb_m4a python -m unittest -v tb_m4a.test_m4a
```

M3 will attach evidence separately and return a pending case to `ready_for_review`; this engine then accepts the revision using precisely the same `review_case` action. **Do not modify the M0 schema in the M3 chat.**

## Important boundaries and integration blockers

1. **No server-side authentication yet.** `Principal` must come from trusted middleware, not a user-supplied JSON field. The existing M1 raw `/v1/cases` receiver permits any valid snapshot and therefore bypasses this domain layer. This prototype must remain bound to localhost and use synthetic records. Before any real deployment, enforce roles/credentials and command-only writes at a single authorized API boundary, including the offline sync producer.
2. **M0 requires a selected diagnostic site** in order to enter `routed_for_diagnostics`. If all simulated sites are unavailable the action returns an explicit error; future work must preserve a human decision to refer and place the referral into a pending-allocation queue rather than lose the clinical decision. That requires a deliberate M0 contract revision, not a made-up `site_id`.
3. Demo capacity is manually seeded. It is not a physical distance calculation, live lab booking, transport scheduling, or clinic integration.
4. No diagnostic lab, clinician confirmation, ASHA, treatment/pickup or evidence-return commands are implemented here. These are distinct follow-on slices after the clinician/workflow boundary is reviewed.
5. `expected_revision` protects against a stale local snapshot but does not replace an **atomic** read-check-write under real concurrency; any future authenticated route should enforce concurrency in the same DB transaction.
