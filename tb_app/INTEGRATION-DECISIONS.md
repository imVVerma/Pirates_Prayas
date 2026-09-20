# Architecture decisions — M7

| Layer | Source reused | Integration |
|---|---|---|
| Browser intake | `tb_audit/intake-spine.html` and `tb_m2/intake_bridge.js` | Original page/CSS retained; explicit synthetic/consent gate; saves M0 case. |
| Local durability | `tb_m1/store.py` + `tb_m2/intake_adapter.py` | Single local SQLite outbox; patient case_status never stores transfer state. |
| Transport | `tb_m1/client.py` and `tb_m1/server.py` | Separate actual HTTP receiver, ACK, retries, `(case_id,revision)` dedup; receiver can be stopped independently. |
| Browser sync | `tb_audit/tb-sync-layer.html` | Reuses page/CSS; **replaces fake random generator and timeout-based simulated sync** with central API and durable queue. |
| Dashboard projection | `m6_5/case_view.py` | Canonical state is source of truth; intake summary is not refreshed as if it were live AI evidence. |
| X-ray/ESR | `tb_m3/screening_attach.py`, `xray_adapter.py`, `esr_adapter.py` | Capture only without model; lab-reference ESR; M3 provenance, no auto medical decision. |
| Human review/routing | `tb_m4a/review_engine.py` | Verifier-selected decision, synthetic area-specific sites; explicit rationale. |
| Diagnosis | `tb_m4a/diagnostic_engine.py` | Verifier order, lab result, distinct clinician-recorded diagnosis. |
| Continuity | `tb_m4a/asha_engine.py` & `followup_engine.py` | Diagnosis/plan/start prerequisites; append-only pickup/follow-up; missed pickup remains visible. |

The central API is the single **post-sync revision writer**. The local outbox
retains intake revision (not a second mutable copy of later central revisions)
to avoid creating a divergent local author. This is a deliberate single-device
prototype choice, not general bi-directional synchronization.

`m6_5/case_view.py` now skips a scheduled medicine pickup after its immutable
missed or picked-up outcome has also been logged. Previously the old schedule
continued to display as the next action.

The M3 version mismatch inside the uploaded ZIP was a material blocker, not a
UI problem. Legacy file functions were preserved, missing canonical interface
functions restored, with 50/50 included M3 tests passing after reconciliation.

Final M7 tests also verify a symptom-only referral succeeds without X-ray/ESR, a negative diagnostic result cannot be recorded as bacteriological confirmation, and browser-submitted actor labels do not override fixed server demo principals.
