"""M1 real-SQLite / real-localhost-HTTP integration and fault-injection tests."""
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
from client import sync
from contract import M0_DIR, validate_or_raise
from server import make_handler
from store import CentralReceiver, LocalOutbox, RevisionConflict


BASE = json.loads((M0_DIR / 'fixtures/01-symptoms-only.json').read_text())


def pending_version(case):
    result = copy.deepcopy(case)
    result['revision'] += 1
    result['case_status'] = 'pending_additional_test'
    result['review_history'].append({
        'review_id': 'a0000000-0000-4000-8000-000000000001',
        'reviewer_id': 'demo-verifier-1', 'reviewer_role': 'verifier',
        'decision': 'more_tests_needed', 'requested_tests': ['xray'],
        'notes': 'Synthetic optional X-ray requested, NAAT referral remains possible.',
        'decided_at': '2026-09-20T02:15:00+05:30',
    })
    result['status_history'].append({
        'from': 'ready_for_review', 'to': 'pending_additional_test',
        'at': '2026-09-20T02:15:00+05:30', 'actor_id': 'demo-verifier-1',
        'actor_role': 'verifier',
    })
    validate_or_raise(result)
    return result


def test_return_version(case):
    result = copy.deepcopy(case)
    result['revision'] += 1
    result['case_status'] = 'ready_for_review'
    result['xray'].update(available=True, image_ref='synthetic://cxr/review-return',
                          captured_at='2026-09-20T03:40:00+05:30')
    result['status_history'].append({
        'from': 'pending_additional_test', 'to': 'ready_for_review',
        'at': '2026-09-20T03:41:00+05:30', 'actor_id': 'demo-pharmacist-1',
        'actor_role': 'pharmacist',
    })
    validate_or_raise(result)
    return result


