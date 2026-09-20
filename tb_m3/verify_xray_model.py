"""Small local CHECKPOINT SMOKE TEST, not clinical validation or sensitivity estimate.

Usage (run in Python 3.11/3.12 with requirements-ml.txt):
 python verify_xray_model.py --model /path/tb_model.h5 --normal /path/known_normal.png \\
    --tb /path/known_tb.png --preprocessing auto --report verification.json

No model weights or images are downloaded or included. Known images must have
labels independently established and rights/consent to process locally.
"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from xray_adapter import load_local_h5, prepare_image, sha256_file, detect_pixel_range
from provenance import EvidenceError, number


def verify(model_file, normal_image, tb_image, preprocessing='auto'):
    model, sha = load_local_h5(model_file)
    declared = detect_pixel_range(model) if preprocessing == 'auto' else preprocessing
    if declared not in ('raw_0_255','zero_one'):
        raise EvidenceError('unknown preprocessing; inspect upstream sources')
    scores = []
    for image in (normal_image, tb_image):
        batch, _ = prepare_image(image, model, pixel_range=declared)
        import numpy as np
        raw = np.asarray(model.predict(batch, verbose=0))
        if raw.shape != (1,1):
            raise EvidenceError(f'expected scalar sigmoid output, got {raw.shape}')
        scores.append(number(float(raw[0,0]), 'raw score', minimum=0, maximum=1))
    if not scores[0] < scores[1]:
        raise EvidenceError('expected TB sigmoid score > normal score; label direction not verified')
    # Stronger 0.5 check for demo test examples; not a clinical performance claim.
    if not scores[0] < 0.5 <= scores[1]:
        raise EvidenceError('known sample scores do not straddle demo threshold 0.5; do NOT enable flags')
    return {
        'status': 'checkpoint_smoke_pass_only',
        'model_sha256': sha, 'preprocessing': declared,
        'label_mapping': 'class_1=TB_suggestive, class_0=normal_in_model',
        'known_normal_score': scores[0], 'known_tb_score': scores[1],
        'normal_image_sha256': sha256_file(normal_image),
        'tb_image_sha256': sha256_file(tb_image),
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'clinical_validation': False,
        'warning': 'Two samples do not establish accuracy, clinical benefit, calibrated probability, or WHO product approval.',
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', required=True)
    p.add_argument('--normal', required=True)
    p.add_argument('--tb', required=True)
    p.add_argument('--preprocessing', default='auto', choices=['auto','raw_0_255','zero_one'])
    p.add_argument('--report', required=True)
    args = p.parse_args()
    result = verify(args.model, args.normal, args.tb, args.preprocessing)
    path = Path(args.report)
    if path.exists():
        raise EvidenceError('refuse to overwrite prior smoke-test report')
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
