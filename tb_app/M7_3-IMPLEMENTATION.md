# M7.3 — worker interface over unchanged M0–M6.5 state machinery

## Run

From extracted ZIP root (Python 3.11+; install `pip install -r tb_m3/requirements-core.txt`):

```
python tb_app/server.py central --db demo-central.sqlite3 --port 8765
python tb_app/server.py device --db demo-device.sqlite3 --port 8766 --central-url http://127.0.0.1:8765
```

Open `http://127.0.0.1:8766/field` for worker intake; `/field/cases` for worker case tracking; `/sync` for retained reviewer workbench; `/intake` for retained legacy intake. To demonstrate central outage, stop central only, submit **fictional** case while the local device process stays running, reopen central, retry on `/field/cases`.

## Changed files (relative to provided integrated M7)

- `tb_m2/intake_adapter.py`: optional source text, explicit cough answer, consented speech source and optional nonclinical report-availability claims; deterministic draft records original narrative verbatim and preserves `None` answers. Older M2 payloads still accepted.
- `tb_app/server.py`: worker page and JS asset routes, links in legacy nav. No change to clinical action endpoints.
- **New** `tb_app/field_intake.html` and `tb_app/field_intake.js`: one-question wizard with Hindi/English option, explicit yes/no/unknown, editable narrative, browser speech recognition if present and explicitly consented to, report availability questions, final draft review, M2 HTTP save and M1 sync attempt.
- **New** `tb_app/field_cases.html` and `tb_app/field_cases.js`: simple local outbox states and optional central clinical stage labels, plus retry. No clinical action controls.
- **New** `tb_app/test_field_intake.py`, `tb_app/test_field_browser.py`, and `tb_app/test_field_contract.py`: M0/outbox regressions, Chromium DOM test, and static designer HTML compatibility gate. # CHANGED
- `tb_app/DESIGNER-HANDOFF-M7_3.md`: visual-designer's two-file edit contract.
- Existing `tb_audit/intake-spine.html`, `tb_audit/tb-sync-layer.html`, M0/M1/M3/M4/M5/M6 and original `tb_app/app_sync.js` are untouched.

## Important boundaries / unfinished gates

1. **Not AI-extracted yet:** with no approved LLM or speech provider configuration, the current summary is an explicitly labeled rule-based draft from structured answers plus typed/transcribed text copied **verbatim**. Both sources take the exact same backend code path. Do not advertise as AI interpretation. No narrative-derived symptom fields are invented. A model-backed service needs explicit provider selection, data governance, evidence tests and worker confirmation before deployment.
2. Voice uses the browser's `SpeechRecognition`/`webkitSpeechRecognition` when available; the **browser provider may send audio remotely** and need connectivity. We don't store an audio file. Worker must consent before using mic, can review/edit resulting text, and can type instead. If consent is withdrawn, the voice transcript is cleared.
3. Intake report **claims** (`yes/no/unknown`) are preserved only as unverified text in `case_summary.brief_text`. The canonical `xray`/`esr` blocks remain `available:false` until M3 attaches a timestamped, traceable result via reviewer/lab flow. The worker cannot enter a model flag or arbitrary ESR cutoff here. Claim values are NOT a proof of capture.
4. UI offers fictional `Sample village A/B`, mapped to `DEMO-AREA-A/B` for seeded registry. Real locality entry and real records remain blocked until a genuine registry, consent/privacy program and secure role boundaries exist.
5. The local device Python service and SQLite must stay running; WAN/central outage is supported, browser-only standalone offline operation is NOT.
6. The reviewer workbench still uses synthetic actors, not authenticated/authorized production identities. No clinical deployment, no real patient data.
7. Actual browser-to-localhost acceptance in this managed environment is skipped (Chromium `ERR_BLOCKED_BY_ADMINISTRATOR`). Real Chromium DOM wizard + stubbed HTTP passes; real Python HTTP + SQLite tests pass. Run full journey locally before demo.

## Test commands

```
export PYTHONPATH=tb_m0:tb_m1:tb_m2:tb_m3:tb_m4a:m6_5:tb_app
python tb_m0/validate_cases.py
python -m unittest discover -s tb_m1 -p test_m1.py
python -m unittest discover -s tb_m2 -p test_m2.py
python -m unittest discover -s tb_m3 -p test_m3.py
python -m unittest discover -s tb_m4a -p 'test_*.py'
python -m unittest discover -s m6 -p 'test_*.py'
python -m unittest discover -s m6_5 -p 'test_*.py'
python -m unittest discover -s tb_app -p test_fullstack.py
python -m unittest discover -s tb_app -p test_field_intake.py
python -m unittest discover -s tb_app -p test_field_browser.py
python -m unittest discover -s tb_app -p test_field_contract.py
node --check tb_app/field_intake.js && node --check tb_app/field_cases.js
```

## Parallel designer merge gate

After receiving edited worker HTML, replace **only** `tb_app/field_intake.html` and `tb_app/field_cases.html`. Run `python -m unittest discover -s tb_app -p test_field_contract.py`, all `test_field_intake.py` tests, then a local browser walkthrough. If the contract test fails, reconcile the design rather than renaming the selectors in JS or modifying the M0 schema.
