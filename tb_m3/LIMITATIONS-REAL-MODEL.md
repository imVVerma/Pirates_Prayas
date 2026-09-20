# M3 — X-ray/ESR module audit, fixes, and real-model verification

Scope: verify and strengthen the existing X-ray and ESR modules, produce
small adapters emitting output conforming to M0's frozen
`case-schema.json`, backed by tests. No UI changes, no training.

**Verification gate status: CLOSED.** The real `tb_model.h5` and two
labelled reference images (the model author's own widget examples,
`tb-negative.png`/`tb-positive.png`) were provided and run end-to-end.
Every item on the M3 checklist below has a concrete, evidenced result.

```
[x] tb_model.h5                       -- provided, loaded, verified
[x] Known-normal X-ray                -- provided (author's own reference image)
[x] Known-TB X-ray                    -- provided (author's own reference image)
[x] Verify H5 input/preprocessing     -- RESOLVED: raw 0-255 input confirmed two independent ways
[x] Verify Normal/TB label direction  -- CONFIRMED: normal=0.025, TB=0.985
[x] Run verify_xray_model.py          -- PASS
[x] Save smoke-test report            -- reports/smoke_test_report_20260920T002345Z.{json,md}
```

## 1. Old module bugs (confirmed, not assumed)

### 1a. The X-ray model loader was broken and would fail every time
Old `tb_xray_model.py` used
`AutoModelForImageClassification.from_pretrained("Owos/tb-classifier")`.
The checkpoint is a Keras/TensorFlow HDF5 file (`tb_model.h5`), not a
`transformers`-format checkpoint; the repo's `config.json` declares
`"architectures": ["InceptinV3ForImageClassification"]` — a class that
does not exist in `transformers` (typo/placeholder). This would raise on
any machine, immediately. **Fixed**: load `tb_model.h5` directly with
`keras.models.load_model` (`xray_adapter.LazyKerasTBModel`).

### 1b. Preprocessing was wrong — RESOLVED WITH THE REAL FILE, not a guess
The user's M3 handoff flagged this as genuinely ambiguous: the author's
own deployment scripts (`predict.py`, `deployment/streamlit_deploy.py`)
manually divide the loaded image by 255 before calling `predict()`, but
the training notebook's `base_model()` builds the model with an internal
`Rescaling(1/255)` layer applied to the raw input. Resolved two
independent ways against the **actual uploaded weights**:

1. **Static**: `scripts/inspect_h5_architecture.py` opened the real
   `tb_model.h5`'s embedded Keras config (via `h5py`, no TensorFlow) and
   found: `Rescaling` layer, `scale=0.00392156862745098` (=1/255), right
   after the `InputLayer`. Input shape `(None, 300, 300, 3)`.
