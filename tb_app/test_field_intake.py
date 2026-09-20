"""M7.3 regression: real M0 contract, local outbox, old intake compatibility, worker pages.

Synthetic fixtures ONLY. Browser acceptance is separately documented.
"""
from __future__ import annotations
import copy,sys, tempfile,threading,unittest
from pathlib import Path
from datetime import datetime,timezone
from http.server import ThreadingHTTPServer
from uuid import uuid4
ROOT=Path(__file__).resolve().parent.parent
for name in ('tb_m0','tb_m1','tb_m2','tb_app'):
    sys.path.insert(0,str(ROOT/name))
from contract import validate_or_raise
from intake_adapter import IntakeError,build_case
sys.path.insert(0, str(ROOT/'tb_app'))  # CHANGED ensure integrated server, not tb_m1/server.py
from server import central_handler,device_handler
from store import LocalOutbox,CentralReceiver
from test_fullstack import request, DemoTestHTTP

class FieldCaseTests(unittest.TestCase):
    def case(self,**changes):
        at=datetime.now(timezone.utc).isoformat()
        return dict(case_id=str(uuid4()),created_at=at,consent_recorded_at=at,
            consent_confirmed=True,synthetic_acknowledged=True,age=35,sex='not_recorded',
            location='DEMO-AREA-A',cough_duration_days=None,fever=None,night_sweats=False,
            weight_loss=True,xray_available=False,esr_available=False,**changes)

    def test_text_and_voice_follow_same_summary_path(self):
        source='तीन सप्ताह से खाँसी है; बुखार नहीं बताया।'
        base=self.case()
        base.update(raw_text=source,cough_present=True,cough_duration_days=21)
        typed=build_case(dict(base,text_source='text'))
        spoken=build_case(dict(base,text_source='voice',audio_recording_consent=True))
        for c in (typed,spoken):
            validate_or_raise(c)
            self.assertEqual(c['symptom_screen']['raw_transcript'],source)
            self.assertIn(source,c['case_summary']['brief_text'])
            self.assertFalse(c['xray']['available'])
            self.assertFalse(c['esr']['available'])
            self.assertIsNone(c['diagnosis'])
        self.assertEqual(typed['case_summary']['brief_text'],spoken['case_summary']['brief_text'])
        self.assertFalse(typed['consent']['audio_recording'])
        self.assertTrue(spoken['consent']['audio_recording'])

    def test_three_state_cough_and_no_hidden_symptom_inference(self):
        for answered,days,expected in [(True,21,True),(True,None,True),(False,None,False),(None,None,None)]:
            with self.subTest(answered=answered,days=days):
                raw=self.case();raw.update(cough_present=answered,cough_duration_days=days,raw_text='cough for months')
                c=build_case(raw);self.assertIs(c['symptom_screen']['cough_present'],expected)
                # Narrative does not silently overwrite a contradictory direct answer.
                self.assertIsNone(c['symptom_screen']['fever'])
        for answer,days in [(False,4),(None,5),(True,0)]:
            with self.subTest(answer=answer,days=days),self.assertRaises(IntakeError):
                build_case(dict(self.case(),cough_present=answer,cough_duration_days=days))

    def test_claims_preserved_in_summary_without_fabricating_evidence(self):
        case=build_case(dict(self.case(),xray_report_claim='yes',esr_report_claim='unknown'))
        validate_or_raise(case)
        summary=case['case_summary']['brief_text']
        self.assertIn('X-ray=yes; ESR=unknown',summary)
        self.assertIn('UNVERIFIED',summary)
        self.assertFalse(case['xray']['available'])
        self.assertFalse(case['esr']['available'])
        for claim in ('positive','maybe',None):
            with self.subTest(claim=claim),self.assertRaises(IntakeError):
                build_case(dict(self.case(),xray_report_claim=claim))

    def test_voice_and_raw_narrative_validation(self):
        for raw in [
            dict(text_source='voice',raw_text='hello'),
            dict(text_source='voice',raw_text='   ',audio_recording_consent=True),
            dict(text_source='other',raw_text='hi'),
            dict(raw_text='x'*2501),
            dict(raw_text=23),
            dict(audio_recording_consent='yes'),
            dict(location='Actual patient address')]:
            with self.subTest(raw=repr(raw)[:80]),self.assertRaises(IntakeError):
                build_case(dict(self.case(),**raw))
        self.assertEqual(build_case(self.case())['symptom_screen']['source'],'text')

    def test_device_worker_pages_and_durable_post(self):
        with tempfile.TemporaryDirectory() as t:
            local=LocalOutbox(Path(t)/'local.sqlite3')
            receiver=CentralReceiver(Path(t)/'central.sqlite3')
            server=DemoTestHTTP(('127.0.0.1',0),device_handler(local,'http://127.0.0.1:1'))
            th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
            url=f'http://127.0.0.1:{server.server_port}'
            try:
                for route, marker in [('/field','/field_intake.js'),('/field/cases','/field_cases.js'),
                                     ('/field_intake.js','/v1/intake'),('/field_cases.js','/v1/outbox'),
                                     ('/intake','/intake_bridge.js'),('/sync','/app_sync.js')]:
                    code,body=request(url+route)
                    self.assertEqual(code,200,route);self.assertIn(marker,body)
                payload=self.case(raw_text='Example narrative',text_source='text',cough_present=None)
                code,result=request(url+'/v1/intake',payload)
                self.assertEqual(code,201,result)
                self.assertEqual(result['case']['symptom_screen']['raw_transcript'],'Example narrative')
                self.assertEqual(request(url+'/v1/intake',payload)[0],200)
                self.assertEqual(len(local.status()),1)
                # Central deliberately offline. Device survives a new LocalOutbox instance.
                code,retry=request(url+'/v1/sync',{})
                self.assertEqual(code,200)
                self.assertEqual(LocalOutbox(Path(t)/'local.sqlite3').status()[0]['sync_status'],'pending')
            finally:
                server.shutdown();server.server_close();th.join(timeout=3)

if __name__=='__main__':unittest.main(verbosity=2)
