# M3 — optional X-ray / ESR evidence, reconciled with M0 → M1 → M2 → M4a

**Engineering status: M3 contract/ESR integration pass; real pretrained-weight inference gate OPEN.** All included fixture data are synthetic. No UI changes, model downloads, model training, or real patient data were used.

## How to use this handoff

Place `tb_m0`, `tb_m1`, `tb_m2`, `tb_m3`, and `tb_m4a` **as sibling directories**. M0 and M1 are the authority for validity/revisions; M3 does not modify their contracts.

| File | Responsibility |
|---|---|
| `provenance.py` | Strict real RFC3339 offset-aware timestamps, finite numbers, explicit identifiers. |
| `esr_adapter.py` | Lab-reported numeric ESR and lab's **actual reported** upper reference range; no fake generic >=20 rule. `make_esr()` returns the exact M0 ESR block. |
| `xray_adapter.py` | Opt-in local Keras H5 adapter, fail-closed preprocessing detection, model hash, raw sigmoid score, frozen-schema output. Does not download weights. |
| `verify_xray_model.py` | Offline smoke check against operator-supplied correctly labeled normal/TB images; ties preprocessing/label assumption to exact H5 bytes. Not clinical validation. |
| `screening_attach.py` | Pure `attach_screening_tests(existing_case, xray=..., esr=..., actor_id=..., actor_role=..., event_at=...)`; validates with real M0/M1; zero side effects. |
| `demo_assemble_case.py` | Creates a **synthetic** next revision with image observed but **no AI score**, and ESR lab provenance. No stale stub interface. |
| `test_m3.py` | 50 offline unit + contract/integration tests including M4a request→M3 return→M4a diagnostic referral and M1 persistence. |
| `LIMITATIONS.md` | Precise remaining technical/clinical work and links to original evidence. |

## Gate reproducibility — no ML packages required

From the parent directory:

```bash
python -m pip install 'jsonschema>=4.18,<5' 'numpy>=1.26,<3' 'Pillow>=10,<13'
python tb_m0/validate_cases.py
python -m unittest discover -s tb_m1 -p 'test_m1.py'
PYTHONPATH="$PWD/tb_m0:$PWD/tb_m1:$PWD/tb_m2" python -m unittest discover -s tb_m2 -p 'test_m2.py'
python -m unittest discover -s tb_m3 -p 'test_m3.py' -v
PYTHONPATH="$PWD/tb_m0:$PWD/tb_m1:$PWD/tb_m4a" python -m unittest discover -s tb_m4a -p 'test_m4a.py'
python tb_m3/demo_assemble_case.py --out /tmp/m3-synthetic-case.json
```

Latest measured results (current sandbox Python 3.13): M0 PASS; M1 10; M2 11; M3 **50**; M4a 18. No full real H5 loaded, so these cannot be reported as a verified real-model gate.

### M3 primary operation: attaching a later test result

```python
from screening_attach import attach_screening_tests
from esr_adapter import make_esr

esr = make_esr(value_mm_hr=42,
               captured_at='2026-09-20T04:32:00+05:30',
               lab_report_ref='SYNTHETIC-LAB-42',
               upper_limit_mm_hr=22,
               lab_reference_description='synthetic reported reference 0-22 mm/h')
new_case = attach_screening_tests(old_case, esr=esr,
            actor_id='demo-pharmacist-1', actor_role='pharmacist')
# old_case unchanged; new_case.revision == old_case.revision + 1
# M1 LocalOutbox.enqueue(new_case) then normal opportunistic sync.
```

For `pending_additional_test`, provide a **real supplied** `event_at` only on receipt of all tests the reviewer explicitly requested; the adapter appends `pending_additional_test → ready_for_review` with actor and timestamp. Partial returns remain pending; no fabricated timestamps or duplicated cases. If same evidence is re-attached, revision does not increase. Results already present cannot be overwritten; schema cannot record a second X-ray or ESR observation without a later extension.

**M0's `case_summary` is a timestamped intake brief, not a live view.** M3 does not rewrite it into an invented AI summary. The eventual verifier dashboard should read live `xray`/`esr` fields and their provenance. X-ray/ESR never create a diagnosis, clinical referral decision, ASHA treatment support or molecular assay result.

## Exact real-weight gate (still required)

1. On a computer with Python **3.11 or 3.12**, install `tb_m3/requirements-ml.txt` in a fresh virtual environment; do not force TensorFlow into the Python 3.13 core sandbox.
2. Separately acquire approved-for-the-demo, local `Owos/tb-classifier` **`tb_model.h5`** from its model repository. The model card lists Apache-2.0; it describes research use and explicitly states **no clinical testing**. Avoid downloading to just run offline contract tests.
3. Inspect the **actual** H5 model for input image size, scalar sigmoid, internal rescaling, and whether the training pipeline did any normalization outside the model. The upstream prediction script uses `/255`, while the previous chat reports a notebook with an internal `Rescaling(1/255)`; these cannot be reconciled from a conversation alone. Reject ambiguous scaling until resolved, then specify `--preprocessing raw_0_255` or `zero_one` based on evidence. `auto` accepts **one** identifiable in-model `Rescaling(1/255)` and otherwise fails closed.
4. With two independently labeled, properly usable normal/TB sample images, run:

```bash
python tb_m3/verify_xray_model.py \
  --model /secure/path/tb_model.h5 \
  --normal /secure/path/known_normal.png \
  --tb /secure/path/known_tb.png \
  --preprocessing auto \
  --report /secure/path/model-smoke-report.json
```

5. Only after report PASS, use `infer_verified_local(model_path=..., verification_report_path=..., image_path=..., image_ref=..., captured_at=...)` to populate X-ray with raw output in legacy-named `model_confidence`; `model_id` includes H5 SHA256 + cutoff + pixel processing. Report binds actual bytes but is **not cryptographically signed**. A two-image check is **not** held-out validation, model calibration or WHO CAD approval. When the actual H5 fails, document the failure and leave `xray.model_flag=None` rather than attach fabricated evidence.

**No UI enablement** until an authorized acquisition source supplies image/report refs and real timestamps and the local evidence store controls access. Do not expose image paths or lab identifiers that contain patient personal data.
