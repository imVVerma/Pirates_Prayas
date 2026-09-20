# Copy/paste prompt for parallel visual/interaction design (M7.3)

You are designing the **field worker interface**, not the clinician/reviewer workbench, for a synthetic-only adult (18+) TB screening and continuity prototype. The backend M0–M6.5 and M7 clinical workbench already exist. You are receiving the latest **M7.3 ZIP**; please **open and modify only these two files**:

- `tb_app/field_intake.html` — responsive one-question-at-a-time worker intake. Update HTML copy, CSS, labels, arrangement within each step, and focus/spacing/accessibility as needed.
- `tb_app/field_cases.html` — simple worker-facing saved/sent/review statuses. Update HTML/CSS/layout/accessibility only.

Do **not** edit `tb_app/field_intake.js`, `tb_app/field_cases.js`, `tb_app/server.py`, `tb_m2/intake_adapter.py`, `tb_app/workflow.py`, `tb_app/app_sync.js`, `tb_m0/case-schema.json`, any database or clinical files, or the existing `intake-spine.html` and `tb-sync-layer.html`. Please don't build another mock backend or a disconnected React prototype.

**Preserve the frontend contract.** Keep the `/field_intake.js` and `/field_cases.js` script tags. Keep all existing element IDs and radio-group names, all `<section class="step" id="step-...">` panels, option values, `hidden` functionality, `data-en`/`data-hi` attributes, and form input types; the JS selects these. Keep `#feedback`, `#progress`, `#bar`, `#preview`, `#voiceStatus`, `#doneMessage`, `#next`, `#back`, `#retry`, `#refresh`, `#cards`, `#notice`, and the synthetic-only warning. If you need a behavior change, document it separately; do not implement it by renaming elements.

**User experience:** design for low-literacy/low-bandwidth rural pharmacist/PHC worker, mobile first (320–390px and 768px), 18px+ body text, big touch targets, uncluttered single task per screen, direct Hindi/English labels (have a Hindi speaker proofread), back/progress/save feedback, editable typed or speech-transcribed narrative, and explicit Yes / No / Don't know choices. Keep the distinction between a worker's **claim that a report is available** and a verified X-ray/ESR result, which cannot be created here. Keep review-and-confirm, explicit consent, age >=18, and synthetic-data-only messaging. Leave real address/patient entry disabled in this demonstration. Do not imply clinical diagnosis, validated AI extraction, actual browser-only offline operation, or real sign-in/role security. Voice support varies by browser/network; typing is always the fallback.

**Deliverables:** two edited HTML files only, plus optional screenshots of English intake, Hindi intake and saved cases at mobile width. List every behavior/ID change you believe is essential so the integration engineer can decide explicitly. Do not import remote fonts, CDNs, component libraries, images, plugins or other runtime dependencies.

**Acceptance after design handoff:** run `python -m unittest discover -s tb_app -p test_field_contract.py` from the extracted project root, then manually walk the wizard at mobile width. Keep all selectors stable; a failed contract test is a required integration fix, not permission to edit the backend.
