from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tb_m0'))
sys.path.insert(0, str(ROOT / 'tb_m1'))
sys.path.insert(0, str(ROOT / 'tb_m2'))
sys.path.insert(0, str(ROOT / 'tb_m3'))
sys.path.insert(0, str(ROOT / 'tb_m4a'))

from contract import validate_or_raise
from review_engine import CapacityRegistry, Principal as ReviewPrincipal, Site, review_case
from screening_attach import attach_screening_tests
from diagnostic_engine import Principal as DiagnosticPrincipal, order_diagnostic_test, record_diagnostic_result, record_clinician_diagnosis
from asha_engine import Principal as ASHAPrincipal, confirm_treatment_plan, mark_treatment_started, assign_treatment_support
from followup_engine import Principal as FollowUpPrincipal, schedule_followup, schedule_medicine_pickup, record_medicine_pickup, record_followup

BASE = json.loads((ROOT / 'tb_m2' / 'canonical-case-output.json').read_text())
SMOKE = json.loads((ROOT / 'tb_m3' / 'reports' / 'smoke_test_report_20260920T002345Z.json').read_text())

VERIFIER = ReviewPrincipal('m6-verifier', 'verifier')
CLINICIAN = DiagnosticPrincipal('m6-clinician', 'clinician')
LAB = DiagnosticPrincipal('m6-lab', 'lab')
ASHA = ASHAPrincipal('ASHA-M6-01', 'asha')
REGISTRY = CapacityRegistry([Site('M6-DIAG-LAB', frozenset({'diagnostic_testing'}), 'DEMO-AREA-A', 10, True, True)])

T = [
    '2026-09-20T06:00:00+05:30', '2026-09-20T06:10:00+05:30',
    '2026-09-20T06:20:00+05:30', '2026-09-20T06:30:00+05:30',
    '2026-09-20T06:40:00+05:30', '2026-09-20T06:50:00+05:30',
    '2026-09-20T07:00:00+05:30', '2026-09-20T07:10:00+05:30',
    '2026-09-20T07:20:00+05:30', '2026-09-20T07:30:00+05:30',
    '2026-09-20T07:40:00+05:30', '2026-09-20T07:50:00+05:30',
]


def real_verified_xray_block():
    raw = SMOKE['steps']['preprocessing_cross_check']['raw_0_255']
    score = raw['tb']
    return {
        'available': True,
        'image_ref': 'verified://tb-positive.png',
        'model_flag': 'abnormal' if score >= 0.5 else 'normal',
        'model_confidence': score,
        'heatmap_ref': None,
        'model_id': 'verified-real-h5-smoke:raw_0_255',
        'captured_at': T[1],
    }


def make_case():
    c = copy.deepcopy(BASE)
    validate_or_raise(c)
    return c


