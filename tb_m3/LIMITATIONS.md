# M3 verification boundaries / corrections to the failed parallel-chat handoff

## Verified *here*

- Reviewed the original uploaded `tb_audit/tb_xray_model.py` (incorrectly uses Transformers AutoModel on a Keras H5) and `tb_audit/esr_rule.py` (generic >=20 fallback and generalized 33% normal ESR figure), M0 schema + semantic validator, M1 revision checker/store, M2 symptom-only fixture, and M4a engine.
- Verified public model card: `Owos/tb-classifier` lists Apache-2.0 and a TensorFlow model, not clinically evaluated. Model repo lists `tb_model.h5` ~87.7 MB. The web page's auto-generated Transformers code is not evidence of a runnable Transformers checkpoint. Source: https://huggingface.co/Owos/tb-classifier and https://huggingface.co/Owos/tb-classifier/tree/main .
- Read upstream repo `predict.py`, which uses `keras.models.load_model`, sets `classes=["Normal", "Tuberculosis"]` and divides images by 255; this *conflicts with the preceding chat's assertion* that external division always double-scales the checkpoint. Source: https://github.com/owos/tb_project/blob/main/predict.py . An actual `training.ipynb` + H5 inspection is required to settle this and verify that the supplied class mapping is correct for the exact H5.
- Ran real M0 cross-field validation and M1 check_next on screening revisions, M1 durable outbox/central receiver, and M4a verifier request/return/referral flow with synthetics. All 50 M3 offline tests passed.

## Not verified, do not claim

- **Real `.h5` loaded and predicted? NO.** TensorFlow/tf-keras and the 87.7 MB real weights are not present in this Python 3.13 environment. `infer_xray` unit tests used a clearly marked *fake scalar model* to exercise contract/preprocessing/error behavior. TF/Keras compatibility is a proposed env pin, not a passing real-checkpoint test.
- **Correct real-model preprocessing? OPEN.** Upstream inference script and earlier-chat claim conflict. The code refuses ambiguous auto scaling. Model-declared Rescaling is evidence, not proof of its training input normalization; verify data pipeline too.
- **Label direction? OPEN for actual H5.** Script provides a two-sample smoke check but no two-image result was produced here. It is no replacement for a held-out set.
- **Clinical accuracy, external generalization or WHO CAD product approval? NOT ESTABLISHED.** Model-card accuracy/recall are self-reported and cannot be presented as independent held-out validation. WHO's 2025 CAD policy names evaluated products, not blanket approval of arbitrary open models: https://www.who.int/publications/i/item/9789240110373/ .
- **Grad-CAM on real H5? NOT RUN.** Previous chat said its code was in a private `/home/claude/m3` sandbox but never delivered. This package does not pretend to contain or have tested that implementation. M0 `heatmap_ref` stays null unless a future verified module supplies one.
- **ESR clinical validation? NOT ESTABLISHED.** Only record lab interval and non-specific descriptive tier. ESR is not a WHO-endorsed TB diagnosis, TB rule-out, or prerequisite to molecular referral. Earlier chat's "33% normal ESR" comes from children with an ESR recorded; do not extrapolate to all TB cases. There is no generic >=20 mm/h gate.
- **Real laboratory, image-store, actor authorization, report authenticity, image consent, site capacity? NOT IMPLEMENTED.** `lab_report_ref` and `actor_role` are caller-provided in this synthetic prototype. Current M1 receiver accepts schema-valid snapshots and is not a credential-enforcing clinical backend. No separate security/privacy review or clinician sign-off.
- **Multiple serial ESR or new images? NOT SUPPORTED in M0.** Replacing already attached readings is forbidden. A real case may require more than one observation; extend contract with an append-only screening-event list in a future version and migration.
- **Summary regeneration? Not done.** M2 `case_summary` records its generation time at intake; M3 does not alter that historical brief or let it suppress newly available test evidence. Dashboard should render current structured observations.

## Next gating work, ordered

1. Obtain actual model H5 and training/preprocess evidence in a compatible isolated ML environment. Verify scaling and label mapping; save SHA-pinned smoke report. If unavailable, keep X-ray model unverified and demo image present without fabricated AI flag.
2. Clinician/NTEP sign-off on workflow and ESR display decisions; verify local reporting and intended population. These are requirements for pilot use, not a blocker for a labeled synthetic engineering demo.
3. Wire M3 test creation through trusted server actor and controlled evidence storage; authenticate users and enforce role/site/report provenance. Do not claim M1 HTTP alone provides this.
4. Browser smoke test on real localhost intake→M1, then M3 attachment→M4a human decision with clean synthetic fixtures; preserve no UI redesign.
