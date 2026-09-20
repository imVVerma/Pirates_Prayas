# Rural TB Detection & Continuity — Shared Team Doc

Paste this whole file into every sub-chat as shared context. It has three parts:
1. The frozen case-record schema (the contract between modules)
2. The task split across 5 build chats
3. The pitch fact-sheet (claims verified so far, with sources)

---

## 1. Frozen Case-Record Schema

This is the contract. If two modules disagree on field names or structure, that's the
first thing to catch at integration — not the last. Don't change field names without
flagging it to every chat.

```json
{
  "case_id": "string (uuid)",
  "created_at": "ISO 8601 timestamp",
  "status": "intake | pending_additional_test | ready_for_review | reviewed | routed | positive_confirmed | closed",

  "patient": {
    "demographics": {
      "age": "number",
      "sex": "string",
      "location": "string (village/area identifier)"
    }
  },

  "symptom_screen": {
    "cough_duration_days": "number | null",
    "fever": "boolean",
    "night_sweats": "boolean",
    "weight_loss": "boolean",
    "source": "voice | text",
    "raw_transcript": "string | null",
    "structured_at": "ISO 8601 timestamp"
  },

  "xray": {
    "available": "boolean",
    "image_ref": "string | null",
    "model_flag": "abnormal | normal | null",
    "model_confidence": "number 0-1 | null",
    "heatmap_ref": "string | null",
    "captured_at": "ISO 8601 timestamp | null"
  },

  "esr": {
    "available": "boolean",
    "value": "number | null",
    "flag": "elevated | normal | null",
    "captured_at": "ISO 8601 timestamp | null"
  },

  "case_summary": {
    "brief_text": "string | null",
    "generated_at": "ISO 8601 timestamp | null"
  },

  "verifier_decision": {
    "reviewer_id": "string | null",
    "decision": "intervention_required | not_required | more_tests_needed | null",
    "notes": "string | null",
    "decided_at": "ISO 8601 timestamp | null"
  },

  "routing": {
    "confirmatory_test_site": "string | null",
    "distance_or_eta": "string | null",
    "routed_at": "ISO 8601 timestamp | null"
  },

  "asha_assignment": {
    "asha_id": "string | null",
    "assigned_at": "ISO 8601 timestamp | null",
    "medicine_pickup_log": [
      { "scheduled_date": "date", "picked_up": "boolean", "logged_at": "ISO 8601 timestamp" }
    ]
  },

  "followups": [
    {
      "date": "ISO 8601 timestamp",
      "source": "voice | text",
      "raw_transcript": "string | null",
      "summary": "string",
      "trend": "improving | no_change | concerning"
    }
  ]
}
```

Build against **mock JSON matching this schema**, not against a live upstream module.
The integration chat's job is wiring real outputs into real inputs once every module
can produce/consume this shape.

---

## 2. Task Split (5 build chats + 1 verify track)

| # | Chat | Owns | Research question it resolves | Builds against |
|---|------|------|-------------------------------|-----------------|
| 1 | Voice/offline-LLM | WHO intake flow (text-first, voice stretch); STT/small-LLM benchmark | 1a | Outputs `symptom_screen` block |
| 2 | Sync/architecture | Store-and-forward sync layer (can be mocked) | 1b | Takes a full case JSON, "sends" it |
| 3 | X-ray + ESR | Pretrained CXR model integration, ESR threshold rule | 1d (teleradiology channel) | Mock `symptom_screen` in → `xray` + `esr` blocks out |
| 4 | Verifier dashboard + routing | Case-summary generator, capacity registry, fusion logic | 1e | Mock full case in → `verifier_decision` + `routing` out |
| 5 | ASHA/follow-up | Assignment, medicine pickup tracking, longitudinal summarization | — | Mock "positive" case in → `asha_assignment` + `followups` out |
| 6 | Pitch/verify (this doc) | Fact-checking claims, sourcing precedents, consent framing | 1c | Feeds the pitch script, not the build |

**Demo path:** build and rehearse **Branch B** (X-ray/ESR available at first contact,
single pass, no loop-back) as the primary live demo. Diagram **Branch A**'s loop-back
(verifier requests more tests → case returns to field → re-syncs) rather than building
the round-trip live — it's the most operationally complex part of the system and the
least demo-critical.

**Sync point:** freeze both the schema and the fact-sheet below together, at a set time
before the demo (e.g., 2 hours out), so the pitch narrative and the working demo say
the same thing.

---

## 3. Pitch Fact-Sheet (verified so far)

| Claim | Verified finding | Source | Use in pitch as |
|---|---|---|---|
| WHO 4-symptom screen accuracy | Does **not** meet WHO's own >90% sensitivity bar for an ideal screen. Real-world sensitivity ~79% overall (up to ~90% when limited to people already in clinical care); specificity as low as 38–50% in some subgroups. | WHO TB Knowledge Sharing Platform; PMC8590066 (Wykowski et al., 2021); PMC3629105 | Reason the design principle exists: screen triages, a human decides. Say this proactively. |
| A near-identical AI chest-X-ray pipeline already exists in India | PATH India deployed Qure.ai's qXR (AI chest X-ray reader) with SMS alerts triggering Truenat referral, Nagpur, Jan 2019–Feb 2020. 10,481 people referred, 197 diagnosed, 13% increase in case detection. | stoptb.org project report (PATH India / qXR) | Precedent to cite, not hide from. Differentiator: qXR is X-ray-only and stops at the alert; this system adds voice/offline symptom intake upstream of any X-ray, plus the full continuity loop (ASHA, adherence tracking). |
| A national case-management system already exists | Ni-Kshay portal under NTEP (National TB Elimination Programme) already tracks TB cases nationally; ASHA workers' TB duties are formally defined (mobilize presumptive patients, sample transport, treatment support, adherence follow-up). | NTEP official pages (ntep.in); The Wire coverage of ASHA/NTEP | Pre-empt "why not just use Ni-Kshay?" — answer: this system captures the informal first stop (pharmacist/dawa khana) that never generates a Ni-Kshay record, and can feed into it rather than replace it. |
| Mobile X-ray units are real infrastructure | Medanta's "TB-Free Haryana" campaign ran a mobile digital CXR van into rural Mewat district as a public-private partnership; cost of identifying one smear-negative TB case was ~US$32. | Springer/BMC Public Health, s12889-019-6421-1 | Real precedent for the "capacity registry" module — not a hypothetical. |
| Commercial teleradiology channels exist in India | Providers like 5C Network offer AI-assisted chest X-ray reads with ~15-minute average turnaround across Indian facilities; teleradiology for rural India has working examples dating back to 2007 (Bangalore–northeast India link). | 5cnetwork.com; Journal of Telemedicine and Telecare, 2010 | Resolves research stream 1d — cite as the channel rather than designing a radiologist-matching system from scratch. |

### Still open (lower priority, don't block the demo on these)
- Literature-sourced ESR threshold value for the TB adjunct-marker rule (needed for build item 3, not just the pitch).
- A sourced figure for "how often is X-ray/ESR unavailable at first contact" — currently asserted as "the common case" without a citation. Either find a number or soften the pitch language to "commonly reported, not precisely quantified."
- Consent/privacy model (research stream 1c) — still needs a one-paragraph committed answer for the pitch.
