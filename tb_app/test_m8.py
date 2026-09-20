"""M8 integration tests: unified summary, worker evidence, verifier requests."""
from __future__ import annotations
import base64, json, sys, tempfile, threading, unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4

ROOT=Path(__file__).resolve().parent.parent
for name in ('tb_m0','tb_m1','tb_m2','tb_m3','tb_m4a','m6_5','tb_app'):
    sys.path.insert(0,str(ROOT/name))
from server import central_handler, device_handler
from store import LocalOutbox, CentralReceiver
from contract import validate_or_raise, check_next
from test_fullstack import DemoTestHTTP


def req(url, data=None):
    r=Request(url, data=json.dumps(data).encode() if data is not None else None,
              headers={'Content-Type':'application/json'} if data is not None else {})
    try:
        with urlopen(r, timeout=8) as h:
            return h.status, json.loads(h.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


class M8(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='tb-m8-')
        base=Path(self.tmp.name)
        self.local=LocalOutbox(base/'local.sqlite3')
        self.central=CentralReceiver(base/'central.sqlite3')
        self.remote=DemoTestHTTP(('127.0.0.1',0),central_handler(self.central)); self.remote.daemon_threads=True
        self.device=DemoTestHTTP(('127.0.0.1',0),device_handler(self.local,f'http://127.0.0.1:{self.remote.server_port}')); self.device.daemon_threads=True
        self.threads=[]
        for srv in (self.remote,self.device):
            t=threading.Thread(target=srv.serve_forever,daemon=True);t.start();self.threads.append(t)
        self.url=f'http://127.0.0.1:{self.device.server_port}'
        self.addCleanup(self.close)

    def close(self):
        for s in (self.device,self.remote):s.shutdown();s.server_close()
        for t in self.threads:t.join(timeout=2)
        self.tmp.cleanup()

    def new_case(self):
        at=datetime.now(timezone.utc).isoformat()
        return {'case_id':str(uuid4()),'created_at':at,'consent_recorded_at':at,'consent_confirmed':True,
                'synthetic_acknowledged':True,'age':35,'sex':'female','location':'DEMO-AREA-A',
                'cough_present':True,'cough_duration_days':21,'fever':None,'night_sweats':False,
                'weight_loss':True,'raw_text':'तीन सप्ताह से खाँसी है।','text_source':'text',
                'audio_recording_consent':False,'xray_available':False,'esr_available':False,
                'xray_report_claim':'unknown','esr_report_claim':'unknown'}

    def sync(self):
        code,out=req(self.url+'/v1/sync',{})
        self.assertEqual(code,200,out)
        return out

    def test_summary_endpoint_uses_same_path_for_typed_and_speech_text(self):
        payload={'raw_text':'तीन सप्ताह से खाँसी है।','structured':{'cough_present':True,'cough_duration_days':21,'fever':False,'night_sweats':None,'weight_loss':True}}
        a=req(self.url+'/v1/intake/summary',payload)[1]
        b=req(self.url+'/v1/intake/summary',payload)[1]
        self.assertEqual(a,b);self.assertEqual(a['method'],'deterministic_fallback');self.assertFalse(a['diagnostic'])
        self.assertIn(payload['raw_text'],a['summary'])

    def test_verifier_request_and_same_case_evidence_submission(self):
        code,saved=req(self.url+'/v1/intake',self.new_case());self.assertEqual(code,201,saved);case=saved['case'];self.sync();
        self.assertEqual(self.local.status()[0]['sync_status'],'acked')
        status,body=req(self.url+f'/v1/dashboard/cases/{case["case_id"]}/actions',{
            'expected_revision':case['revision'],'action':'review','decision':'more_tests_needed',
            'requested_tests':['xray','esr'],'notes':'Need screening evidence.'})
        self.assertEqual(status,201,body);pending=body['case'];self.assertEqual(pending['case_status'],'pending_additional_test')
        code,request=req(self.url+f'/v1/field/cases/{case["case_id"]}/requests');self.assertEqual(code,200);self.assertEqual(request['pending_tests'],['xray','esr'])
        image=base64.b64encode(b'fake-png-for-synthetic-upload').decode()
        code,x=req(self.url+f'/v1/field/cases/{case["case_id"]}/evidence',{'evidence_type':'xray','upload':{'filename':'demo.png','mime_type':'image/png','content_base64':image},'captured_at':datetime.now(timezone.utc).isoformat()})
        self.assertEqual(code,201,x);xray_case=x['case'];self.assertEqual(xray_case['case_id'],case['case_id']);self.assertTrue(xray_case['xray']['available']);self.assertEqual(xray_case['case_status'],'pending_additional_test')
        code,e=req(self.url+f'/v1/field/cases/{case["case_id"]}/evidence',{'evidence_type':'esr','value':42,'lab_upper_limit':22,'reference_source':'DEMO-LAB-REF-01','captured_at':datetime.now(timezone.utc).isoformat()})
        self.assertEqual(code,201,e);final=e['case'];self.assertEqual(final['case_id'],case['case_id']);self.assertTrue(final['esr']['available']);self.assertEqual(final['case_status'],'ready_for_review');self.assertEqual(final['revision'],pending['revision']+2);validate_or_raise(final)
        self.sync();self.assertEqual(self.local.status()[-1]['sync_status'],'acked')

if __name__=='__main__':unittest.main(verbosity=2)