class M1Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tb-m1-')
        root = Path(self.temp.name)
        self.local_path = root / 'device.sqlite3'
        self.central_path = root / 'central.sqlite3'
        self.outbox = LocalOutbox(self.local_path)
        self.receiver = CentralReceiver(self.central_path)
        self.start_http()

    def tearDown(self):
        self.stop_http()
        self.temp.cleanup()

    def start_http(self):
        self.httpd = ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.receiver))
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.httpd.server_port)

    def stop_http(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def post(self, case):
        request = Request(self.url + '/v1/cases', json.dumps(case).encode(),
                          {'Content-Type':'application/json'}, method='POST')
        return urlopen(request, timeout=3)

    def test_offline_relaunch_connection_then_server_restart(self):
        self.outbox.enqueue(BASE)
        self.assertEqual(self.outbox.status()[0]['sync_status'],'pending')
        # Simulate app termination and startup; local SQLite is reopened.
        self.outbox = LocalOutbox(self.local_path)
        self.assertEqual(self.outbox.status()[0]['sync_status'],'pending')
        self.assertEqual(sync(self.outbox,self.url)[0][2],'stored')
        self.assertEqual(self.outbox.status()[0]['sync_status'],'acked')
        self.stop_http()
        self.receiver = CentralReceiver(self.central_path)
        self.start_http()
        self.assertEqual(self.receiver.latest(BASE['case_id']),BASE)
        self.assertEqual(self.receiver.revisions(BASE['case_id']),[BASE['revision']])

    def test_retry_dropped_ack_never_duplicates_case(self):
        self.outbox.enqueue(BASE)
        self.assertEqual(sync(self.outbox,self.url,drop_ack_once=True)[0][2],'ack_lost_retry')
        self.assertEqual(self.outbox.status()[0]['sync_status'],'pending')
        self.assertEqual(self.receiver.revisions(BASE['case_id']),[2])
        self.outbox = LocalOutbox(self.local_path) # retry after app restart
        self.assertEqual(sync(self.outbox,self.url)[0][2],'duplicate')
        self.assertEqual(self.receiver.revisions(BASE['case_id']),[2])
        self.assertEqual(self.outbox.status()[0]['attempt_count'],2)
        self.assertEqual(self.outbox.status()[0]['sync_status'],'acked')

    def test_more_tests_loop_same_id_and_immutable_histories(self):
        v3 = pending_version(BASE)
        v4 = test_return_version(v3)
        for c in (BASE, v3, v4):
            self.assertEqual(self.outbox.enqueue(c),'queued')
        self.assertEqual([row[2] for row in sync(self.outbox,self.url)],['stored']*3)
        self.assertEqual(self.receiver.revisions(BASE['case_id']),[2,3,4])
        received = self.receiver.latest(BASE['case_id'])
        self.assertEqual(received['case_id'],BASE['case_id'])
        self.assertEqual(received['case_status'],'ready_for_review')
        self.assertTrue(received['xray']['available'])
        self.assertEqual(len(received['review_history']),1)
        self.assertEqual(len(received['status_history']),4)
        self.assertTrue(all(x['sync_status']=='acked' for x in self.outbox.status()))

    def test_gap_rejected_without_dropping_offline_copy(self):
        v3 = pending_version(BASE)
        v4 = test_return_version(v3)
        self.outbox.enqueue(v4) # first snapshot at revision 4 (initial partial local history)
        self.receiver.ingest(BASE)
        self.assertEqual(sync(self.outbox,self.url)[0][2],'needs_attention')
        self.assertEqual(self.outbox.status()[0]['sync_status'],'needs_attention')
        self.assertEqual(self.receiver.revisions(BASE['case_id']),[2])

    def test_same_revision_different_content_is_conflict(self):
        self.receiver.ingest(BASE)
        changed = copy.deepcopy(BASE)
        changed['symptom_screen']['fever'] = False
        with self.assertRaises(RevisionConflict):
            self.receiver.ingest(changed)
        with self.assertRaises(HTTPError) as caught:
            self.post(changed)
        self.assertEqual(caught.exception.code,409)
        self.assertEqual(self.receiver.latest(BASE['case_id']), BASE)

    def test_append_only_enforced_on_local_and_server(self):
        v3 = pending_version(BASE)
        self.outbox.enqueue(BASE)
        self.outbox.enqueue(v3)
        bad = test_return_version(v3)
        bad['review_history'] = []
        # valid one-snapshot? ready state may have review_history empty, but
        # server/local cross-snapshot contract rejects discarding the review.
        validate_or_raise(bad)
        with self.assertRaisesRegex(ValueError,'append-only'):
            self.outbox.enqueue(bad)
        self.receiver.ingest(BASE)
        self.receiver.ingest(v3)
        with self.assertRaises(RevisionConflict):
            self.receiver.ingest(bad)

    def test_malformed_clinical_case_rejected_over_http(self):
        bad = copy.deepcopy(BASE)
        bad['xray']['model_flag'] = 'abnormal'  # cannot infer without available test
        with self.assertRaises(HTTPError) as caught:
            self.post(bad)
        self.assertEqual(caught.exception.code,422)
        self.assertIsNone(self.receiver.latest(BASE['case_id']))

    def test_case_sync_status_remains_outside_clinical_json(self):
        self.outbox.enqueue(BASE)
        sync(self.outbox,self.url)
        self.assertNotIn('sync_status',self.receiver.latest(BASE['case_id']))
        self.assertNotIn('sync_status',BASE)
        self.assertEqual(self.outbox.status()[0]['sync_status'],'acked')

    def test_missing_server_preserves_unsent(self):
        self.outbox.enqueue(BASE)
        self.stop_http()
        self.assertEqual(sync(self.outbox,self.url)[0][2],'retry_later')
        self.assertEqual(self.outbox.status()[0]['sync_status'],'pending')
        self.receiver = CentralReceiver(self.central_path)
        self.start_http()
        self.assertEqual(sync(self.outbox,self.url)[0][2],'stored')
        self.assertEqual(self.outbox.status()[0]['sync_status'],'acked')

    def test_duplicate_submit_on_local_does_not_add_outbox_row(self):
        self.assertEqual(self.outbox.enqueue(BASE),'queued')
        self.assertEqual(self.outbox.enqueue(BASE),'already_queued')
        self.assertEqual(len(self.outbox.status()),1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
