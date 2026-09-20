> From: https://claude.ai/chat/9e7c3204-d013-478d-8ae7-dbbf522c8dab?artifact=cf9723b2-52d3-479e-a942-336fa4209195

# you asked

message time: 2026-09-20 03:19:44

[text/markdown] tb-hackathon-project-spec.md

[text/markdown] tb-hackathon-team-doc.md

I'm building the sync layer for a TB detection hackathon project (context doc attached). Scope: a store-and-forward sync mechanism so a case created offline on a pharmacist's device reaches a central verifier queue whenever connectivity allows. This can be simulated/mocked for a 24-hour demo — the team just needs to agree on and demonstrate the model (e.g., local queue + opportunistic sync trigger). Build against a full mock case JSON matching the schema in the doc. Deliverable: a working (even if simulated) sync flow, and a one-paragraph explanation of the mechanism for the pitch.

---

# claude response

Here's a working simulated sync flow you can demo live: **[TB Case Sync Layer](https://claude.ai/artifact/SdnGXbEfYKTxtytYgJvjpG)**

What it does:
- **Create case (offline intake)** generates a mock case matching the frozen schema (demographics, symptom screen, optional X-ray/ESR blocks) and drops it straight into a local queue — this works with the connectivity toggle set to Offline, proving nothing blocks on a connection.
- The **connectivity toggle** simulates the pharmacist's device gaining signal. Flipping to Online arms a sync trigger that walks the local queue, marks each case `syncing`, then `synced`, and moves it into the central verifier queue panel — with staggered timing so multiple cases don't all land instantly.
- If you flip back to Offline mid-sync, an in-flight case reverts to `queued_locally` and logs an interruption, so the retry-on-failure behavior is visible, not just claimed.
- Click any case card to see its full JSON against the shared schema — useful for showing judges the module boundary is real, not hand-waved.
- The sync log at the bottom timestamps every transition, which doubles as a talk-track while you click through the demo.

One-paragraph mechanism explanation for the pitch:

> Every case created on the pharmacist's device is written to a local queue immediately and is fully functional offline — intake, structuring, and any available X-ray/ESR capture never wait on a network. A lightweight sync trigger checks connectivity opportunistically (on a timer, or on any detected signal change) and, when a connection exists, pushes queued cases one at a time to the central verifier queue; each case is marked `syncing` then `synced`, and if the connection drops mid-transfer the case reverts to queued and retries on the next window rather than being lost or duplicated. This is the same pattern offline-first health tools like CommCare/ODK use for field data collection in low-connectivity settings, so nothing here depends on inventing new sync infrastructure — the innovation is entirely upstream (voice intake, AI summarization) and downstream (ASHA continuity), not in this layer.

That last line is worth keeping in your back pocket if a judge asks why the sync layer looks "simple" — it's supposed to; boring and reliable is the right answer for store-and-forward, and citing CommCare/ODK precedent (same move your fact-sheet made for the X-ray pipeline) heads off the "did you build sync from scratch" question.