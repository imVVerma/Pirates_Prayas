> From: https://claude.ai/chat/2ba143e7-d840-4745-a03a-2232bd3f8f8a

# you asked

message time: 2026-09-20 03:23:18

I'm building the X-ray + ESR module for a TB detection hackathon project (context doc attached). Scope: integrate a pretrained TB chest X-ray model (Shenzhen/Montgomery/TBX11K-trained, don't train from scratch) that outputs an abnormality flag + confidence + heatmap if time allows, and a simple ESR threshold rule sourced from clinical literature (elevated ESR as a TB adjunct marker). Build against mock symptom_screen JSON matching the schema in the doc — don't wait on the intake module. Output must fill the "xray" and "esr" blocks of the case-record schema exactly as specified. Start by finding a usable pretrained model and an ESR threshold with a citation.

---

# claude response

No file actually came through — the uploads folder is empty. Since this project has moved from the pharmacist-triage concept to what sounds like a different track (X-ray + ESR diagnostic module, case-record schema, symptom_screen JSON), can you re-attach the context doc? In the meantime, I'll get started on research so we're not blocked.

The context doc didn't come through — the uploads folder is empty on my end, so I don't have the schema for `symptom_screen` or the case-record. I'll flag that at the end, but here's the research you asked for first.

## Pretrained X-ray model

**Recommendation: `Owos/tb-classifier` on Hugging Face**

- Architecture: InceptionV3 (ImageNet-pretrained backbone, fine-tuned) via `transformers`
- Trained on the Kaggle "Tuberculosis (TB) Chest X-ray Database" (3,500 normal / 700 TB-positive), which pools Montgomery, NIAID TB Portal, Belarus, and RSNA CXR data — same lineage as Shenzhen/Montgomery
- Reported eval: recall 0.984, precision 0.926, binary accuracy 0.986 (self-reported, not independently validated)
- Apache-2.0 license, loadable in ~5 lines with `AutoImageProcessor` / `AutoModelForImageClassification`, no training required
- Caveats worth stating in your writeup: no clinical validation, single-institution-style training data (Nigeria-focused deployment intent), so treat confidence as indicative, not diagnostic

**Why not the others I checked:**
- TBX11K's SymFormer (yun-liu/Tuberculosis) is the "proper" academic TBX11K-trained model with bounding-box localization, but it runs on mmdetection — heavy setup, GPU-dependent, not a 24hr-hackathon integration
- The Sivaramakrishnan-Rajaraman VGG16 papers report strong Shenzhen/Montgomery AUCs (~0.85–0.96) but the published repos ship the bone-suppression preprocessing weights, not a ready inference checkpoint for the classifier itself — you'd be reconstructing their pipeline from the paper

For the heatmap "if time allows," Grad-CAM on the InceptionV3's final conv block is a straightforward bolt-on (`pytorch-grad-cam` library) and is exactly the technique Owos's own reference project and the academic TB literature use for interpretability.

## ESR threshold

Two layers I'd bake into the rule, both literature-backed:

1. **Elevated ESR (nonspecific baseline)** — standard age/sex-adjusted normal limits (Westergren method): Men <50: ≤15 mm/hr, Men ≥50: ≤20 mm/hr, Women <50: ≤20 mm/hr, Women ≥50: ≤30 mm/hr. (Wikipedia summary of the Westergren reference convention; consistent across the clinical sources I checked.)
2. **Strongly suggestive of active TB** — ESR ≥100 mm/hr is specifically flagged in the TB literature as a marker associated with active pulmonary TB (particularly HIV-negative patients, mean ~102 mm/hr in one cohort study; a separate sputum-grade study found ESR rising with AFB smear grade, from ~28 mm/hr at scanty up to ~42 mm/hr at 3+). Source: very high erythrocyte sedimentation rate values of ≥100 mm/h are associated with tuberculosis and other chronic infective or inflammatory conditions (Levay & Viljoen, S Afr Med J 2005, on ESR in active TB).

So a simple three-tier rule: `normal` (below age/sex cutoff) → `elevated` (above cutoff, nonspecific) → `markedly_elevated` (≥100 mm/hr, adjunct signal for active TB per the cited literature). Worth noting for your slide: one pediatric TB study found ~33% of confirmed TB cases had normal ESR, so it should only ever be an adjunct/weight, never a gate — good defensive framing for judges asking about false negatives.

## What I need to build the actual module

To fill the `xray` and `esr` blocks exactly as specified and generate a valid mock `symptom_screen` JSON, I need the schema itself — field names, types, and how `xray`/`esr` nest into the case record. Can you re-attach the doc (or paste the relevant schema section)? Once I have it I'll write the mock JSON + the integration code (model loading, inference wrapper, ESR rule function, schema-conformant output) in one pass.

---

# you asked

message time: 2026-09-20 03:26:38

[text/markdown] AI-Solutions-for-ASHA-Workers.md

[text/markdown] tb-hackathon-project-spec.md

here are the context docs if they help

---

# claude response

Good — the spec actually clarifies something important: **the case-record JSON schema was never frozen in this doc.** Section 4 explicitly calls for the team to agree on it before splitting work, but only lists the conceptual fields (symptom answers, X-ray flag, ESR flag, etc.), not concrete types/keys. So "matching the schema in the doc" doesn't quite apply yet — I'll propose a concrete schema for just the `xray` and `esr` blocks (your chat's scope, per Section 4's "X-ray + ESR chat" assignment), and you can carry it into the integration chat.

Let me update the project note, then build.

Logic checks out. Now the X-ray model wrapper.

Now the mock `symptom_screen` generator and the module that assembles a full case record.

All three files work together end-to-end. Copying to outputs.

Ran the demo end-to-end against mock `symptom_screen` — output below is real, not illustrative.

**Three files:**
- `esr_rule.py` — age/sex-adjusted normal ranges + the ≥100 mm/hr "markedly elevated" TB-adjunct tier, both cited inline; tested against 5 cases including missing-value and fallback paths
- `tb_xray_model.py` — lazy-loading wrapper around `Owos/tb-classifier`, with an optional Grad-CAM heatmap path that degrades gracefully (returns `None` instead of crashing) if the library or layer name doesn't match
- `case_module.py` — the mock `symptom_screen` generator (WHO 4-symptom fields) and the function that assembles the `xray` + `esr` blocks into a case-record fragment

**Sample output** (no X-ray captured, ESR = 42 for a 26-year-old male):
```json
"esr": {
  "available": true,
  "value_mm_hr": 42,
  "reference_range_used": "Age/sex-adjusted Westergren upper limit for M age 26: <= 15 mm/hr",
  "flag": "elevated",
  ...
}
```

**Two things to flag before you run further:**

1. **This sandbox can't reach huggingface.co**, so `predict()` is syntax-checked but not exercised against the real model download. Before the demo: `pip install transformers torch pillow pytorch-grad-cam`, run one real image through it, and check `model.config.id2label` — HF model cards sometimes have unlabeled or swapped logits, and the Grad-CAM target layer name (`model.inception.Mixed_7c`) is a guess based on typical InceptionV3 attribute naming, not confirmed against this specific checkpoint's state dict.

2. **The case-record schema isn't frozen anywhere in the spec** — Section 4 says the team needs to agree on one but doesn't define it. I put a proposed schema in `case_module.py`'s docstring (just the `symptom_screen`/`xray`/`esr` shapes this module owns). Worth pasting that into the integration chat before the verifier-dashboard and ASHA chats build against assumptions that don't match.