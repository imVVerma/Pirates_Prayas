import copy
import json
import unittest

from contract import M0_DIR, validate_or_raise
from asha_engine import Principal as APrincipal, assign_pre_diagnosis_navigation, assign_treatment_support, mark_treatment_started
from diagnostic_engine import Principal as DPrincipal, order_diagnostic_test, record_diagnostic_result, record_clinician_diagnosis
from followup_engine import FollowUpError, Principal, record_followup, record_medicine_pickup, schedule_followup, schedule_medicine_pickup
from review_engine import CapacityRegistry, Principal as RPrincipal, Site, review_case

FIX=M0_DIR/'fixtures'
S_ONLY=json.loads((FIX/'01-symptoms-only.json').read_text())
VERIFIER=RPrincipal('demo-verifier-1','verifier')
CLINICIAN=DPrincipal('demo-clinician-1','clinician')
LAB=DPrincipal('demo-lab-1','lab')
ASHA_ID='ASHA-01'
ASHA=Principal(ASHA_ID,'asha')
REGISTRY=CapacityRegistry([Site('DEMO-NAAT-LAB',frozenset({'diagnostic_testing'}),'DEMO-AREA-A',28,True,True)])
T1='2026-09-20T02:15:00+05:30'; T2='2026-09-20T02:20:00+05:30'; T3='2026-09-20T03:00:00+05:30'; T4='2026-09-20T04:00:00+05:30'; T5='2026-09-20T05:00:00+05:30'; T6='2026-09-20T06:00:00+05:30'; T7='2026-09-20T07:00:00+05:30'

def routed():
    c=review_case(S_ONLY,principal=VERIFIER,expected_revision=S_ONLY['revision'],decision='intervention_required',notes='Synthetic diagnostic referral.',site_id='DEMO-NAAT-LAB',registry=REGISTRY,when=T1)
    return assign_pre_diagnosis_navigation(c,principal=VERIFIER,expected_revision=c['revision'],asha_id=ASHA_ID,when=T2)

def treatment():
    c=review_case(S_ONLY,principal=VERIFIER,expected_revision=S_ONLY['revision'],decision='intervention_required',notes='Synthetic diagnostic referral.',site_id='DEMO-NAAT-LAB',registry=REGISTRY,when=T1)
    c=order_diagnostic_test(c,principal=CLINICIAN,expected_revision=c['revision'],test_type='xpert_ultra',lab_id='DEMO-NAAT-LAB',when=T2)
    tid=c['diagnostic_tests'][0]['test_id']
    c=record_diagnostic_result(c,principal=LAB,expected_revision=c['revision'],test_id=tid,result='positive',specimen_ref='synthetic://specimen/1',collected_at='2026-09-20T02:40:00+05:30',when=T3)
    c=record_clinician_diagnosis(c,principal=CLINICIAN,expected_revision=c['revision'],classification='bacteriologically_confirmed',supporting_test_ids=[tid],when=T4)
    c['diagnosis']['treatment_plan_confirmed']=True
    validate_or_raise(c)
    c=mark_treatment_started(c,principal=CLINICIAN,expected_revision=c['revision'],when=T5)
    return assign_treatment_support(c,principal=CLINICIAN,expected_revision=c['revision'],asha_id=ASHA_ID,when=T6)