2. **Empirical**: `scripts/verify_xray_model.py` ran the real model on
   both labelled images under both conventions:

   | preprocessing | known-normal score | known-TB score | separation |
   |---|---|---|---|
   | raw 0-255 (correct) | 0.0246 | 0.9847 | **0.9601** |
   | pre-divided by 255 (author's scripts) | 0.9897 | 0.9907 | 0.0010 |

   Static and empirical evidence agree: **feed the model raw 0-255 pixel
   values.** The author's own `predict.py`/`streamlit_deploy.py` almost
   certainly double-rescale relative to how the model was actually
   trained — a real bug in the upstream repo, now avoided here.

**Fixed** in `xray_adapter.preprocess_image` (no `/255` division).

### 1c. Framework compatibility bug found while verifying (new finding)
Loading the real `tb_model.h5` with plain `keras.models.load_model` under
TensorFlow 2.21 / Keras 3 (the version Python 3.12 installs) raised:
```
ValueError: Invalid Functional model configuration. The graph of the
Functional model either has loops or disconnected nodes.
```
The file is a Keras Functional model with a **nested Functional submodel**
(InceptionV3 nested inside the outer classifier) — Keras 3 cannot resolve
that from a legacy H5 file. **Fixed**: install `tf-keras` (Keras 2
compatibility shim) and set `TF_USE_LEGACY_KERAS=1` before importing
`tensorflow`; confirmed this loads the identical file with zero errors.
`LazyKerasTBModel` sets this automatically.

### 1d. Output labels/enum were wrong
`config.json`: `id2label={"0":"Negative","1":"Positive"}`; `predict.py`:
`classes=["Normal","Tuberculosis"]`, index 1/high score = TB-positive.
**Confirmed on the real model + real images**: known-normal scored 0.025
(low), known-TB scored 0.985 (high) — direction matches. The old module's
schema field used `"positive"/"negative"`; the real schema enum is
`"abnormal"/"normal"` (M0's own `invalid-fixtures/02-bad-xray-flag.json`
exists to catch exactly that mistake). **Fixed** in
`xray_adapter.postprocess_score`.

### 1e. Both old modules emitted a field the schema forbids
`case-schema.json`'s `xray`/`esr` objects are `additionalProperties:
false` with exactly 7 and 5 keys. Both old modules added a `citation`
key. **Fixed** — citation/audit text now lives in each module's docstring
and `AUDIT_NOTE` constant, not in the synced JSON.

### 1f. ESR used the wrong field name
Old `esr_rule.py` emitted `value_mm_hr`; real field is `esr.value`. M0's
own `invalid-fixtures/03-wrong-esr-field.json` exists to catch this exact
mistake. **Fixed** in `esr_adapter.py`.

### 1g. Grad-CAM used the wrong library for the wrong kind of model
Old code used `pytorch_grad_cam` against `model.inception.Mixed_7c` —
both assume a PyTorch model. The real checkpoint is Keras/TensorFlow.
Replaced with a small TensorFlow-native Grad-CAM in `heatmap.py`.
**Not yet exercised against the real nested-model checkpoint** (see
Section 4) — kept explicitly best-effort/optional as originally scoped.

## 2. New finding from verification: the model has low specificity

Running the real model on degenerate/garbage inputs (all-black, all-white,
random noise — all under the *confirmed-correct* raw-0-255 preprocessing)
produced:

| input | score |
|---|---|
| all-black | 0.9901 |
| all-white | 0.9952 |
| random noise | 0.9865 |
| (for comparison) known-TB image | 0.9847 |

**The model scores meaningless/degenerate inputs in the same range as a
genuine TB-positive image.** It appears to default to "abnormal" for
almost anything that doesn't specifically match its narrow training
distribution of normal chest X-rays, rather than genuinely recognizing
TB-specific features. This is a real, measured limitation (not a guess),
now documented in `xray_adapter.py`'s `AUDIT_NOTE` and enforced in
practice by never letting `model_flag`/`model_confidence` feed any
decision logic (see Section 3). Expect elevated false-positive risk on
any out-of-distribution input — wrong image type, unusual positioning,
scanner artifacts, non-chest images.

## 3. Clinical-appropriateness review of the ESR rule (requested by M0)

- **Kept unchanged**: age/sex-adjusted Westergren normal ranges (standard,
  uncontroversial clinical reference values).
- **Reworded**: old docstring called ESR ≥100 mm/hr a "TB adjunct signal
  specifically" — overstated given its own cited evidence (a single
  correlational cohort study, and ~33% of confirmed TB cases having a
  *normal* ESR). Schema's three-tier enum kept; language now frames
  `markedly_elevated` as a nonspecific high-inflammation flag, not a
  TB-specific finding.
- **Confirmed, not just claimed**: neither adapter has any code path
  feeding `flag`/`model_flag` into `case_status`, routing, or referral
  decisions. `demo_assemble_case.py`'s four scenarios only ever set
  `xray`/`esr`, never `case_status`/`review_history`.

## 4. Evidence: 36 tests, all passing

Run: `cd m3 && TF_USE_LEGACY_KERAS=1 python3 -m unittest discover -s tests -v`

- **Pure logic, no network/model needed** (13 ESR tests, 14 X-ray tests):
  tiering, boundaries, missing-age/sex fallback, preprocessing shape/scale
  (now asserting raw values, not `<=1.0`), score→flag/confidence mapping,
  null-field invariants.
- **Real M0 gate acceptance** (6 tests): imports M0's own unmodified
  `case-schema.json`/`validate_cases.py`; proves our blocks pass the real
  gate and the exact old bugs (`value_mm_hr`, `"positive"` flag, stray
  `citation`) are actually rejected by it.
- **Real model integration (3 tests, NOT stubbed)**: `LazyKerasTBModel`
  loads the actual uploaded `tb_model.h5`, runs the actual uploaded
  `tb-negative.png`/`tb-positive.png` through `build_xray_block`, and
  confirms `model_flag="normal"`/`"abnormal"` land correctly, with the
  schema shape still exact.
- `demo_assemble_case.py`: four realistic scenarios (neither available,
  ESR-only, X-ray captured-not-scored, **X-ray with the real model**)
  through the real M0 gate — all four PASS. Real-model scenario reports
  `abnormal (confidence=0.9847)`, matching the smoke-test report exactly.
- Re-ran M0's own `validate_cases.py` unmodified against its own
  fixtures: still `M0 GATE: PASS` (28/28) — confirms we didn't touch or
  break the frozen contract.
- Full smoke-test report: `reports/smoke_test_report_20260920T002345Z.{json,md}`.

## 5. What remains open

- **Grad-CAM heatmap** (`heatmap.py`) has not been run against the real
  nested-model checkpoint. The nested InceptionV3 submodel makes locating
  a "last conv layer" and building a Grad-CAM sub-graph materially
  harder than a flat architecture; it will most likely degrade to
  returning `None` gracefully on this specific file rather than actually
  producing a heatmap. Kept explicitly best-effort/optional, as
  originally scoped ("if time allows") — never blocks the rest of the
  `xray` block.
- **Model validation remains self-reported only** (binary_accuracy
  0.9857, precision 0.9259, recall 0.9843 on a held-out split of its own
  training data). No independent/external-cohort validation. Combined
  with the low-specificity finding in Section 2, `model_confidence`
  should be treated purely as an uncalibrated screening score.
- **Only one image per class was tested.** The label-direction and
  preprocessing checks are decisive on these two images (huge, clean
  separation), but a single positive/negative pair is not a statistical
  validation — it confirms the *mechanics* (loading, scaling, label
  direction) are correct, not the model's real-world accuracy.
- **License**: HF repo tagged `apache-2.0` (weights); author's code repo
  MIT. Both permissive; not a substitute for legal review before a pilot.
- **ESR clinical scope unchanged from M0**: nonspecific lookup rule, no
  gating logic reads its output.
- **Symptom intake / fusion scoring / verifier dashboard**: out of scope
  for this chat, untouched.

## 6. Files delivered

```
xray_adapter.py                      corrected X-ray adapter (Keras H5, verified raw-0-255 preprocessing/labels)
esr_adapter.py                       corrected ESR rule adapter (schema-exact fields, reviewed language)
heatmap.py                           optional Grad-CAM (TensorFlow-native; not yet run on the real nested model)
demo_assemble_case.py                4-scenario demo, incl. the REAL model, run through the real M0 gate
requirements.txt                     pinned dependencies incl. confirmed tf-keras/TF_USE_LEGACY_KERAS requirement
scripts/inspect_h5_architecture.py   static H5 architecture check (h5py only) -- resolved the preprocessing ambiguity
scripts/verify_xray_model.py         full smoke test: load, shape check, preprocessing cross-check, label direction, bias check, report
scripts/upstream_training_notebook_evidence.ipynb   the actual training notebook pulled from github.com/owos/tb_project, kept as evidence
reports/smoke_test_report_20260920T002345Z.{json,md}   the actual verification run's output
tests/test_esr_adapter.py            13 unit tests, network-free
tests/test_xray_adapter.py           14 unit tests, network-free (stub model)
tests/test_real_model_integration.py 3 tests against the REAL uploaded weights + real labelled images
tests/test_schema_compliance.py      6 tests against M0's REAL unmodified schema/validator
tests/m0_contract/                   verbatim copies of M0's case-schema.json, validate_cases.py, fixtures/01-symptoms-only.json
```
