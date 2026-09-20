# TB prototype integration — M7 (synthetic, localhost only)

This package joins the **existing intake-spine.html** and **tb-sync-layer.html**
with the actual M0–M6.5 backend. Their original layout/CSS is reused, with
functional JavaScript substituted for the old in-memory random-case simulation.
No generated design mockups, web fonts, training or automatic diagnosis are needed.

## Launch (Python 3.11+; tested with 3.13)

Unzip all folders together. From the folder containing `tb_m0`, `tb_m1`,
`tb_m2`, `tb_m3`, `tb_m4a`, `m6`, `m6_5`, `tb_audit`, `tb_app`:

```bash
python -m pip install -r tb_m3/requirements-core.txt
# Terminal 1 — central receiver, start after intake if demonstrating an outage:
python tb_app/server.py central --db demo-central.sqlite3 --port 8765
# Terminal 2 — local pharmacist device; leave this running even with central down:
python tb_app/server.py device --db demo-device.sqlite3 --port 8766 --central-url http://127.0.0.1:8765
```

Open **http://127.0.0.1:8766/intake**; use synthetic data only, age >=18,
location `DEMO-AREA-A` (or `DEMO-AREA-B`), check both consent/demo acknowledgement
boxes, and save. Open **http://127.0.0.1:8766/sync** to view the real local M1
SQLite outbox, central M1 SQLite list and M6.5 case-detail projection. Use
**Retry sync** if the receiver was unavailable. Select a central case to operate
through the explicit decision workbench.

Stop only Terminal 1 to simulate a true central outage. Existing local cases
remain in `demo-device.sqlite3`; restart central and retry. The *local Python
service must stay running*: this is **offline WAN**, not browser-only offline.
The original intake form's legacy X-ray/ESR toggles remain disabled. Add
screening evidence in the workbench after sync, with source metadata.

## Demo path

1. `Intake` -> local SQLite -> (optional outage) -> `Retry sync` -> central.
2. On central case, `Human review` -> `more_tests_needed`, choose X-ray + ESR.
3. `Record synthetic X-ray capture` (image reference **only, no model inference**).
4. `Record synthetic lab ESR` with value, laboratory upper bound and synthetic
   reference. The M3 adapter returns the same case for a second review.
5. `Human review` -> `intervention_required`, select `DEMO-LAB-01` for area A.
6. `Order diagnostic test`, explicitly confirm the synthetic specimen was
   collected now. `Lab records result` -> `Clinician records diagnosis`, explicitly
   select the supporting completed result.
7. `Clinician confirms treatment plan` -> `records treatment initiation` ->
   `Assign ASHA treatment support` -> schedule pickup -> record missed pickup
   and replacement date -> record follow-up.

Negative/indeterminate results must NOT automatically close or confirm TB.
X-ray/ESR never create a diagnosis or select clinical referral by themselves.

## Gate and tests

```bash
python tb_m0/validate_cases.py
python -m unittest discover -s tb_m1 -p test_m1.py
python -m unittest discover -s tb_m2 -p test_m2.py
python -m unittest discover -s tb_m3 -p test_m3.py
PYTHONPATH=tb_m0:tb_m1:tb_m2:tb_m3:tb_m4a:m6_5 python -m unittest discover -s tb_m4a -p 'test_*.py'
PYTHONPATH=tb_m0:tb_m1:tb_m2:tb_m3:tb_m4a:m6_5 python -m unittest discover -s m6 -p 'test_*.py'
PYTHONPATH=tb_m0:tb_m1:tb_m2:tb_m3:tb_m4a:m6_5 python -m unittest discover -s m6_5 -p 'test_*.py'
python -m unittest discover -s tb_app -p test_fullstack.py -v
node --check tb_m2/intake_bridge.js && node --check tb_app/app_sync.js
# optional actual browser smoke; can skip on managed Chromium:
python -m unittest discover -s tb_app -p test_browser_fullstack.py -v
```

Tests use isolated temporary databases. The full-stack HTTP tests exercise an
actual central outage, retry, one stable case ID, monotonic revisions, optional
screening return, direct symptom-only diagnostic referral, rejection of false
bacteriological confirmation, fixed server-side demo actors, clinical diagnosis,
treatment initiation and missed pickup.
The Chrome-based test was **skipped here** because the managed browser blocked
localhost navigation. A human browser smoke test on your machine remains a
release gate. Everything must remain synthetic until permissions and security
are implemented and a qualified clinical review is complete.

## Roles, trust, and model integrity

Clinical pure engines continue to own every decision and transition. The
new `tb_app/workflow.py` uses **hard-coded synthetic demo principals** and
fake site/capacity records. This is NOT verified sign-in, credentialed
role-based access, live NTEP routing, secure PHI storage, or deployment code.
Both ports bind **127.0.0.1**; do not expose them or use real patient records.

No `tb_model.h5` checkpoint or labelled image bytes are in this package.
The uploaded M3 archive **contains a past 2-image smoke-test report** claiming
real-H5 load and raw-0–255 preprocessing, and reports severe false positives
on black/white/noise inputs. That report cannot be re-executed from this ZIP.
The M3 artifact was internally inconsistent: `test_m3.py` expected `make_esr`,
`infer_xray` and local-H5 helpers absent in the packaged Python files. M7
adds those APIs while keeping the earlier adapters; the provided 50 M3 tests
now run against actual source. The workbench allows an **image capture reference
without a model score**; it does not pretend image metadata is model evidence.
If a verified checkpoint and image storage are later provided, the `infer_verified_local`
API can be connected by a separately reviewed acquisition endpoint.

Known contract limitation: the frozen M0 assignment is a single object.
M5a does not permit converting an existing *pre-diagnosis navigation ASHA*
assignment into treatment support later. The workbench identifies the
limitation; for a complete treatment-support demo, do NOT first assign the
pre-diagnosis navigator. A proper phase-transition/audit event belongs in
an M0 migration, not an untracked server-side overwrite.

Other open gates: actual authentication/authorization, endpoint security,
clinician/NTEP workflow sign-off, clinical model suitability, case-conflict
reconciliation across multiple devices, patient-data protection and retention,
verified site capacity, and a three-state (yes/no/unknown) symptom UI.

## M7.3 new worker flow (supersedes M7 worker-facing intake, not the clinical workbench)

See `tb_app/M7_3-IMPLEMENTATION.md`. Start the same two Python processes, then open
`http://127.0.0.1:8766/field` (worker intake) and `/field/cases` (simple worker statuses).
Existing `/intake` and `/sync` remain available unchanged for regression/debug.
`tb_app/DESIGNER-HANDOFF-M7_3.md` restricts parallel visual design edits to the
new HTML/CSS files; do not rename DOM IDs or change clinical state logic.
