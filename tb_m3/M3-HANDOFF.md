# M3 handoff / explicit gate

**Contract M3: PASS (50 tests)** with the actual M0/M1/M2/M4a files. **Live X-ray model M3: OPEN** (weights + TF not used). No interface work and no AI training.

### Integrated
- Correct M0 blocks: `xray.available/image_ref/model_flag/model_confidence/heatmap_ref/model_id/captured_at` and `esr.available/value/flag/reference_range_used/captured_at`.
- `make_esr` takes real operator-supplied laboratory report reference, measured time, and lab reference. No default 20 mm/h TB cutoff.
- `attach_screening_tests` increments M1 revision on change, reuses stable case_id/patient/consent/histories, rejects overwrite/stale evidence, retries idempotently, only makes pending→ready after all specifically requested tests arrive. Does NOT diagnose or choose treatment/referral.
- X-ray uses local Keras `.h5`, not Transformers AutoModel. Raw sigmoid model output preserved and SHA/threshold/preprocessing recorded in legacy `model_id`. Fail closed when scaling or actual label mapping is unresolved. Grad-CAM not claimed.
- M4a review request→M3 data return→M4a explicit diagnostic referral→M1 durable receiver tested, synthetic only.

### Required before real-model claim
- Isolated Python 3.11/3.12 environment; actual local checkpoint and 2 known images; reconcile original notebook/preprocess and model internal scaling; run `verify_xray_model.py`; publish report + new smoke results (not weights or sensitive images); ensure M0 is still satisfied.
- No WHO approval / clinical sensitivity / held-out validation claim for this model. Clinician review needed for ESR and clinical pathway.
- M2 legacy manual X-ray/ESR controls remain disabled; evidence capture and trusted authorization are distinct future work.
