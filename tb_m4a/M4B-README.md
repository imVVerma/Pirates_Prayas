# M4b — diagnostic result and clinician decision core

M4b extends M4a without changing the M0 schema. It records the diagnostic journey after a human verifier has routed a case.

## Flow

`routed_for_diagnostics → diagnostic test pending → diagnostic_result_available → diagnosed`

- `order_diagnostic_test()` records an explicit test order on the same case and revision history.
- `record_diagnostic_result()` is restricted to a trusted `lab` principal and records a final positive/negative/indeterminate result without allowing overwrite.
- `record_clinician_diagnosis()` is restricted to a trusted `clinician` principal. Bacteriological confirmation requires a positive supporting diagnostic test. Clinical diagnosis requires an explicit rationale.
- M4b does **not** decide treatment, assign an ASHA worker, or infer a diagnosis from X-ray/ESR.
- All changes are append-only revisions checked through M1 `check_next()` and validated against M0.

## Synthetic verification

```bash
PYTHONPATH=tb_m0:tb_m1:tb_m4a python -m unittest -v tb_m4a.test_m4a tb_m4a.test_m4b
```

This remains a synthetic engineering component. `Principal` must be resolved by trusted server/session middleware in any real deployment. The existing M1 receiver is not itself an authentication boundary.
