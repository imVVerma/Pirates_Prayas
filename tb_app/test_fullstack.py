"""Real localhost HTTP/SQLite integration against both app processes, synthetic only."""
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

class DemoTestHTTP(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # An offline/timeout test can abandon queued TCP connections.
        # Expected broken-pipe on later restart is not a clinical action failure.
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        return super().handle_error(request, client_address)
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from uuid import uuid4
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tb_m1'))
sys.path.insert(0,str(ROOT/'tb_m2'))
sys.path.insert(0,str(ROOT/'tb_app'))
from server import central_handler,device_handler
from store import CentralReceiver,LocalOutbox
from contract import check_next,validate_or_raise


def request(url, data=None):
    r=Request(url,data=json.dumps(data).encode() if data is not None else None,
              headers={'Content-Type':'application/json'} if data is not None else {},
              method='POST' if data is not None else 'GET')
    try:
        with urlopen(r,timeout=8) as h:
            body=h.read()
            if h.headers.get_content_type()=='application/json':
                return h.status,json.loads(body)
            return h.status,body.decode()
    except HTTPError as exc:
        return exc.code,json.loads(exc.read())

class FullStackHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='tb-m7-')
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.local=LocalOutbox(base/'local.sqlite3')
        self.central=CentralReceiver(base/'central.sqlite3')
        self.remote=DemoTestHTTP(('127.0.0.1',0),central_handler(self.central))
        self.remote.daemon_threads=True
        self.remote_url=f'http://127.0.0.1:{self.remote.server_port}'
        self.device=DemoTestHTTP(('127.0.0.1',0),device_handler(self.local,self.remote_url))
        self.device.daemon_threads=True
        self.url=f'http://127.0.0.1:{self.device.server_port}'
        self.threads=[]
        t=threading.Thread(target=self.device.serve_forever,daemon=True);t.start();self.threads.append(t)
        self.addCleanup(self.close_servers)

    def close_servers(self):
        for s in (self.device,self.remote):
            s.shutdown();s.server_close()
        for t in self.threads:t.join(timeout=3)

    def bring_online(self):
        t=threading.Thread(target=self.remote.serve_forever,daemon=True);t.start();self.threads.append(t)

    def new_case(self):
        at=datetime.now(timezone.utc).isoformat()
        return {'case_id':str(uuid4()),'created_at':at,'consent_recorded_at':at,
                'consent_confirmed':True,'synthetic_acknowledged':True,'age':36,
                'sex':'female','location':'DEMO-AREA-A','cough_duration_days':14,
                'fever':True,'night_sweats':None,'weight_loss':False,
                'xray_available':False,'esr_available':False}

    def act(self,case,action,**kwargs):
        status,body=request(self.url+f'/v1/dashboard/cases/{case["case_id"]}/actions',
                            {'expected_revision':case['revision'],'action':action,**kwargs})
        self.assertEqual(status,201,f'{action}: {body}')
        newer=body['case']
        check_next(case,newer)
        validate_or_raise(newer)
        return newer

    def test_real_http_pages_outage_and_complete_care_journey(self):
        for path in ('/intake','/sync','/intake_bridge.js','/app_sync.js'):
            code,html=request(self.url+path)
            self.assertEqual(code,200,path)
            self.assertNotIn('mockCase()',html if path=='/sync' else '')
            if path=='/sync':
                self.assertIn('caseWorkbench',html)
                self.assertIn('/app_sync.js',html)
            if path=='/intake':self.assertIn('/intake_bridge.js',html)
        raw=self.new_case()
        status,saved=request(self.url+'/v1/intake',raw)
        self.assertEqual(status,201,saved)
        case=saved['case']
        self.assertEqual(case['revision'],2)
        self.assertEqual(self.local.status()[0]['sync_status'],'pending')
        self.assertEqual(request(self.url+'/v1/dashboard/cases')[0],503)
        status,sync=request(self.url+'/v1/sync',{})
        self.assertEqual(status,200)
        self.assertEqual(sync['outcomes'][0]['status'],'retry_later')
        self.assertEqual(self.local.status()[0]['sync_status'],'pending')
        self.bring_online()
        status,sync=request(self.url+'/v1/sync',{})
        self.assertEqual(status,200,sync)
        self.assertEqual(self.local.status()[0]['sync_status'],'acked')
        code,display=request(self.url+'/v1/dashboard/cases/'+case['case_id'])
        self.assertEqual(code,200)
        self.assertEqual(display['view']['current_stage'],'needs_review')
        # Human review and optional screening loop (M4a, M3) plus diagnostic branch.
        case=self.act(case,'review',decision='more_tests_needed',notes='More evidence requested.',
                      requested_tests=['xray','esr'])
        self.assertEqual(case['case_status'],'pending_additional_test')
        case=self.act(case,'xray_capture',image_ref='DEMO-XRAY-0001')
        self.assertIsNone(case['xray']['model_flag'])
        self.assertEqual(case['case_status'],'pending_additional_test')
        case=self.act(case,'esr_result',value=42,lab_upper_limit=22,
                      reference_source='DEMO-LAB-REF')
        self.assertEqual(case['case_status'],'ready_for_review')
        self.assertEqual(case['esr']['flag'],'elevated')
        self.assertIsNone(case['diagnosis'])
        # No automatic referral/diagnosis from CXR or ESR.
        case=self.act(case,'review',decision='intervention_required',
                      notes='Human explicitly requests confirmatory testing.',
                      site_id='DEMO-LAB-01',requested_tests=[])
        case=self.act(case,'diagnostic_order',test_type='xpert_mtb_rif',specimen_ref='DEMO-SPEC-01',specimen_collected=True)
        test_id=case['diagnostic_tests'][-1]['test_id']
        case=self.act(case,'diagnostic_result',test_id=test_id,result='positive')
        self.assertIsNone(case['diagnosis'])
        case=self.act(case,'diagnosis',classification='bacteriologically_confirmed',
                      supporting_test_ids=[test_id],clinical_rationale='',
                      full_course_treatment_decided=False,treatment_plan_confirmed=False)
        self.assertIsNone(case['diagnosis']['treatment_started_at'])
        case=self.act(case,'confirm_plan')
        case=self.act(case,'start_treatment')
        case=self.act(case,'treatment_support',asha_id='demo-asha-01')
        due=datetime.now(timezone.utc).date().isoformat()
        case=self.act(case,'pickup_schedule',scheduled_date=due)
        from datetime import timedelta
        later=(datetime.now(timezone.utc).date()+timedelta(days=3)).isoformat()
        case=self.act(case,'pickup_result',scheduled_date=due,status='missed',reschedule_date=later)
        case=self.act(case,'followup',kind='treatment',summary='Synthetic follow-up after missed pickup.',trend='no_change')
        self.assertEqual(self.central.latest(case['case_id']),case)
        self.assertEqual(len(self.central.revisions(case['case_id'])),case['revision']-1)
        code,latest=request(self.url+'/v1/dashboard/cases/'+case['case_id'])
        self.assertEqual(code,200)
        self.assertEqual(latest['view']['current_stage'],'treatment_follow_up')
        self.assertEqual(latest['view']['alerts'][0]['type'],'missed_pickup')
        self.assertEqual(latest['view']['asha']['next_action']['due'],later)
        self.assertEqual(len(self.local.status()),1) # central actions do not duplicate device rows
        # Explicit stale-write rejection.
        code,bad=request(self.url+f'/v1/dashboard/cases/{case["case_id"]}/actions',
                         {'action':'followup','expected_revision':2,'kind':'treatment','summary':'bad'})
        self.assertEqual(code,422,bad)

    def test_symptoms_only_direct_referral_without_xray_or_esr(self):
        """Optional screening cannot become an implicit diagnostic prerequisite."""
        self.bring_online()
        raw = self.new_case()
        status, saved = request(self.url + '/v1/intake', raw)
        self.assertEqual(status, 201, saved)
        case = saved['case']
        self.assertEqual(request(self.url + '/v1/sync', {})[0], 200)
        case = self.act(case, 'review', decision='intervention_required',
                        notes='Synthetic human referral from symptom review alone.',
                        site_id='DEMO-LAB-01', requested_tests=[],
                        actor_id='forged-browser-clinician', actor_role='clinician')
        self.assertEqual(case['review_history'][-1]['reviewer_id'], 'demo-verifier-1')
        self.assertEqual(case['case_status'], 'routed_for_diagnostics')
        self.assertFalse(case['xray']['available'])
        self.assertFalse(case['esr']['available'])
        self.assertIsNone(case['diagnosis'])
        case = self.act(case, 'diagnostic_order', test_type='xpert_ultra',
                        specimen_ref='DEMO-SPEC-DIRECT', specimen_collected=True)
        self.assertIsNone(case['diagnosis'])
        test_id = case['diagnostic_tests'][-1]['test_id']
        case = self.act(case, 'diagnostic_result', test_id=test_id, result='negative')
        self.assertIsNone(case['diagnosis'])
        code, error = request(self.url + f'/v1/dashboard/cases/{case["case_id"]}/actions', {
            'expected_revision':case['revision'], 'action':'diagnosis',
            'classification':'bacteriologically_confirmed',
            'supporting_test_ids':[test_id]})
        self.assertEqual(code, 422, error)
        self.assertEqual(self.central.latest(case['case_id']), case)

    def test_duplicate_intake_and_invalid_action_do_not_advance(self):
        self.bring_online();raw=self.new_case()
        code,body=request(self.url+'/v1/intake',raw)
        self.assertEqual(code,201,body)
        self.assertEqual(request(self.url+'/v1/intake',raw)[0],200)
        self.assertEqual(len(self.local.status()),1)
        request(self.url+'/v1/sync',{})
        original=self.central.latest(raw['case_id'])
        code,err=request(self.url+f'/v1/dashboard/cases/{raw["case_id"]}/actions',
                         {'action':'diagnosis','expected_revision':2,
                          'classification':'bacteriologically_confirmed'})
        self.assertEqual(code,422,err)
        self.assertEqual(original,self.central.latest(raw['case_id']))
        code,err=request(self.url+f'/v1/dashboard/cases/{raw["case_id"]}/actions',
                         {'action':'review','expected_revision':2,
                          'decision':'intervention_required','notes':'human referral',
                          'site_id':'DEMO-LAB-02','requested_tests':[]})
        self.assertEqual(code,422,err) # wrong area; no fake nearest
        self.assertEqual(original,self.central.latest(raw['case_id']))

if __name__=='__main__': unittest.main(verbosity=2)
