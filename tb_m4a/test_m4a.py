"""M4a review-and-routing contract tests. No UI, network or large model."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from contract import M0_DIR, validate_or_raise
from store import CentralReceiver, RevisionConflict
from review_engine import (CapacityRegistry, Principal, ReviewError, Site,
                           attach_pending_screening_route, review_case)

FIX = M0_DIR / 'fixtures'
S_ONLY = json.loads((FIX/'01-symptoms-only.json').read_text())
UPFRONT = json.loads((FIX/'02-tests-upfront.json').read_text())
VERIFIER = Principal('demo-verifier-1', 'verifier')
CLINICIAN = Principal('demo-clinician-1', 'clinician')
PHARM = Principal('demo-pharmacist-1', 'pharmacist')
T1 = '2026-09-20T02:15:00+05:30'
T2 = '2026-09-20T02:25:00+05:30'
T3 = '2026-09-20T02:35:00+05:30'
REGISTRY = CapacityRegistry([
    Site('DEMO-NAAT-LAB',frozenset({'diagnostic_testing'}),'DEMO-AREA-A',28,True,True),
    Site('DEMO-XRAY-VAN',frozenset({'additional_screening'}),'DEMO-AREA-A',45,True,True),
    Site('DEMO-OFFLINE-LAB',frozenset({'diagnostic_testing'}),'DEMO-AREA-A',10,False,True),
    Site('DEMO-REMOTE-LAB',frozenset({'diagnostic_testing'}),'DEMO-AREA-B',5,True,True),
])


def decide(case, action='intervention_required', principal=VERIFIER,
           site_id='DEMO-NAAT-LAB', requested_tests=(), when=T1, **kw):
    return review_case(case,principal=principal,expected_revision=case['revision'],
        decision=action,notes='A human reviewer chose this action based on this synthetic case.',
        requested_tests=requested_tests,site_id=site_id,registry=REGISTRY,when=when, **kw)

class M4aReview(unittest.TestCase):
    def test_direct_diagnostic_referral_without_optional_tests(self):
        updated=decide(S_ONLY)
        self.assertEqual(updated['case_status'],'routed_for_diagnostics')
        self.assertEqual(updated['revision'],3)
        self.assertIsNone(updated['diagnosis'])
        self.assertEqual(updated['diagnostic_tests'],[])
        self.assertFalse(updated['xray']['available'])
        self.assertEqual(updated['routes'][-1]['site_id'],'DEMO-NAAT-LAB')
        validate_or_raise(updated)

    def test_upfront_cxr_esr_no_auto_diagnosis(self):
        result=decide(UPFRONT)
        self.assertEqual(result['case_status'],'routed_for_diagnostics')
        self.assertIsNone(result['diagnosis'])
        self.assertEqual(result['esr'],UPFRONT['esr'])

    def test_pending_without_site_and_later_route_same_case(self):
        pending=decide(S_ONLY,'more_tests_needed',site_id=None,requested_tests=['xray'])
        self.assertEqual(pending['routes'],[])
        self.assertEqual(pending['case_status'],'pending_additional_test')
        routed=attach_pending_screening_route(pending,principal=VERIFIER,
                    expected_revision=pending['revision'],site_id='DEMO-XRAY-VAN',
                    registry=REGISTRY,when=T2)
        self.assertEqual(routed['case_id'],S_ONLY['case_id'])
        self.assertEqual(routed['case_status'],'pending_additional_test')
        self.assertEqual(routed['revision'],4)
        self.assertEqual(routed['routes'][-1]['purpose'],'additional_screening')
        validate_or_raise(routed)

    def test_pending_may_go_directly_for_diagnostics(self):
        pending=decide(S_ONLY,'more_tests_needed',site_id=None,requested_tests=['xray'])
        routed=decide(pending,when=T2)
        self.assertEqual(routed['case_status'],'routed_for_diagnostics')
        self.assertEqual(len(routed['review_history']),2)
        self.assertFalse(routed['xray']['available'])

    def test_no_referral_closed_without_treatment(self):
        closed=decide(S_ONLY,'not_required',site_id=None)
        self.assertEqual(closed['case_status'],'closed')
        self.assertIsNone(closed['diagnosis'])
        self.assertIsNone(closed['asha_assignment']['support_phase'])

    def test_role_rejected(self):
        with self.assertRaisesRegex(ReviewError,'trusted verifier'):
            decide(S_ONLY,principal=PHARM)

    def test_stale_revision_rejected(self):
        with self.assertRaisesRegex(ReviewError,'stale'):
            review_case(S_ONLY,principal=VERIFIER,expected_revision=1,decision='not_required',
                        notes='Synthetic reviewer judgment',when=T1)

    def test_missing_site_diagnostic_action_rejected(self):
        with self.assertRaisesRegex(ReviewError,'site'):
            decide(S_ONLY,site_id=None)

    def test_unavailable_capacity_rejected(self):
        with self.assertRaisesRegex(ReviewError,'not verified reachable'):
            decide(S_ONLY,site_id='DEMO-OFFLINE-LAB')

    def test_wrong_area_and_purpose_rejected(self):
        for sid in ('DEMO-REMOTE-LAB','DEMO-XRAY-VAN'):
            with self.subTest(site=sid), self.assertRaises(ReviewError):
                decide(S_ONLY,site_id=sid)

    def test_no_synthetic_screening_request_rejected(self):
        with self.assertRaises(ReviewError):
            decide(S_ONLY,'more_tests_needed',site_id=None)

    def test_no_esr_diagnostic_gate(self):
        without_esr=copy.deepcopy(S_ONLY)
        self.assertFalse(without_esr['esr']['available'])
        self.assertEqual(decide(without_esr)['case_status'],'routed_for_diagnostics')

    def test_pending_cannot_be_silently_closed(self):
        pending=decide(S_ONLY,'more_tests_needed',site_id=None,requested_tests=['esr'])
        with self.assertRaisesRegex(ReviewError,'pending additional'):
            decide(pending,'not_required',site_id=None,when=T2)

    def test_no_modified_original(self):
        original=copy.deepcopy(S_ONLY)
        decide(S_ONLY)
        self.assertEqual(S_ONLY,original)

    def test_date_order_rejected(self):
        with self.assertRaisesRegex(ReviewError,'predate'):
            decide(S_ONLY,when='2026-09-20T02:01:00+05:30')

    def test_close_no_route_and_diagnostic_no_tests(self):
        final=decide(S_ONLY,'not_required',site_id=None)
        self.assertEqual(final['routes'],[])
        self.assertEqual(final['diagnostic_tests'],[])

    def test_sqlite_revision_append_only_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=CentralReceiver(Path(tmp)/'central.sqlite3')
            db.ingest(S_ONLY)
            v3=decide(S_ONLY)
            self.assertEqual(db.ingest(v3)['result'],'stored')
            self.assertEqual(db.ingest(v3)['result'],'duplicate')
            self.assertEqual(db.revisions(S_ONLY['case_id']),[2,3])
            self.assertEqual(db.latest(S_ONLY['case_id'])['case_status'],'routed_for_diagnostics')
            with self.assertRaises(RevisionConflict):
                db.ingest(decide(S_ONLY,action='not_required',site_id=None))

    def test_registry_does_not_invent_nearest(self):
        self.assertEqual([s.site_id for s in REGISTRY.options('DEMO-AREA-A','diagnostic_testing')],
                         ['DEMO-NAAT-LAB'])
        self.assertEqual(REGISTRY.options('UNKNOWN','diagnostic_testing'),[])

if __name__=='__main__': unittest.main(verbosity=2)
