import copy
import json
import unittest
from pathlib import Path

from contract import M0_DIR, validate_or_raise
from diagnostic_engine import (DiagnosticError, Principal,
                               order_diagnostic_test, record_diagnostic_result,
                               record_clinician_diagnosis)
from review_engine import CapacityRegistry, Principal as ReviewPrincipal, Site, review_case

FIX = M0_DIR / 'fixtures'
S_ONLY = json.loads((FIX/'01-symptoms-only.json').read_text())
VERIFIER = ReviewPrincipal('demo-verifier-1', 'verifier')
CLINICIAN = Principal('demo-clinician-1', 'clinician')
LAB = Principal('demo-lab-1', 'lab')
REGISTRY = CapacityRegistry([Site('DEMO-NAAT-LAB', frozenset({'diagnostic_testing'}), 'DEMO-AREA-A', 28, True, True)])
T1='2026-09-20T02:15:00+05:30'; T2='2026-09-20T02:20:00+05:30'; T3='2026-09-20T03:00:00+05:30'; T4='2026-09-20T04:00:00+05:30'


def routed_case():
    return review_case(S_ONLY, principal=VERIFIER, expected_revision=S_ONLY['revision'],
                       decision='intervention_required', notes='Synthetic reviewer referral.',
                       site_id='DEMO-NAAT-LAB', registry=REGISTRY, when=T1)

