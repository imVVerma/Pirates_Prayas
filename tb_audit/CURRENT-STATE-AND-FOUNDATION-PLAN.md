# Rural TB Detection & Continuity — source-code audit and foundation plan

Audit date: 2026-09-20. Basis: the 11 files in `Building-prototype-while-verifying-pitch-claims (1).zip`. This is a source/code audit, **not** a deployed clinical system validation. The sample-case JSON shipped alongside this document is synthetic and reconstructed from `tb-hackathon-team-doc.md`; it was not found as an existing downloaded case in the ZIP.

## Inventory and observed results

| Component | Evidence | Actual status |
|---|---|---|
| Project story / schema | `tb-hackathon-project-spec.md`, `tb-hackathon-team-doc.md` | An agreed *documented* JSON shape exists; not enforced by executable validation. |
| Intake | `intake-spine.html` | Form populates an in-memory JS object and can use Claude-artifact APIs for summary and download; lacks required fields and validation; no persistence. |
| Summary | `intake-spine.html` | Uses `claude.use('sample')`; cannot be considered an independent, offline or backend LLM service. Prompt supports non-diagnostic summary; behavior not independently exercised. |
| Sync | `tb-sync-layer.html` | JavaScript timer/array simulation of offline->online transitions, with generated *random* mock cases. No disk/device persistence, central server, HTTP transport, idempotency, acknowledgement, import from intake, or conflict control. |
| ESR | `esr_rule.py` | Imports and runs; `case_module.py` mock ESR output runs. Different keys from frozen schema. Invalid negative ESR/negative age/NaN are accepted; unknown sex raises. Clinical use of threshold not yet agreed. |
| CXR | `tb_xray_model.py` | Python syntax compiles and unavailable-image path runs. **Real inference not exercised.** Selected HF repo publishes a TensorFlow `.h5` weight file, whereas wrapper uses Transformers `AutoModelForImageClassification.from_pretrained` with a PyTorch-style softmax and Grad-CAM access. Treat as incompatible/unproven pending inspection, not functioning inference. |
| Assembly | `case_module.py` | Mock fragment works, but is not a full frozen case: `patient_id`, nested weeks in `symptoms`, different xray/ESR keys, and no workflow objects. |
| Verifier / routing / confirmatory result / ASHA | No implementation files in ZIP | Not built in supplied sources. |

Executed: `python -m py_compile esr_rule.py tb_xray_model.py case_module.py`, `python case_module.py`, `python esr_rule.py`, `node --check` on extracted JS from both HTML documents. These are *syntax and mock smoke tests* only. The two HTML artifacts were inspected, not browser-integration-tested. No large model, image weights, or UI styling work was run.

## Priority defects before expanding

1. **Contract drift:** Python fragment does not fit the documented frozen case. Preserve existing modules and normalize at an adapter boundary instead of rewriting everything.
2. **State-model ambiguity:** Clinical `status` and device `queued_locally/syncing/synced` are different concepts. Track `case_status` and `sync_status` separately. Record append-only verifier decisions and diagnostic results so re-review/loop-back does not overwrite history.
3. **Missing confirmation data:** `positive_confirmed` exists, but there is no confirmatory test order/result or clinical-diagnosis evidence in the schema. Intervention/referral is not TB confirmation. Treatment/adherence tasks must not be opened automatically from an abnormal CXR/ESR.
4. **No durable sync:** Use a local durable queue (SQLite or IndexedDB), stable case ID + monotonically increasing revision, durable ACK, idempotent server upsert, retry/cancellation, and a separate central database/queue. Simulate network loss, not the persistence itself.
5. **CXR loader mismatch:** Check published `.h5` model and original Keras preprocessing/label convention before assigning it to an inference backend. Leave Grad-CAM out until prediction works; raw model scores are not calibrated clinical probabilities.
6. **Clinical logic:** The named WHO four-symptom screen is specifically recommended for adults/adolescents living with HIV. Symptom intake can still be offered in other target populations, but population-specific pathway/labels must be explicit. ESR is nonspecific and must not gate access to molecular confirmatory testing. Do not use an invented 2-week rule as though it were the universal WHO four-symptom algorithm.
7. **Privacy/roles:** Before real data: consent captured, synthetic/deidentified demo fixtures, minimum necessary fields, explicit role authorization, protected local and remote storage, retention and audit trail.

