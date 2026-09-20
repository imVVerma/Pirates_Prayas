import copy
import json
import unittest

from contract import M0_DIR, validate_or_raise
from asha_engine import ASHAError, Principal, assign_pre_diagnosis_navigation, confirm_treatment_plan, mark_treatment_started, assign_treatment_support
from diagnostic_engine import Principal as DPrincipal, order_diagnostic_test, record_diagnostic_result, record_clinician_diagnosis
from review_engine import CapacityRegistry, Principal as ReviewPrincipal, Site, review_case

FIX=M0_DIR/'fixtures'
S_ONLY=json.loads((FIX/'01-symptoms-only.json').read_text())
VERIFIER=ReviewPrincipal('demo-verifier-1','verifier')
CLINICIAN=DPrincipal('demo-clinician-1','clinician')
LAB=DPrincipal('demo-lab-1','lab')
ASHA=Principal('demo-asha-coordinator','asha')
REGISTRY=CapacityRegistry([Site('DEMO-NAAT-LAB',frozenset({'diagnostic_testing'}),'DEMO-AREA-A',28,True,True)])
T1='2026-09-20T02:15:00+05:30'; T2='2026-09-20T02:20:00+05:30'; T3='2026-09-20T03:00:00+05:30'; T4='2026-09-20T04:00:00+05:30'; T5='2026-09-20T04:30:00+05:30'; T6='2026-09-20T05:00:00+05:30'

def routed():
    return review_case(S_ONLY,principal=VERIFIER,expected_revision=S_ONLY['revision'],decision='intervention_required',notes='Synthetic diagnostic referral.',site_id='DEMO-NAAT-LAB',registry=REGISTRY,when=T1)

def pending():
    return review_case(S_ONLY,principal=VERIFIER,expected_revision=S_ONLY['revision'],decision='more_tests_needed',requested_tests=['xray'],notes='Synthetic additional screening request.',when=T1)

def diagnosed():
    c=routed()
    c=order_diagnostic_test(c,principal=CLINICIAN,expected_revision=c['revision'],test_type='xpert_ultra',lab_id='DEMO-NAAT-LAB',when=T2)
    tid=c['diagnostic_tests'][0]['test_id']
    c=record_diagnostic_result(c,principal=LAB,expected_revision=c['revision'],test_id=tid,result='positive',specimen_ref='synthetic://specimen/1',collected_at='2026-09-20T02:40:00+05:30',when=T3)
    c=record_clinician_diagnosis(c,principal=CLINICIAN,expected_revision=c['revision'],classification='bacteriologically_confirmed',supporting_test_ids=[tid],when=T4)
    return c

