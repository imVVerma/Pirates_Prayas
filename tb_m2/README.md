# M2 — original intake → M0 contract → durable M1 outbox → central receiver

**Synthetic-only, adults 18+, localhost prototype.** M2 does not alter the original `tb_audit/intake-spine.html` on disk or design a new UI. Its same-origin local server injects an integration-only JavaScript bridge when serving the original HTML. The bridge adds **two functional required checkboxes** (explicit data/share consent and synthetic-data-only acknowledgement), disables the unverified legacy X-ray/ESR controls, and intercepts the existing two buttons. **The browser cannot save cases on its own if the local Python device process is stopped**: "offline" here means disconnected from the *central receiver* while the local device service and SQLite are running. M1 demonstrates survival of Python restarts.

## Folder structure

Keep these sibling folders together:

```
project/
  tb_audit/intake-spine.html  # ORIGINAL, untouched
  tb_m0/                      # Frozen M0 schema and validator
  tb_m1/                      # M1 SQLite outbox, receiver, client
  tb_m2/                      # M2 adapter, device HTTP, injected bridge, tests
```

## Run (from the project directory)

```bash
python -m pip install 'jsonschema>=4.18,<5'
# Terminal A: start local device first; the central receiver need NOT be running.
python tb_m2/device_server.py --db device.sqlite3 --port 8766 \
    --central-url http://127.0.0.1:8765
# Open http://127.0.0.1:8766/intake
# Fill age>=18, a synthetic location like DEMO-AREA-A, and symptoms;
# tick BOTH acknowledgements; press "Save case + draft summary".
# Terminal B: later, turn on the central receiver:
python tb_m1/server.py --db central.sqlite3 --port 8765
# Terminal C: safe manual retry of pending cases after connection returns:
python tb_m1/client.py --db device.sqlite3 --url http://127.0.0.1:8765 sync
```

Check local sync metadata (never a diagnosis):

```bash
python tb_m1/client.py --db device.sqlite3 status
```

The existing **Download** button now downloads the *M0-valid, locally persisted* case JSON using browser Blob APIs, not the old Claude-only API. The **Summary** button writes the case to local SQLite and attempts a best-effort sync to the central receiver; if remote is down the row remains `pending`. Summary is deterministic and non-diagnostic, has no LLM dependency, and never converts unknown fields into absent findings.

## M2 files and responsibilities

- `intake_adapter.py`: strict legacy-form submission → frozen M0 version `1.0.0` snapshot (revision 2, `ready_for_review`); calls the same combined `validate_or_raise()` used by M1. Never guesses consent, evidence, model identity, test time or ESR thresholds.
- `device_server.py`: localhost-only HTTP bridge. `GET /intake` serves unchanged original HTML with injected `/intake_bridge.js`; `POST /v1/intake` validates and enqueues; `POST /v1/sync` attempts M1 sync; `GET /v1/outbox` returns **metadata only**.
- `intake_bridge.js`: reads real original form input values, preserves untouched checkboxes as JSON `null`, captures explicit consent time, and intercepts the existing buttons. No styling changes.
- `test_m2.py`: Python unit + SQLite + real localhost HTTP contract integration tests.
- `test_browser_smoke.py`: optional real-Chromium test. Chromium is **blocked by the administrator in our execution environment**, so it is automatically skipped there rather than claimed as passed; run this test on your own machine.

## Boundary and handoff to M3

The legacy HTML asks for X-ray model flag/confidence but has no image reference, acquisition timestamp, or model identity. Its ESR field automatically applies an unsourced flat **20 mm/hr** threshold and has no lab reference-range provenance. **M2 disables these legacy controls and rejects programmatic `xray_available` or `esr_available` true.** Tests-upfront remains an M0 fixture and a working M1 transport path, but connecting *real* tests from the form is explicitly gated on M3's output adapter. When M3 is ready, integrate real `xray`/`esr` M0 blocks as provenance-bearing revisions of the **same case** instead of inventing values.

## Known gaps — do not use for clinical deployment

- No verified identities/roles, authentication, HTTPS, encryption at rest, real PHI handling, server-side consent attestation, real patient deduplication, post-submit edits, privacy/retention policy, revocation or device registration. Both HTTP servers bind **127.0.0.1**.
- Original symptom checkboxes are binary toggles. The bridge records **untouched as `null`**, checked as `true`, and explicitly changed back to unchecked as `false`. This is data-correct but awkward to express in the current UI; a later low-cost functional tri-state control is recommended **once the backend contract is stable**.
- No browser IndexedDB/service worker: if the device Python process is not running, **do not claim the browser can submit offline**.
- First successful case is frozen at revision 2. Edited re-submissions produce **409**, preserving the first case rather than overwriting it. Later corrections/ASHA/test returns require authorized future revision endpoints.
- The locally loaded legacy source still contains the unused Claude handler and unsourced ESR logic; the M2 injection intercepts its two buttons and disables test fields. The original file is not changed. A future UI cleanup can remove dead code without affecting the M0/M1 contract.
- External fonts in original page may be unavailable offline; no data path depends on them.

## Gate

```bash
cd project
python tb_m0/validate_cases.py
(cd tb_m1 && python -m unittest -v test_m1)
PYTHONPATH=tb_m1:tb_m2 python -m unittest -v tb_m2.test_m2
node --check tb_m2/intake_bridge.js
# Optional, run outside restricted Chromium container:
PYTHONPATH=tb_m1:tb_m2 python -m unittest -v tb_m2.test_browser_smoke
```

The core M2 gate is tests of real HTTP/SQLite flow, snapshot validation, preservation of explicit unknown vs false, consent + age + provenance rejection, offline retry, and repeat/modified submission semantics. A local human browser smoke test remains requested before treating M2 as integrated on your hardware.
