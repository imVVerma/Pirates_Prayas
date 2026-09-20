"""M3 gate: real M0/M1 contract, negative provenance tests, offline model stubs.

No TensorFlow, large downloads, UI, network, or private patient records.
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'tb_m1'))
sys.path.insert(0, str(ROOT.parent / 'tb_m0'))
sys.path.insert(0, str(ROOT.parent / 'tb_m4a'))

from contract import validate_or_raise, check_next
from store import LocalOutbox, CentralReceiver
from screening_attach import attach_screening_tests
from esr_adapter import make_esr
from xray_adapter import (infer_xray, prepare_image, detect_pixel_range,
                          model_image_shape, sha256_file, load_local_h5, infer_verified_local)
from provenance import EvidenceError, aware_time

CASE_PATH = ROOT.parent / 'tb_m2' / 'canonical-case-output.json'
NOW = '2026-09-20T05:00:00+05:30'


def source_case():
    return json.loads(CASE_PATH.read_text())


def cxr(**kwargs):
    data = {
        'available': True, 'image_ref': 'synthetic://cxr/record-1',
        'model_flag': 'abnormal', 'model_confidence': 0.7,
        'heatmap_ref': None, 'model_id': 'synthetic-model-NOT-REAL',
        'captured_at': '2026-09-20T04:30:00+05:30',
    }
    data.update(kwargs)
    return data


def esr(**kwargs):
    data = make_esr(value_mm_hr=40, captured_at='2026-09-20T04:30:00+05:30',
                    lab_report_ref='SYNTHETIC-123', upper_limit_mm_hr=22,
                    lab_reference_description='0-22 mm/h (SYNTHETIC)')
    data.update(kwargs)
    return data


def attach(case, **kwargs):
    return attach_screening_tests(case, actor_id='demo-pharmacist-1', actor_role='pharmacist', **kwargs)


class ProvenanceTests(unittest.TestCase):
    def test_real_offset(self):
        self.assertEqual(aware_time('2026-09-20T04:00:00+05:30', 'when'),
                         datetime(2026, 9, 19, 22, 30, tzinfo=timezone.utc))

    def test_invalid_date(self):
        with self.assertRaises(EvidenceError):
            aware_time('2026-13-20T04:00:00Z', 'when')

    def test_naive_date(self):
        with self.assertRaises(EvidenceError):
            aware_time('2026-09-20T04:00:00', 'when')

    def test_placeholder_date(self):
        with self.assertRaises(EvidenceError):
            aware_time('t', 'when')


class ESRTests(unittest.TestCase):
    def test_unavailable(self):
        result = make_esr()
        self.assertFalse(result['available'])
        self.assertTrue(all(v is None for k, v in result.items() if k != 'available'))

    def test_normal(self):
        self.assertEqual(make_esr(value_mm_hr=20, captured_at=NOW, lab_report_ref='r',
                                  upper_limit_mm_hr=20, lab_reference_description='0-20')['flag'], 'normal')

    def test_elevated(self):
        result = esr()
        self.assertEqual(result['flag'], 'elevated')
        self.assertIn('SYNTHETIC-123', result['reference_range_used'])

    def test_markedly_elevated_not_tb(self):
        result = make_esr(value_mm_hr=100, captured_at=NOW, lab_report_ref='r',
                          upper_limit_mm_hr=30, lab_reference_description='<=30')
        self.assertEqual(result['flag'], 'markedly_elevated')
        self.assertIn('not a TB cutoff', result['reference_range_used'])

    def test_no_lab_threshold(self):
        with self.assertRaises(EvidenceError):
            make_esr(value_mm_hr=31, captured_at=NOW, lab_report_ref='r')

    def test_no_fake_report(self):
        with self.assertRaises(EvidenceError):
            make_esr(value_mm_hr=31, captured_at=NOW, upper_limit_mm_hr=20,
                     lab_reference_description='0-20')

    def test_invalid_values(self):
        for bad in ('12', True, float('nan'), float('inf'), -1, 501, None):
            with self.subTest(bad=bad), self.assertRaises(EvidenceError):
                make_esr(value_mm_hr=bad, captured_at=NOW, lab_report_ref='r',
                         upper_limit_mm_hr=20, lab_reference_description='0-20')

    def test_missing_time(self):
        with self.assertRaises(EvidenceError):
            make_esr(value_mm_hr=30, lab_report_ref='r', upper_limit_mm_hr=20,
                     lab_reference_description='0-20')

    def test_invalid_upper(self):
        with self.assertRaises(EvidenceError):
            make_esr(value_mm_hr=30, captured_at=NOW, lab_report_ref='r',
                     upper_limit_mm_hr=0, lab_reference_description='0-0')


class FakeRescaling:
    pass
FakeRescaling.__name__ = 'Rescaling'

class Rescaling:
    def __init__(self, scale=1/255):
        self.scale = scale

class DummyModel:
    input_shape = (None, 300, 300, 3)
    def __init__(self, score=0.7, layers=None):
        self.score = score
        self.layers = [Rescaling()] if layers is None else layers
        self.received = None
    def predict(self, batch, verbose=0):
        self.received = batch.copy()
        return [[self.score]]


class XrayTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = Path(self.tmp.name)/'gray.png'
        Image.new('RGB', (80, 80), (255,255,255)).save(self.image)
        self.sha = 'a'*64

    def call(self, model=None, **kwargs):
        values = dict(model=model or DummyModel(), model_sha256=self.sha,
                      image_path=self.image, image_ref='synthetic://cxr/1',
                      captured_at=NOW, label_mapping_verified=True)
        values.update(kwargs)
        return infer_xray(**values)

    def test_raw_score_and_scale_once(self):
        model = DummyModel(0.17)
        result = self.call(model)
        self.assertEqual(result['model_confidence'], 0.17)
        self.assertEqual(result['model_flag'], 'normal')
        self.assertAlmostEqual(float(model.received.max()), 255)
        self.assertIn('input=raw_0_255', result['model_id'])
        self.assertIsNone(result['heatmap_ref'])

    def test_positive_score(self):
        self.assertEqual(self.call(DummyModel(0.73))['model_flag'], 'abnormal')

    def test_no_unverified_label(self):
        with self.assertRaisesRegex(EvidenceError, 'label mapping'):
            self.call(label_mapping_verified=False)

    def test_no_fake_sha(self):
        with self.assertRaises(EvidenceError):
            self.call(model_sha256='bogus')

    def test_no_captured_at(self):
        with self.assertRaises(EvidenceError):
            self.call(captured_at=None)

    def test_no_image_ref(self):
        with self.assertRaises(EvidenceError):
            self.call(image_ref=None)

    def test_scaling_ambiguous(self):
        with self.assertRaisesRegex(EvidenceError, 'preprocessing unknown'):
            self.call(model=DummyModel(layers=[]))

    def test_operator_confirmed_zero_one(self):
        model = DummyModel(layers=[])
        result = self.call(model=model, pixel_range='zero_one')
        self.assertAlmostEqual(float(model.received.max()), 1)
        self.assertIn('input=zero_one', result['model_id'])

    def test_nested_rescaling(self):
        child = DummyModel(layers=[Rescaling()])
        root = DummyModel(layers=[child])
        self.assertEqual(detect_pixel_range(root), 'raw_0_255')

    def test_multiple_rescaling_rejected(self):
        with self.assertRaises(EvidenceError):
            detect_pixel_range(DummyModel(layers=[Rescaling(),Rescaling()]))

    def test_wrong_layer_scale(self):
        with self.assertRaises(EvidenceError):
            detect_pixel_range(DummyModel(layers=[Rescaling(0.5)]))

    def test_output_wrong_shape(self):
        model = DummyModel()
        model.predict = lambda batch, verbose=0: [[0.5,0.5]]
        with self.assertRaisesRegex(EvidenceError, 'expected finite sigmoid'):
            self.call(model)

    def test_output_nan(self):
        with self.assertRaises(EvidenceError):
            self.call(DummyModel(float('nan')))

    def test_missing_model_no_download(self):
        with self.assertRaises(EvidenceError):
            load_local_h5(Path(self.tmp.name)/'unknown.h5')

    def test_preprocess_unknown_format(self):
        fake = Path(self.tmp.name)/'bad.bmp'
        from PIL import Image
        Image.new('RGB', (100,100)).save(fake)
        with self.assertRaisesRegex(EvidenceError, 'PNG/JPEG'):
            prepare_image(fake, DummyModel())

    def test_verified_local_report_pins_weights(self):
        from unittest.mock import patch
        import json
        model_file = Path(self.tmp.name)/'tiny.h5'
        model_file.write_bytes(b'model stub; no actual h5')
        sha = sha256_file(model_file)
        report_file = Path(self.tmp.name)/'report.json'
        report_file.write_text(json.dumps({
            'status': 'checkpoint_smoke_pass_only',
            'model_sha256': sha, 'clinical_validation': False,
            'label_mapping': 'class_1=TB_suggestive, class_0=normal_in_model',
            'preprocessing': 'raw_0_255',
            'checked_at': NOW,
            'normal_image_sha256': 'c'*64,
            'tb_image_sha256': 'd'*64,
            'known_normal_score': 0.12,
            'known_tb_score': 0.83,
        }))
        with patch('xray_adapter.load_local_h5', return_value=(DummyModel(),sha)):
            block = infer_verified_local(model_path=model_file,
                verification_report_path=report_file, image_path=self.image,
                image_ref='synthetic://cxr/1', captured_at=NOW)
            self.assertEqual(block['model_flag'], 'abnormal')
            # Change the report, and the exact same weights must be refused.
            obj = json.loads(report_file.read_text())
            obj['model_sha256'] = 'b'*64
            report_file.write_text(json.dumps(obj))
            with self.assertRaisesRegex(EvidenceError, 'differ'):
                infer_verified_local(model_path=model_file,
                    verification_report_path=report_file, image_path=self.image,
                    image_ref='synthetic://cxr/1', captured_at=NOW)

    def test_sha(self):
        self.assertEqual(len(sha256_file(self.image)), 64)


class ContractAndSyncTests(unittest.TestCase):
    def test_source_fixture_valid(self):
        validate_or_raise(source_case())

    def test_attach_esr(self):
        old = source_case()
        new = attach(old, esr=esr())
        validate_or_raise(new)
        check_next(old, new)
        self.assertEqual(new['revision'], old['revision']+1)
        self.assertEqual(new['case_status'], 'ready_for_review')
        self.assertEqual(old['esr']['available'], False)
        self.assertEqual(new['diagnosis'], None)

    def test_attach_xray(self):
        old = source_case()
        new = attach(old, xray=cxr())
        validate_or_raise(new)
        self.assertEqual(new['xray']['model_confidence'], 0.7)
        self.assertIsNone(new['diagnosis'])

    def test_attach_both(self):
        old = source_case()
        new = attach(old, xray=cxr(), esr=esr())
        validate_or_raise(new)
        self.assertEqual(new['revision'], 3)
        self.assertEqual(new['patient'], old['patient'])

    def test_source_untouched(self):
        old = source_case()
        original = copy.deepcopy(old)
        attach(old, xray=cxr())
        self.assertEqual(old, original)

    def test_idempotency(self):
        old = attach(source_case(), esr=esr())
        retry = attach(old, esr=esr())
        self.assertEqual(retry, old)

    def test_partial_update(self):
        old = attach(source_case(), esr=esr())
        new = attach(old, esr=esr(), xray=cxr())
        self.assertEqual(new['revision'], old['revision']+1)

    def test_overwrite_forbidden(self):
        old = attach(source_case(), esr=esr())
        with self.assertRaisesRegex(EvidenceError, 'conflicting evidence'):
            attach(old, esr=esr(value=50))

    def test_unavailable_cannot_erase(self):
        old = attach(source_case(), esr=esr())
        with self.assertRaisesRegex(EvidenceError, 'cannot be removed'):
            attach(old, esr=make_esr())

    def test_xray_raw_capture_then_inference(self):
        raw = cxr(model_flag=None, model_confidence=None, model_id=None)
        old = attach(source_case(), xray=raw)
        new = attach(old, xray=cxr())
        validate_or_raise(new)
        self.assertEqual(new['revision'], old['revision']+1)
        self.assertEqual(new['xray']['image_ref'], raw['image_ref'])

    def test_xray_conflicting_image(self):
        old = attach(source_case(), xray=cxr(model_flag=None, model_confidence=None, model_id=None))
        with self.assertRaisesRegex(EvidenceError, 'different image'):
            attach(old, xray=cxr(image_ref='synthetic://other-image'))

    def test_no_inference_without_model_id(self):
        with self.assertRaises(EvidenceError):
            attach(source_case(), xray=cxr(model_id=None))

    def test_no_esr_flag_without_source(self):
        with self.assertRaises(EvidenceError):
            attach(source_case(), esr=esr(reference_range_used=None))

    def test_unavailable_partial_refused(self):
        with self.assertRaises(EvidenceError):
            attach(source_case(), esr=esr(available=False))

    def test_reject_actor(self):
        with self.assertRaises(EvidenceError):
            attach_screening_tests(source_case(), esr=esr(), actor_id='x', actor_role='system')

    def test_reject_time_on_ready(self):
        with self.assertRaises(EvidenceError):
            attach(source_case(), esr=esr(), event_at=NOW)

    def test_no_input(self):
        with self.assertRaises(EvidenceError):
            attach(source_case())

    def test_pending_loop(self):
        old = source_case()
        old['revision'] = 3
        old['case_status'] = 'pending_additional_test'
        old['review_history'] = [{
            'review_id': 'e5363529-771e-476e-8005-3244fbdf922a',
            'reviewer_id':'demo-verifier-1', 'reviewer_role':'verifier',
            'decision':'more_tests_needed','requested_tests':['xray','esr'],
            'notes':'Optional screening requested for demo.',
            'decided_at':'2026-09-20T04:15:00+05:30',
        }]
        old['status_history'].append({
            'from':'ready_for_review','to':'pending_additional_test',
            'at':'2026-09-20T04:15:00+05:30',
            'actor_id':'demo-verifier-1','actor_role':'verifier',
        })
        validate_or_raise(old)
        partial = attach(old, esr=esr())
        self.assertEqual(partial['case_status'], 'pending_additional_test')
        self.assertEqual(partial['revision'], 4)
        with self.assertRaisesRegex(EvidenceError, 'event_at required'):
            attach(partial, xray=cxr())
        with self.assertRaises(EvidenceError):
            attach(partial, xray=cxr(), event_at='2026-09-20T04:16:00+05:30')
        ready = attach(partial, xray=cxr(), event_at=NOW)
        validate_or_raise(ready)
        check_next(partial, ready)
        self.assertEqual(ready['revision'], 5)
        self.assertEqual(ready['case_status'], 'ready_for_review')
        self.assertEqual(ready['review_history'], old['review_history'])
        self.assertEqual(ready['status_history'][-1]['actor_role'], 'pharmacist')
        self.assertIsNone(ready['diagnosis'])
        self.assertEqual(attach(ready, xray=cxr(), esr=esr()), ready)

    def test_m4a_real_review_to_m3_return_to_diagnostic_referral(self):
        from review_engine import review_case, Principal, Site, CapacityRegistry
        base = source_case()
        reviewer = Principal(actor_id='demo-verifier-1', role='verifier')
        pending = review_case(base, principal=reviewer,
            expected_revision=base['revision'], decision='more_tests_needed',
            notes='Additional screening (synthetic workflow only).',
            requested_tests=['xray', 'esr'],
            when='2026-09-20T04:15:00+05:30')
        self.assertEqual(pending['case_status'], 'pending_additional_test')
        returned = attach(pending, xray=cxr(), esr=esr(), event_at=NOW)
        self.assertEqual(returned['case_status'], 'ready_for_review')
        registry = CapacityRegistry([Site('SYNTHETIC-NAAT-1',
            frozenset({'diagnostic_testing'}),'DEMO-AREA-A',25,True,True)])
        routed = review_case(returned, principal=reviewer,
            expected_revision=returned['revision'], decision='intervention_required',
            notes='Human-selected molecular diagnostic referral; not a TB diagnosis.',
            site_id='SYNTHETIC-NAAT-1', registry=registry,
            when='2026-09-20T05:10:00+05:30')
        self.assertIsNone(routed['diagnosis'])
        with tempfile.TemporaryDirectory() as tmp:
            central = CentralReceiver(Path(tmp)/'central.sqlite')
            outbox = LocalOutbox(Path(tmp)/'local.sqlite')
            for obj in (base, pending, returned, routed):
                validate_or_raise(obj)
                outbox.enqueue(obj)
                central.ingest(obj)
            self.assertEqual(central.revisions(base['case_id']), [2,3,4,5])
            self.assertEqual(central.latest(base['case_id']), routed)

    def test_sync_end_to_end_and_retry(self):
        original = source_case()
        newer = attach(original, xray=cxr(), esr=esr())
        with tempfile.TemporaryDirectory() as tmp:
            outbox = LocalOutbox(Path(tmp)/'local.sqlite')
            central = CentralReceiver(Path(tmp)/'central.sqlite')
            self.assertEqual(outbox.enqueue(original), 'queued')
            self.assertEqual(outbox.enqueue(newer), 'queued')
            self.assertEqual(central.ingest(original)['result'], 'stored')
            self.assertEqual(central.ingest(newer)['result'], 'stored')
            self.assertEqual(central.ingest(newer)['result'], 'duplicate')
            self.assertEqual(central.revisions(original['case_id']), [2,3])
            self.assertEqual(central.latest(original['case_id']), newer)


if __name__ == '__main__':
    unittest.main(verbosity=2)
