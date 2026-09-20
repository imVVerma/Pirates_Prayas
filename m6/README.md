# M6 End-to-End Integration Gate

Backend-only integration gate for the rural TB screening and continuity prototype.

## Journey exercised

`M2 intake -> M4a human review -> M3 verified X-ray/ESR return -> M4a diagnostic referral -> M4b diagnostic order/result/diagnosis -> M5a treatment initiation/ASHA assignment -> M5b continuity events`

The X-ray value used by the integration test is the **recorded output of the real uploaded `tb_model.h5` smoke test**, not a newly inferred value in this package. The supplied M3 report records raw-0-255 preprocessing, normal score 0.0246406496, TB score 0.9847194552, and a final verification verdict of PASS. This preserves the distinction between model verification evidence and a fresh model run.

## Gate

- One stable `case_id` through the entire journey
- Monotonically increasing revisions
- Screening evidence does not create diagnosis
- Human verifier explicitly creates diagnostic referral
- Diagnostic result is supplied by lab
- Diagnosis is explicit clinician action
- Treatment support requires treatment-plan confirmation and explicit initiation
- ASHA continuity is append-only
- Missed pickup is retained and replacement pickup is appended
- Clinical `case_status` remains distinct from sync state

## Known unrelated environment issue

The packaged M2 browser test expects the historical `tb_audit/intake-spine.html`, which is not part of this foundation package. M2's core adapter/HTTP suite previously passed 11/11. This is retained as an environment/package fixture issue, not silently patched during M6.
