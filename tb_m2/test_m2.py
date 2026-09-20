"""M2 adapter, device HTTP, real SQLite/HTTP to M1 integration tests."""
from __future__ import annotations
import copy
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from contract import validate_or_raise
from device_server import make_handler as make_device_handler
from intake_adapter import IntakeError, build_case
from server import make_handler as make_central_handler
from store import CentralReceiver, LocalOutbox

BASE = {
  'case_id':'b61b4aa4-c4db-5838-83c7-c4b876979bf4',
  'created_at':'2026-09-20T04:00:00+05:30',
  'consent_recorded_at':'2026-09-20T03:59:59+05:30',
  'consent_confirmed':True, 'synthetic_acknowledged':True,
  'age':35, 'sex':'female', 'location':'DEMO-AREA-A',
  'cough_duration_days':12, 'fever':True,
  'night_sweats':None, 'weight_loss':False,
  'xray_available':False, 'esr_available':False,
}

class AdapterTests(unittest.TestCase):
    def test_valid_case_m0_and_unknown_preservation(self):
        case = build_case(BASE)
        validate_or_raise(case)
        self.assertEqual(case['schema_version'],'1.0.0')
        self.assertEqual(case['revision'],2)
        self.assertEqual(case['case_status'],'ready_for_review')
        self.assertIsNone(case['symptom_screen']['night_sweats'])
        self.assertFalse(case['symptom_screen']['weight_loss'])
        self.assertIsNone(case['diagnosis'])
        self.assertFalse(case['xray']['available'])
        self.assertEqual(case,build_case(BASE))
        self.assertIn('unknown',case['case_summary']['brief_text'])
        self.assertNotIn('has TB',case['case_summary']['brief_text'])

    def test_cough_unknown_vs_absent(self):
        raw = dict(BASE,cough_duration_days=None)
        screen = build_case(raw)['symptom_screen']
        self.assertIsNone(screen['cough_present'])
        self.assertIsNone(screen['cough_duration_days'])
        raw['cough_duration_days'] = 0
        screen = build_case(raw)['symptom_screen']
        self.assertFalse(screen['cough_present'])
        self.assertIsNone(screen['cough_duration_days'])

    def test_explicit_consent_rejects_default_true_assumptions(self):
        for updates in ({'consent_confirmed':False}, {'synthetic_acknowledged':False},
                        {'consent_recorded_at':'2026-09-20T04:01:00+05:30'}):
            with self.subTest(updates=updates), self.assertRaises(IntakeError):
                build_case(dict(BASE,**updates))

    def test_age_scope_and_demo_region(self):
        for updates in ({'age':17}, {'age':True}, {'age':23.1},
                        {'location':'Rajpura block, Patiala'}, {'sex':'Male'}):
            with self.subTest(updates=updates), self.assertRaises(IntakeError):
                build_case(dict(BASE,**updates))

    def test_no_silent_test_fabrication_or_esr_cutoff(self):
        for change in ({'xray_available':True},{'esr_available':True}):
            with self.subTest(change=change), self.assertRaisesRegex(IntakeError,'M3 adapter'):
                build_case(dict(BASE,**change))
        self.assertIsNone(build_case(BASE)['esr']['flag'])

    def test_bad_symptom_type_or_extra_fields(self):
        for change in ({'fever':0},{'cough_duration_days':-3},
                       {'source':'voice'},{'case_id':'invalid'}):
            with self.subTest(change=change), self.assertRaises(IntakeError):
                build_case(dict(BASE,**change))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tb-m2-')
        root = Path(self.temp.name)
        self.local_db = root / 'device.sqlite3'
        self.central_db = root / 'central.sqlite3'
        self.outbox = LocalOutbox(self.local_db)
        self.receiver = CentralReceiver(self.central_db)
        self._servers = []
        # server starts later to assert offline WAN behavior
        self.start_device('http://127.0.0.1:1')

    def tearDown(self):
        for httpd, thread in reversed(self._servers):
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=4)
        self.temp.cleanup()

    def start_http(self,handler):
        httpd = ThreadingHTTPServer(('127.0.0.1',0),handler)
        httpd.daemon_threads = True
        thread = threading.Thread(target=httpd.serve_forever,daemon=True)
        thread.start()
        self._servers.append((httpd,thread))
        return 'http://127.0.0.1:'+str(httpd.server_port)

    def start_device(self,remote):
        self.device_url = self.start_http(make_device_handler(self.outbox,remote))

    def post(self,path,data,origin=None):
        headers={'Content-Type':'application/json'}
        if origin: headers['Origin']=origin
        req=Request(self.device_url+path,json.dumps(data).encode(),headers,method='POST')
        with urlopen(req,timeout=5) as response:
            return response.status,json.load(response)

    def test_actual_form_submission_offline_then_sync_no_duplicate(self):
        status, saved = self.post('/v1/intake',BASE)
        self.assertEqual(status,201)
        case = saved['case']
        validate_or_raise(case)
        self.assertEqual(self.outbox.status()[0]['sync_status'],'pending')
        self.assertIsNone(self.receiver.latest(case['case_id']))
        status, sync_result = self.post('/v1/sync',{})
        self.assertEqual(sync_result['outbox'][0]['sync_status'],'pending')
        self.assertEqual(sync_result['outcomes'][0]['status'],'retry_later')
        self.outbox = LocalOutbox(self.local_db)
        self.assertEqual(self.outbox.status()[0]['sync_status'],'pending')
        remote = self.start_http(make_central_handler(self.receiver))
        # New local process/server with same DB, remote is finally reachable.
        self.start_device(remote)
        _, retried = self.post('/v1/sync',{})
        self.assertEqual(retried['outbox'][0]['sync_status'],'acked')
        self.assertEqual(retried['outcomes'][0]['status'],'stored')
        self.assertEqual(self.receiver.latest(case['case_id']),case)
        self.assertEqual(self.receiver.revisions(case['case_id']),[2])
        result, repeated = self.post('/v1/intake',BASE)
        self.assertEqual(result,200)
        self.assertEqual(repeated['result'],'already_queued')
        self.assertEqual(len(self.outbox.status()),1)
        self.assertEqual(self.receiver.revisions(case['case_id']),[2])

    def test_modified_after_first_submit_explicit_conflict(self):
        self.post('/v1/intake',BASE)
        with self.assertRaises(HTTPError) as caught:
            self.post('/v1/intake',dict(BASE,fever=False))
        self.assertEqual(caught.exception.code,409)
        self.assertEqual(len(self.outbox.status()),1)

    def test_invalid_case_rejected_before_local_storage(self):
        with self.assertRaises(HTTPError) as caught:
            self.post('/v1/intake',dict(BASE,age=14))
        self.assertEqual(caught.exception.code,422)
        self.assertEqual(len(self.outbox.status()),0)

    def test_wrong_origin_forbidden(self):
        with self.assertRaises(HTTPError) as caught:
            self.post('/v1/intake',BASE,origin='https://other.example')
        self.assertEqual(caught.exception.code,403)
        self.assertEqual(len(self.outbox.status()),0)

    def test_actual_legacy_html_is_served_with_bridge(self):
        with urlopen(self.device_url+'/intake') as response:
            text = response.read().decode('utf-8')
        with urlopen(self.device_url+'/intake_bridge.js') as response:
            js = response.read().decode('utf-8')
        self.assertIn('WHO four-symptom screen',text)
        self.assertIn('src="/intake_bridge.js"',text)
        self.assertIn('fetch(path',js)
        self.assertIn('stopImmediatePropagation',js)
        self.assertIn('m2-consent',js)


if __name__ == '__main__':
    unittest.main(verbosity=2)