## Build milestones and acceptance gates — no UI redesign

**M0 — Contract and clinical state transitions (first).** Produce `case-schema.json`, 4 synthetic fixtures (symptoms only / tests upfront / more-tests loop / diagnostic result), a validation script, and a short clinical workflow decision table. Explicitly agree minimum age/population scope, verifier permissions, pre-diagnosis ASHA support versus treatment follow-up, missing-data behavior and what constitutes clinical versus bacteriological confirmation. Gate: all valid fixtures pass schema; each deliberately malformed fixture fails; no UI edits needed.

**M1 — Durable store-and-forward (second).** Extract sync logic from HTML; persist actual intake-produced case JSON and revisions locally; send to a minimal central receiver; acknowledgement and idempotent ingestion. Gate: create case offline, restart app, regain connection, retry a dropped ACK without duplicate, reattach requested test to same case ID.

**M2 — Intake adapter and summary (third).** Preserve form, normalize existing output to the canonical contract, check missing/invalid field values, and supply deterministic non-diagnostic summary as fallback when LLM is unavailable. Gate: real generated intake case is validated, durably queued, and appears unchanged in review service; LLM failure does not lose the case.

**M3 — X-ray/ESR adapters (fourth).** Agree scope of ESR and source of clinical rule. For CXR, prove correct published-weight loading, preprocessing, label mapping and a tiny held-out labelled set; optionally attach image and model metadata. Gate: model identity and exact image-to-flag path tested; avoid unverified accuracy claims.

**M4 — Verifier, result, and routing core (fifth).** Implement API/data state machine and capacity registry with seeded *clearly synthetic* sites, not a dashboard first. Gate: human verifier can request tests, route directly to NAAT when indicated, receive a test result into the same case, close/route cases, and preserve all decisions and timestamps.

**M5 — ASHA follow-up core (sixth).** Distinguish sample-collection navigation/support from confirmed-TB treatment adherence. Implement assignments, scheduled/actual pickup events, missed-pickup alert, follow-up summaries and audit trail. Gate: mock case can complete intake->review->test->diagnosis->support without bypassing confirmation.

**M6 — Pitch, voice and UI polishing (last).** Once functional gates pass, connect the existing HTML or ask for new wireframes. Treat offline speech and Grad-CAM as stretch goals. Present simulated capacity and unvalidated models honestly.

## Design inputs needed from the team, not visual mockups

- A one-page **role/action matrix**: pharmacist, qualified verifier, diagnostic lab, ASHA; who may see/edit/close each field.
- A **clinical workflow decision table reviewed by an appropriate TB clinician or local NTEP guide**: which population, when direct molecular referral occurs, optional CXR/ESR, follow-up if negative/inconclusive, and when a clinician may diagnose without bacteriological confirmation.
- Definitions for **capacity registry** (availability means machine operational? appointments? sample transportation? latest status?), and seeded synthetic provider/ASHA records.
- For CXR inference: model files or repository, author-provided preprocessing/class mapping, plus a few deidentified/licensed, known-label demo images. No real patient data yet.

External verification entry points: WHO 2025 TB diagnosis recommendations, https://www.ncbi.nlm.nih.gov/books/NBK614638/ ; WHO targeted four-symptom recommendation, https://www.ncbi.nlm.nih.gov/books/NBK619220/ ; published model files, https://huggingface.co/Owos/tb-classifier/tree/main ; author's Keras prediction source, https://github.com/owos/tb_project/blob/main/predict.py .
