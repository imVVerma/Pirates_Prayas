# Rural TB Detection & Continuity — Project Spec

## 0. One-line system description
A pharmacist/dawa khana worker runs a WHO-criteria voice screening with a patient (offline-capable), the system attaches any available X-ray/ESR hints, everything syncs to a qualified human verifier when connectivity allows, and — if confirmed positive — an ASHA worker is assigned and follow-up conversations are transcribed and summarized over time to track adherence and trajectory.

**Core design rule carried through every module: AI never decides "this is TB." AI structures, flags, and summarizes. A named qualified human decides whether intervention happens.**

---

## 1. RESEARCH STREAMS (assign each to its own chat)

These are open questions that need answers *before* the corresponding module can be built with confidence. Each is scoped tightly enough to hand to a separate chat/person.

### 1a. Offline voice/LLM stack feasibility
- What's the smallest model that can reliably do STT (speech-to-text) for Hindi/regional-language voice input on a low-end laptop or phone, offline, in real time?
- Candidates to evaluate: Whisper (small/base, quantized) for STT; a small quantized LLM (Llama 3.2 1B/3B, Gemma 2B, Phi-3 mini) for structuring the transcript into the WHO screening fields.
- Deliverable: a short benchmark — model size, RAM/CPU needed, accuracy on a few sample Hindi symptom conversations, and a go/no-go on whether full offline voice works in 24 hours, or whether the fallback should be offline text-only (pharmacist types/selects answers) with voice as a stretch goal.

