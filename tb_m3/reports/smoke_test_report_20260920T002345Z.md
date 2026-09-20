# M3 X-ray model smoke-test report — 2026-09-20T00:23:37.463606+00:00

**Final verdict: PASS**

## 1. Static H5 architecture inspection
- Rescaling layer present: True
- Verdict: FOUND an internal Rescaling layer with scale=0.00392156862745098. The model expects RAW pixel input (0-255 float, NOT pre-divided) -- the graph itself applies the 0.00392156862745098 scaling. Any caller that also divides by 255 before predict() (as predict.py and deployment/streamlit_deploy.py both do) will double-scale and degrade predictions. xray_adapter.preprocess_image() must NOT divide by 255 if this verdict holds.

## 2. Model load / shape check
- input_shape: (None, 300, 300, 3)
- output_shape: (None, 1)
- Mismatch: none

## 3. Preprocessing cross-check (separation between known-normal and known-TB scores)
- raw_0_255: normal=0.0246, tb=0.9847, separation=0.9601
- prescaled_0_1: normal=0.9897, tb=0.9907, separation=0.0010
- static (H5-architecture) verdict: raw_0_255
- empirical (separation) verdict: raw_0_255
- agreement: static and empirical evidence AGREE on 'raw_0_255' (separation 0.9601 vs 0.0010 for the other convention)

## 4. Label direction check
- preprocessing used: raw_0_255
- known-normal score: 0.0246
- known-TB score: 0.9847
- matches expected direction (normal<0.5<TB): True

## 5. Degenerate-input bias check (all-black / all-white / random noise, raw_0_255 convention)
- all_black: score=0.9901
- all_white: score=0.9952
- random_noise: score=0.9865

**Warning:** All-black, all-white, and random-noise inputs ALL score >0.9 (same range as a genuine TB-positive image). This model appears to default to 'abnormal' for anything that doesn't specifically match its narrow training distribution of normal chest X-rays, rather than genuinely recognizing TB-specific features. Expect false positives on any out-of-distribution input (wrong image type, unusual positioning, scanner artifacts, non-chest images). Treat model_flag='abnormal' as low-specificity, and never as confirmation of anything.
