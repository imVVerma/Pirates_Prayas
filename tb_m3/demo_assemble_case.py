"""Generate exactly one SYNTHETIC M0-compatible screening revision from M2.

Does not run a real chest-X-ray model or forge a positive model output.
Example from parent directory:
  python tb_m3/demo_assemble_case.py --out /tmp/m3-synthetic-case.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'tb_m0'))
sys.path.insert(0, str(ROOT.parent / 'tb_m1'))
from screening_attach import attach_screening_tests
from esr_adapter import make_esr
from contract import validate_or_raise


def demo_case():
    base = json.loads((ROOT.parent / 'tb_m2' / 'canonical-case-output.json').read_text())
    # A synthetic image exists as a traceable reference, but NO AI model has run.
    xray = {
        'available': True, 'image_ref': 'synthetic://cxr/M3-DEMO',
        'model_flag': None, 'model_confidence': None,
        'heatmap_ref': None, 'model_id': None,
        'captured_at': '2026-09-20T04:30:00+05:30',
    }
    esr = make_esr(value_mm_hr=42, captured_at='2026-09-20T04:32:00+05:30',
                   lab_report_ref='SYNTHETIC-LAB-42', upper_limit_mm_hr=22,
                   lab_reference_description='synthetic lab reference 0-22 mm/h')
    result = attach_screening_tests(base, xray=xray, esr=esr,
                                    actor_id='demo-pharmacist-1', actor_role='pharmacist')
    validate_or_raise(result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='destination synthetic JSON path')
    args = parser.parse_args()
    target = Path(args.out)
    if target.exists():
        parser.error('output exists; refuse to overwrite it')
    target.write_text(json.dumps(demo_case(), indent=2, ensure_ascii=False) + '\n')
    print(f'Wrote synthetic M0-valid revision to {target}')