class M6EndToEnd(unittest.TestCase):
    def test_full_patient_journey_preserves_identity_and_history(self):
        c0 = make_case()
        case_id = c0['case_id']
        revisions = [c0['revision']]

        # Intake -> human verifier requests X-ray + ESR.
        c = review_case(c0, principal=VERIFIER, expected_revision=c0['revision'],
                         decision='more_tests_needed', requested_tests=['xray', 'esr'],
                         notes='Synthetic M6 reviewer requests screening evidence.', when=T[0])
        revisions.append(c['revision'])
        self.assertEqual(c['case_status'], 'pending_additional_test')

        # Verified real-model X-ray artifact + synthetic ESR evidence return to same case.
        xray = real_verified_xray_block()
        esr = {
            'available': True, 'value': 42.0, 'flag': 'elevated',
            'reference_range_used': 'Synthetic reported reference 0-22 mm/h',
            'captured_at': T[2],
        }
        c = attach_screening_tests(c, xray=xray, esr=esr,
                                   actor_id='m6-pharmacist', actor_role='pharmacist', event_at=T[3])
        revisions.append(c['revision'])
        self.assertEqual(c['case_status'], 'ready_for_review')
        self.assertEqual(c['xray']['model_flag'], 'abnormal')
        self.assertAlmostEqual(c['xray']['model_confidence'], 0.984719455242157)

        # Critical boundary: abnormal screening evidence alone does not diagnose or route.
        self.assertIsNone(c['diagnosis'])
        self.assertEqual(len(c['routes']), 0)

        # Human verifier explicitly refers for diagnostics.
        c = review_case(c, principal=VERIFIER, expected_revision=c['revision'],
                         decision='intervention_required', notes='Synthetic human diagnostic referral.',
                         site_id='M6-DIAG-LAB', registry=REGISTRY, when=T[4])
        revisions.append(c['revision'])
        self.assertEqual(c['case_status'], 'routed_for_diagnostics')

        # Diagnostic order -> lab result -> explicit clinician diagnosis.
        c = order_diagnostic_test(c, principal=CLINICIAN, expected_revision=c['revision'],
                                  test_type='xpert_ultra', lab_id='M6-DIAG-LAB',
                                  specimen_ref='synthetic://m6/specimen-1', collected_at=T[5], when=T[5])
        revisions.append(c['revision'])
        test_id = c['diagnostic_tests'][0]['test_id']
        c = record_diagnostic_result(c, principal=LAB, expected_revision=c['revision'],
                                     test_id=test_id, result='positive',
                                     specimen_ref='synthetic://m6/specimen-1', collected_at=T[5], when=T[6])
        revisions.append(c['revision'])
        self.assertEqual(c['case_status'], 'diagnostic_result_available')
        c = record_clinician_diagnosis(c, principal=CLINICIAN, expected_revision=c['revision'],
                                       classification='bacteriologically_confirmed',
                                       supporting_test_ids=[test_id], when=T[7])
        revisions.append(c['revision'])
        self.assertEqual(c['case_status'], 'diagnosed')

        # Explicit care-plan confirmation + treatment initiation precede ASHA treatment support.
        c = confirm_treatment_plan(c, principal=CLINICIAN, expected_revision=c['revision'], when=T[8])
        revisions.append(c['revision'])
        c = mark_treatment_started(c, principal=CLINICIAN, expected_revision=c['revision'], when=T[8])
        revisions.append(c['revision'])
        c = assign_treatment_support(c, principal=CLINICIAN, expected_revision=c['revision'],
                                     asha_id=ASHA.actor_id, when=T[9])
        revisions.append(c['revision'])
        self.assertEqual(c['asha_assignment']['support_phase'], 'treatment_support')
        self.assertEqual(c['case_status'], 'diagnosed')

        # Continuity: scheduled pickup -> missed -> replacement pickup -> completed follow-up.
        c = schedule_medicine_pickup(c, principal=ASHA, expected_revision=c['revision'], scheduled_date='2026-09-22')
        revisions.append(c['revision'])
        c = record_medicine_pickup(c, principal=ASHA, expected_revision=c['revision'],
                                   scheduled_date='2026-09-22', status='missed', when=T[10],
                                   reschedule_date='2026-09-24')
        revisions.append(c['revision'])
        c = record_medicine_pickup(c, principal=ASHA, expected_revision=c['revision'],
                                   scheduled_date='2026-09-24', status='picked_up', when=T[11])
        revisions.append(c['revision'])
        c = schedule_followup(c, principal=ASHA, expected_revision=c['revision'], kind='treatment',
                              scheduled_at='2026-09-25T09:00:00+05:30', summary='Routine treatment-support follow-up')
        revisions.append(c['revision'])
        c = record_followup(c, principal=ASHA, expected_revision=c['revision'], kind='treatment',
                            summary='Treatment-support follow-up completed.', trend='improving',
                            when='2026-09-25T10:00:00+05:30')
        revisions.append(c['revision'])

        validate_or_raise(c)
        self.assertEqual(c['case_id'], case_id)
        self.assertEqual(revisions, list(range(c0['revision'], c['revision'] + 1)))
        self.assertEqual(c['case_status'], 'diagnosed')
        self.assertEqual(c['asha_assignment']['support_phase'], 'treatment_support')
        pickup = c['asha_assignment']['medicine_pickup_log']
        self.assertEqual([(x['scheduled_date'], x['status']) for x in pickup], [
            ('2026-09-22', 'scheduled'), ('2026-09-22', 'missed'),
            ('2026-09-24', 'scheduled'), ('2026-09-24', 'picked_up')
        ])
        self.assertEqual(c['followups'][-1]['kind'], 'treatment')
        self.assertEqual(len(c['status_history']), 7)

    def test_screening_signal_cannot_become_diagnosis(self):
        c = make_case()
        c = review_case(c, principal=VERIFIER, expected_revision=c['revision'],
                         decision='more_tests_needed', requested_tests=['xray'],
                         notes='Synthetic X-ray request.', when=T[0])
        c = attach_screening_tests(c, xray=real_verified_xray_block(), actor_id='m6-pharmacist',
                                   actor_role='pharmacist', event_at=T[2])
        validate_or_raise(c)
        self.assertIsNone(c['diagnosis'])
        self.assertEqual(c['case_status'], 'ready_for_review')


if __name__ == '__main__':
    unittest.main(verbosity=2)