### 1b. Store-and-forward sync architecture
- How does a locally-created case (screening summary + X-ray/ESR hints) get to the qualified verifier and, when needed, a remote radiologist, given intermittent/poor connectivity?
- Research: lightweight sync patterns used in existing offline-first health apps (e.g., how CommCare/ODK-style tools handle sync), compressed image transfer for low bandwidth, and what "available" actually needs to mean (SMS trigger + later data sync? opportunistic Wi-Fi/mobile sync when the pharmacist's phone gets signal?).
- Deliverable: a decision on the minimum viable sync mechanism for a 24-hour demo (can be simulated/mocked, but the team needs to agree on the model).

### 1c. Data privacy / consent framework
- Transcribing a patient's symptoms and follow-up conversations is sensitive health data. Research what a minimally responsible consent flow looks like (verbal consent captured before recording, what gets stored locally vs. synced, who can access a case).
- Note for the pitch: judges may ask about this directly — having a real answer (not an afterthought) is worth points on its own, separate from the tech.
- Deliverable: a one-paragraph consent/privacy model the team commits to and states explicitly in the pitch.

### 1d. Existing teleradiology channels in India
- Before designing a "dispatch a remote radiologist" flow from scratch, check whether an existing network (NHM teleradiology, private teleradiology services, state programs) already does this, so the team can cite it as the channel rather than reinventing a radiologist-matching system in a hackathon.
- Deliverable: either a real channel to reference in the pitch, or confirmation that this piece should be simulated/described as a "future integration," not built.

### 1e. Fusion logic for combining signals
- The qualified verifier will see: WHO symptom summary + (if available) X-ray model output + (if available) ESR flag. Research how existing screening protocols combine multiple weak signals (WHO's own guidance on combining CXR + symptom screening + adjunct markers) so the summary's confidence framing is evidence-based, not invented.
- Deliverable: a simple, citable scoring/priority logic (e.g., how many of the available signals point the same direction), not a new trained model.

---

## 2. CONCRETE / BUILD NOW (no open research question blocking these)

These can be started immediately in parallel, since the underlying logic is already established from prior research and doesn't depend on the research streams above resolving first.

1. **WHO 4-symptom structured intake form/flow** — the question set is public and validated; build the text-based version first (voice is 1a's job), output as structured JSON (cough duration, fever, night sweats, weight loss, plus basic demographics).
2. **Pretrained TB chest X-ray model integration** — use an existing open model or one fine-tuned on the public Shenzhen/Montgomery/TBX11K datasets. Do not train a new one from scratch; cite the model and dataset in the pitch. Output: abnormality flag + confidence + (if time allows) a heatmap image.
3. **ESR threshold rule** — a simple "above X → flag" rule sourced from the clinical literature (elevated ESR as a nonspecific TB adjunct marker), not a trained model.
4. **Case-summary generator** — an LLM call that takes the structured symptom JSON + X-ray flag + ESR flag and produces a short, readable brief for the qualified verifier. This is the one clearly "AI-adding-value" piece worth demoing well: unstructured/voice input in → clean clinical-style summary out.
5. **Capacity/routing registry** — seeded (fake but realistic) dataset of nearby labs/mobile X-ray units/PHCs with self-reported capacity status, plus the matching logic to route a verified case to the nearest available confirmatory-testing option.
6. **ASHA assignment + follow-up data model** — once a case is marked positive by the verifier, assign the nearest available (already-vetted) ASHA worker, and create a treatment tracking record (medicine pickup schedule, visit log).
7. **Longitudinal follow-up summarization** — each follow-up conversation gets transcribed (text-input MVP first, voice via 1a) and summarized; summaries are stored chronologically per patient so a trend ("improving" / "no change" / "concerning") can be shown to the verifier or ASHA supervisor over time.

---

## 3. PROTOTYPE SKELETON

```
[PHARMACIST APP — offline-capable]
   Voice/text intake (WHO screening) 
        -> local structuring (offline LLM)
        -> local case record created
        -> [optional] X-ray image captured/uploaded -> pretrained model runs locally or queues for sync
        -> [optional] ESR value entered -> threshold rule applied
        -> case-summary generated (structured JSON + brief text)
        -> QUEUED FOR SYNC (works even with zero connectivity)

[SYNC LAYER — store & forward]
   Whenever connectivity is available:
        -> case syncs to central review queue
        -> if remote radiologist channel needed, image routes there too

[QUALIFIED VERIFIER DASHBOARD]
   Reviews case summary + signals (symptom score, X-ray flag, ESR flag)
        -> decides: intervention needed? yes/no
        -> if yes: triggers confirmatory-test routing (nearest available capacity)
                   AND assigns nearest available ASHA worker

[ASHA / FOLLOW-UP MODULE]
   Medicine pickup tracking (missed pickup = signal, not a reminder ping)
        -> triggers ASHA check-in if pickup missed
   Periodic follow-up conversations
        -> transcribed -> summarized -> appended to patient's longitudinal record
        -> trend visible to verifier/supervisor over time
```

**What's explicitly AI, and how each piece is honestly framed:**
- Intake structuring: NLP task, real value, no training data needed (applies existing WHO rule).
- X-ray reading: borrowed pretrained model, cited, not claimed as your own training.
- ESR: not AI, a literature-sourced threshold.
- Case-summary generation: real AI value, structuring for a human decision-maker.
- Capacity routing: classical logistics, not ML.
- Follow-up summarization/trend: real AI value (long-context summarization), no training data needed for MVP.

---

## 4. DIVIDING WORK ACROSS CHATS, AND BRINGING IT BACK TOGETHER

**Suggested chat split**, each scoped to one module with a clear input/output contract:
1. Voice/offline-LLM chat → owns research 1a + build item 1 (and voice layer for item 7)
2. Sync/architecture chat → owns research 1b + the sync layer skeleton
3. X-ray + ESR chat → owns build items 2 + 3, plus research 1d if remote radiologist routing is attempted
4. Verifier dashboard + routing chat → owns build items 4 + 5 + research 1e
5. ASHA/follow-up chat → owns build items 6 + 7

**How to reconcile them into one working prototype:**
- Before splitting, agree on and freeze the **JSON schema** for a "case record" (the fields in the skeleton diagram above — symptom answers, X-ray flag, ESR flag, verifier decision, routing result, ASHA assignment, follow-up summaries). This schema is the contract between every chat's output — if two modules disagree on field names or structure, that's the first thing to catch in integration, not the last.
- Each sub-chat should build against **mock inputs/outputs matching that schema**, not against a live upstream module — e.g., the verifier dashboard chat can build against a fake case JSON without waiting for the voice-intake chat to actually produce one.
- Bring everything into a single integration chat only once each module can produce/consume the agreed schema; that chat's job is wiring the real outputs of one module into the real inputs of the next, and resolving whatever drifted (there will be some — that's normal, catch it here rather than the night before the demo).
- Paste this document's Section 3 skeleton into every sub-chat as shared context, so each one is building toward the same picture even when working independently.