class M5a(unittest.TestCase):
    def test_pre_diagnosis_navigation_after_referral(self):
        c=routed(); out=assign_pre_diagnosis_navigation(c,principal=VERIFIER,expected_revision=c['revision'],asha_id='ASHA-01',when=T2)
        self.assertEqual(out['asha_assignment']['support_phase'],'pre_diagnosis_navigation')
        self.assertEqual(out['case_status'],'routed_for_diagnostics')
        self.assertEqual(out['asha_assignment']['medicine_pickup_log'],[])
        validate_or_raise(out)

    def test_pre_diagnosis_navigation_after_more_tests(self):
        c=pending(); out=assign_pre_diagnosis_navigation(c,principal=VERIFIER,expected_revision=c['revision'],asha_id='ASHA-01',when=T2)
        self.assertEqual(out['asha_assignment']['support_phase'],'pre_diagnosis_navigation')

    def test_no_navigation_without_human_request(self):
        with self.assertRaisesRegex(ASHAError,'pending test request or diagnostic referral'):
            assign_pre_diagnosis_navigation(S_ONLY,principal=VERIFIER,expected_revision=S_ONLY['revision'],asha_id='ASHA-01',when=T1)

    def test_asha_cannot_assign_itself(self):
        c=routed()
        with self.assertRaises(ASHAError):
            assign_pre_diagnosis_navigation(c,principal=ASHA,expected_revision=c['revision'],asha_id='ASHA-01',when=T2)

    def test_diagnosis_does_not_enable_treatment_support(self):
        c=diagnosed(); c['diagnosis']['treatment_plan_confirmed']=True; validate_or_raise(c)
        with self.assertRaisesRegex(ASHAError,'treatment initiation'):
            assign_treatment_support(c,principal=CLINICIAN,expected_revision=c['revision'],asha_id='ASHA-01',when=T5)

    def test_treatment_support_requires_confirmed_plan(self):
        c=routed()
        c=order_diagnostic_test(c,principal=CLINICIAN,expected_revision=c['revision'],test_type='xpert_ultra',lab_id='DEMO-NAAT-LAB',when=T2)
        tid=c['diagnostic_tests'][0]['test_id']
        c=record_diagnostic_result(c,principal=LAB,expected_revision=c['revision'],test_id=tid,result='positive',specimen_ref='synthetic://specimen/1',collected_at='2026-09-20T02:40:00+05:30',when=T3)
        c=record_clinician_diagnosis(c,principal=CLINICIAN,expected_revision=c['revision'],classification='bacteriologically_confirmed',supporting_test_ids=[tid],when=T4)
        with self.assertRaisesRegex(ASHAError,'confirmed treatment plan'):
            mark_treatment_started(c,principal=CLINICIAN,expected_revision=c['revision'],when=T5)

    def test_treatment_plan_confirmation_is_revision_safe(self):
        c=diagnosed()
        before=c["revision"]
        out=confirm_treatment_plan(c,principal=CLINICIAN,expected_revision=c["revision"],when=T5)
        self.assertEqual(out["revision"], before+1)
        self.assertTrue(out["diagnosis"]["treatment_plan_confirmed"])
        self.assertTrue(out["diagnosis"]["full_course_treatment_decided"])
        self.assertEqual(out["case_status"], "diagnosed")
        validate_or_raise(out)

    def test_treatment_support_requires_actual_initiation(self):
        c=diagnosed(); c['diagnosis']['treatment_plan_confirmed']=True; validate_or_raise(c)
        with self.assertRaisesRegex(ASHAError,'treatment initiation'):
            assign_treatment_support(c,principal=CLINICIAN,expected_revision=c['revision'],asha_id='ASHA-01',when=T5)

    def test_full_treatment_support_flow(self):
        c=diagnosed()
        c['diagnosis']['treatment_plan_confirmed']=True
        validate_or_raise(c)
        c=mark_treatment_started(c,principal=CLINICIAN,expected_revision=c['revision'],when=T5)
        out=assign_treatment_support(c,principal=CLINICIAN,expected_revision=c['revision'],asha_id='ASHA-01',when=T6)
        self.assertEqual(out['asha_assignment']['support_phase'],'treatment_support')
        self.assertEqual(out['case_status'],'diagnosed')
        self.assertEqual(out['asha_assignment']['medicine_pickup_log'],[])
        validate_or_raise(out)

    def test_treatment_assignment_cannot_predate_initiation(self):
        c=diagnosed(); c['diagnosis']['treatment_plan_confirmed']=True; validate_or_raise(c)
        c=mark_treatment_started(c,principal=CLINICIAN,expected_revision=c['revision'],when=T5)
        with self.assertRaisesRegex(ASHAError,'predate'):
            assign_treatment_support(c,principal=CLINICIAN,expected_revision=c['revision'],asha_id='ASHA-01',when=T4)

    def test_assignment_is_append_only_snapshot_and_does_not_change_case_status(self):
        c=routed(); before=copy.deepcopy(c)
        out=assign_pre_diagnosis_navigation(c,principal=VERIFIER,expected_revision=c['revision'],asha_id='ASHA-01',when=T2)
        self.assertEqual(c,before)
        self.assertEqual(out['revision'],before['revision']+1)
        self.assertEqual(out['case_status'],before['case_status'])

    def test_second_assignment_rejected(self):
        c=routed(); c=assign_pre_diagnosis_navigation(c,principal=VERIFIER,expected_revision=c['revision'],asha_id='ASHA-01',when=T2)
        with self.assertRaisesRegex(ASHAError,'already exists'):
            assign_pre_diagnosis_navigation(c,principal=VERIFIER,expected_revision=c['revision'],asha_id='ASHA-02',when=T3)

    def test_stale_revision_rejected(self):
        c=routed()
        with self.assertRaisesRegex(ASHAError,'stale'):
            assign_pre_diagnosis_navigation(c,principal=VERIFIER,expected_revision=c['revision']-1,asha_id='ASHA-01',when=T2)

    def test_treatment_support_only_clinician(self):
        c=diagnosed(); c['diagnosis']['treatment_plan_confirmed']=True; validate_or_raise(c)
        c=mark_treatment_started(c,principal=CLINICIAN,expected_revision=c['revision'],when=T5)
        with self.assertRaises(ASHAError):
            assign_treatment_support(c,principal=ASHA,expected_revision=c['revision'],asha_id='ASHA-01',when=T6)

if __name__=='__main__': unittest.main(verbosity=2)
