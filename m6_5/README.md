# M6.5 — UI-facing read model

This is a thin projection layer over the frozen M0 case contract. It is not a new clinical schema.

- `case_view.py` creates a deterministic read-only view for UI consumers.
- `canonical-demo-case.json` is a synthetic end-to-end case fixture.
- `test_case_view.py` validates projection behavior.

The projection does not infer diagnosis, treatment, referral, or clinical risk from X-ray/ESR. It only exposes values and explicit workflow state already present in the canonical case.