class M5b(unittest.TestCase):
    def test_schedule_and_complete_navigation_followup(self):
        c=routed(); c=schedule_followup(c,principal=ASHA,expected_revision=c['revision'],kind='navigation',scheduled_at=T3,summary='Visit planned for sample collection support.')
        before=copy.deepcopy(c)
        out=record_followup(c,principal=ASHA,expected_revision=c['revision'],kind='navigation',summary='Helped arrange sample collection transport.',when=T4,trend='no_change')
        self.assertEqual(len(out['followups']),len(before['followups'])+1)
        self.assertTrue(out['followups'][-1]['summary'].startswith('Helped'))
        self.assertEqual(c,before)
        validate_or_raise(out)

    def test_treatment_followup_requires_treatment_support(self):
        c=routed()
        with self.assertRaisesRegex(FollowUpError,'treatment-support'):
            record_followup(c,principal=ASHA,expected_revision=c['revision'],kind='treatment',summary='Not allowed',when=T3)

    def test_only_assigned_asha_records_followup(self):
        c=routed(); wrong=Principal('ASHA-02','asha')
        with self.assertRaisesRegex(FollowUpError,'assigned ASHA'):
            record_followup(c,principal=wrong,expected_revision=c['revision'],kind='navigation',summary='Wrong worker',when=T3)

    def test_wrong_role_cannot_schedule_followup(self):
        c=routed(); pharmacist=Principal('pharmacy-1','pharmacist')
        with self.assertRaisesRegex(FollowUpError,'role is not allowed'):
            schedule_followup(c,principal=pharmacist,expected_revision=c['revision'],kind='navigation',scheduled_at=T3)

    def test_schedule_cannot_predate_assignment(self):
        c=routed()
        with self.assertRaisesRegex(FollowUpError,'before ASHA assignment'):
            schedule_followup(c,principal=ASHA,expected_revision=c['revision'],kind='navigation',scheduled_at=T1)

    def test_schedule_treatment_pickup(self):
        c=treatment(); out=schedule_medicine_pickup(c,principal=ASHA,expected_revision=c['revision'],scheduled_date='2026-09-21')
        self.assertEqual(out['asha_assignment']['medicine_pickup_log'][-1]['status'],'scheduled')
        validate_or_raise(out)

    def test_pickup_completion_is_append_only(self):
        c=treatment(); c=schedule_medicine_pickup(c,principal=ASHA,expected_revision=c['revision'],scheduled_date='2026-09-21')
        before=copy.deepcopy(c)
        out=record_medicine_pickup(c,principal=ASHA,expected_revision=c['revision'],scheduled_date='2026-09-21',status='picked_up',when=T7)
        self.assertEqual(before['asha_assignment']['medicine_pickup_log'][-1]['status'],'scheduled')
        self.assertEqual(out['asha_assignment']['medicine_pickup_log'][-2]['status'],'scheduled')
        self.assertEqual(out['asha_assignment']['medicine_pickup_log'][-1]['status'],'picked_up')
        self.assertEqual(c,before)
        validate_or_raise(out)

    def test_missed_pickup_auto_reschedules(self):
        c=treatment(); c=schedule_medicine_pickup(c,principal=ASHA,expected_revision=c['revision'],scheduled_date='2026-09-21')
        out=record_medicine_pickup(c,principal=ASHA,expected_revision=c['revision'],scheduled_date='2026-09-21',status='missed',when=T7,reschedule_date='2026-09-23')
        log=out['asha_assignment']['medicine_pickup_log']
        self.assertEqual(log[-2]['status'],'missed')
        self.assertEqual(log[-1],{'scheduled_date':'2026-09-23','status':'scheduled','logged_at':None})
        validate_or_raise(out)

    def test_duplicate_pickup_outcome_rejected(self):
        c=treatment(); c=schedule_medicine_pickup(c,principal=ASHA,expected_revision=c['revision'],scheduled_date='2026-09-21')
        c=record_medicine_pickup(c,principal=ASHA,expected_revision=c['revision'],scheduled_date='2026-09-21',status='picked_up',when=T7)
        with self.assertRaisesRegex(FollowUpError,'already recorded'):
            record_medicine_pickup(c,principal=ASHA,expected_revision=c['revision'],scheduled_date='2026-09-21',status='picked_up',when=T7)

    def test_stale_revision_rejected(self):
        c=routed(); c=schedule_followup(c,principal=ASHA,expected_revision=c['revision'],kind='navigation',scheduled_at=T3)
        with self.assertRaisesRegex(FollowUpError,'stale'):
            record_followup(c,principal=ASHA,expected_revision=c['revision']-1,kind='navigation',summary='stale',when=T4)

    def test_m5b_never_changes_case_status(self):
        c=routed(); original_status=c['case_status']
        c=schedule_followup(c,principal=ASHA,expected_revision=c['revision'],kind='navigation',scheduled_at=T3)
        c=record_followup(c,principal=ASHA,expected_revision=c['revision'],kind='navigation',summary='Completed',when=T4)
        self.assertEqual(c['case_status'],original_status)

if __name__=='__main__': unittest.main(verbosity=2)