class M4bDiagnostic(unittest.TestCase):
    def test_order_diagnostic_test(self):
        case=routed_case()
        out=order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                                  test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)
        self.assertEqual(out['case_status'],'routed_for_diagnostics')
        self.assertEqual(out['diagnostic_tests'][0]['result'],'pending')
        self.assertEqual(out['revision'],case['revision']+1)
        validate_or_raise(out)

    def test_lab_result_transitions_case(self):
        case=routed_case()
        ordered=order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                                      test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)
        tid=ordered['diagnostic_tests'][0]['test_id']
        result=record_diagnostic_result(ordered, principal=LAB, expected_revision=ordered['revision'],
                                        test_id=tid, result='positive', specimen_ref='synthetic://specimen/1', collected_at='2026-09-20T02:40:00+05:30', when=T3)
        self.assertEqual(result['case_status'],'diagnostic_result_available')
        self.assertEqual(result['diagnostic_tests'][0]['result'],'positive')
        self.assertEqual(result['routes'][-1]['status'],'completed')
        validate_or_raise(result)

    def test_positive_result_can_be_bacteriologically_confirmed(self):
        case=routed_case()
        ordered=order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                                      test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)
        tid=ordered['diagnostic_tests'][0]['test_id']
        result=record_diagnostic_result(ordered, principal=LAB, expected_revision=ordered['revision'],
                                        test_id=tid, result='positive', specimen_ref='synthetic://specimen/1', collected_at='2026-09-20T02:40:00+05:30', when=T3)
        diagnosed=record_clinician_diagnosis(result, principal=CLINICIAN, expected_revision=result['revision'],
                                             classification='bacteriologically_confirmed', supporting_test_ids=[tid], when=T4)
        self.assertEqual(diagnosed['case_status'],'diagnosed')
        self.assertEqual(diagnosed['diagnosis']['classification'],'bacteriologically_confirmed')
        self.assertFalse(diagnosed['diagnosis']['treatment_plan_confirmed'])
        self.assertIsNone(diagnosed['asha_assignment']['asha_id'])
        validate_or_raise(diagnosed)

    def test_negative_result_cannot_be_bacteriological_confirmation(self):
        case=routed_case()
        ordered=order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                                      test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)
        tid=ordered['diagnostic_tests'][0]['test_id']
        result=record_diagnostic_result(ordered, principal=LAB, expected_revision=ordered['revision'],
                                        test_id=tid, result='negative', specimen_ref='synthetic://specimen/2', collected_at='2026-09-20T02:40:00+05:30', when=T3)
        with self.assertRaisesRegex(DiagnosticError,'positive supporting test'):
            record_clinician_diagnosis(result, principal=CLINICIAN, expected_revision=result['revision'],
                                       classification='bacteriologically_confirmed', supporting_test_ids=[tid], when=T4)

    def test_negative_result_can_support_explicit_clinical_diagnosis(self):
        case=routed_case()
        ordered=order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                                      test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)
        tid=ordered['diagnostic_tests'][0]['test_id']
        result=record_diagnostic_result(ordered, principal=LAB, expected_revision=ordered['revision'],
                                        test_id=tid, result='negative', specimen_ref='synthetic://specimen/2', collected_at='2026-09-20T02:40:00+05:30', when=T3)
        diagnosed=record_clinician_diagnosis(result, principal=CLINICIAN, expected_revision=result['revision'],
                                             classification='clinically_diagnosed', supporting_test_ids=[tid],
                                             clinical_rationale='Synthetic clinician review supports a clinical diagnosis despite the negative rapid test.', full_course_treatment_decided=True, treatment_plan_confirmed=True, when=T4)
        self.assertEqual(diagnosed['case_status'],'diagnosed')
        self.assertEqual(diagnosed['diagnosis']['classification'],'clinically_diagnosed')

    def test_indeterminate_result_requires_clinician_review(self):
        case=routed_case()
        ordered=order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                                      test_type='truenat', lab_id='DEMO-NAAT-LAB', when=T2)
        tid=ordered['diagnostic_tests'][0]['test_id']
        result=record_diagnostic_result(ordered, principal=LAB, expected_revision=ordered['revision'],
                                        test_id=tid, result='indeterminate', specimen_ref='synthetic://specimen/3', collected_at='2026-09-20T02:40:00+05:30', when=T3)
        with self.assertRaises(DiagnosticError):
            record_clinician_diagnosis(result, principal=CLINICIAN, expected_revision=result['revision'],
                                       classification='bacteriologically_confirmed', supporting_test_ids=[tid], when=T4)

    def test_result_cannot_be_overwritten(self):
        case=routed_case()
        ordered=order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                                      test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)
        tid=ordered['diagnostic_tests'][0]['test_id']
        result=record_diagnostic_result(ordered, principal=LAB, expected_revision=ordered['revision'],
                                        test_id=tid, result='positive', specimen_ref='synthetic://specimen/1', collected_at='2026-09-20T02:40:00+05:30', when=T3)
        with self.assertRaisesRegex(DiagnosticError,'already recorded'):
            record_diagnostic_result(result, principal=LAB, expected_revision=result['revision'],
                                     test_id=tid, result='negative', when=T4)

    def test_untrusted_roles_rejected(self):
        case=routed_case()
        with self.assertRaises(DiagnosticError):
            order_diagnostic_test(case, principal=Principal('demo-pharm','pharmacist'),
                                  expected_revision=case['revision'], test_type='xpert_ultra',
                                  lab_id='DEMO-NAAT-LAB', when=T2)

    def test_stale_revision_rejected(self):
        case=routed_case()
        with self.assertRaisesRegex(DiagnosticError,'stale'):
            order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision']-1,
                                  test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)

    def test_original_unchanged(self):
        case=routed_case(); before=copy.deepcopy(case)
        order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                              test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)
        self.assertEqual(case,before)

    def test_diagnosis_does_not_start_treatment_or_assign_asha(self):
        case=routed_case()
        ordered=order_diagnostic_test(case, principal=CLINICIAN, expected_revision=case['revision'],
                                      test_type='xpert_ultra', lab_id='DEMO-NAAT-LAB', when=T2)
        tid=ordered['diagnostic_tests'][0]['test_id']
        result=record_diagnostic_result(ordered, principal=LAB, expected_revision=ordered['revision'],
                                        test_id=tid, result='positive', specimen_ref='synthetic://specimen/1', collected_at='2026-09-20T02:40:00+05:30', when=T3)
        diagnosed=record_clinician_diagnosis(result, principal=CLINICIAN, expected_revision=result['revision'],
                                             classification='bacteriologically_confirmed', supporting_test_ids=[tid], when=T4)
        self.assertFalse(diagnosed['diagnosis']['full_course_treatment_decided'])
        self.assertFalse(diagnosed['diagnosis']['treatment_plan_confirmed'])
        self.assertIsNone(diagnosed['diagnosis']['treatment_started_at'])
        self.assertIsNone(diagnosed['asha_assignment']['asha_id'])

if __name__=='__main__': unittest.main(verbosity=2)
