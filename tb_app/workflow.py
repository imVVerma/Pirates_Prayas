"""Demo-only, server-selected synthetic principals; never accept actors from browser.

All clinical operations delegate to unchanged M3/M4/M5 pure engines and are
persisted through the canonical M1 CentralReceiver revision gate.
This module is NOT authentication or an authorization solution for real patients.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy

ROOT = Path(__file__).resolve().parent.parent
for name in ('tb_m0','tb_m1','tb_m2','tb_m3','tb_m4a','m6_5'):
    sys.path.insert(0, str(ROOT / name))

from contract import validate_or_raise
from review_engine import (Principal as ReviewPrincipal, Site, CapacityRegistry,
                           review_case, attach_pending_screening_route)
from diagnostic_engine import (Principal as DiagnosticPrincipal, order_diagnostic_test,
                               record_diagnostic_result, record_clinician_diagnosis)
from asha_engine import (Principal as ASHAPrincipal, assign_pre_diagnosis_navigation,
                         confirm_treatment_plan, mark_treatment_started, assign_treatment_support)
from followup_engine import (Principal as FollowPrincipal, record_followup,
                             schedule_medicine_pickup, record_medicine_pickup)
from screening_attach import attach_screening_tests
from xray_adapter import build_xray_block
from esr_adapter import make_esr
from provenance import aware_time
from case_view import build_case_view

SITES = (
    Site('DEMO-LAB-01', frozenset({'diagnostic_testing'}),'DEMO-AREA-A',22,True,True),
    Site('DEMO-SCREEN-01',frozenset({'additional_screening'}),'DEMO-AREA-A',15,True,True),
    Site('DEMO-LAB-02', frozenset({'diagnostic_testing'}),'DEMO-AREA-B',34,True,True),
    Site('DEMO-SCREEN-02',frozenset({'additional_screening'}),'DEMO-AREA-B',12,True,True),
)
REGISTRY = CapacityRegistry(SITES)


def now():
    return datetime.now(timezone.utc).isoformat()

def apply_evidence(case, data):
    """Attach worker-submitted screening evidence through the unchanged M3 adapter."""
    validate_or_raise(case)
    if not isinstance(data, dict):
        raise ValueError('evidence body must be JSON object')
    revision = data.get('expected_revision')
    if type(revision) is not int or revision != case['revision']:
        raise ValueError('stale revision: refresh the case before submitting evidence')
    evidence_type = require(data, 'evidence_type')
    if evidence_type not in ('xray', 'esr'):
        raise ValueError('evidence_type must be xray or esr')
    if case['case_status'] not in ('ready_for_review', 'pending_additional_test'):
        raise ValueError('screening evidence is only accepted before diagnostic referral')
    if case['case_status'] == 'pending_additional_test':
        requested = set(case['review_history'][-1]['requested_tests'])
        if evidence_type not in requested:
            raise ValueError(f'{evidence_type} was not requested by the latest verifier review')
    at = require(data, 'captured_at')
    if evidence_type == 'xray':
        image_ref = require(data, 'image_ref')
        block = build_xray_block(available=True, image_ref=image_ref, captured_at=at)
        xray, esr = block, None
    else:
        value = data.get('value')
        upper = data.get('lab_upper_limit')
        if type(value) not in (int, float) or type(upper) not in (int, float):
            raise ValueError('ESR value and lab upper limit must be numeric')
        source = require(data, 'reference_source')
        if not source.startswith('DEMO-'):
            raise ValueError('reference_source must start with DEMO- in the synthetic prototype')
        block = make_esr(value_mm_hr=value, captured_at=at, lab_report_ref=source,
                         upper_limit_mm_hr=upper,
                         lab_reference_description=f'synthetic lab reported reference 0-{upper:g} mm/hr')
        xray, esr = None, block
    event_at = None
    if case['case_status'] == 'pending_additional_test':
        requested = set(case['review_history'][-1]['requested_tests'])
        will_have = {name: case[name]['available'] for name in requested}
        will_have[evidence_type] = True
        if all(will_have.values()):
            event_at = now()
    return attach_screening_tests(case, xray=xray, esr=esr,
                                  actor_id='demo-pharmacist-1', actor_role='pharmacist',
                                  event_at=event_at)



def require(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} is required')
    return value.strip()


def apply(case, data):
    """Apply one explicit demo action to latest M0 case. Never guesses diagnosis."""
    validate_or_raise(case)
    if not isinstance(data, dict):
        raise ValueError('action body must be JSON object')
    action = require(data, 'action')
    revision = data.get('expected_revision')
    if type(revision) is not int or revision != case['revision']:
        raise ValueError('stale revision: reload the case before submitting this action')
    at = now()
    r = ReviewPrincipal('demo-verifier-1','verifier')
    d = DiagnosticPrincipal('demo-clinician-1','clinician')
    v = DiagnosticPrincipal('demo-verifier-1','verifier')
    lab = DiagnosticPrincipal('demo-lab-1','lab')
    a = ASHAPrincipal('demo-clinician-1','clinician')
    av = ASHAPrincipal('demo-verifier-1','verifier')
    asha_id = case['asha_assignment']['asha_id'] or 'demo-asha-01'
    f = FollowPrincipal(asha_id,'asha')
    if action == 'review':
        return review_case(case,principal=r,expected_revision=revision,
                           decision=require(data,'decision'),notes=require(data,'notes'),
                           requested_tests=data.get('requested_tests',[]),
                           site_id=data.get('site_id') or None,registry=REGISTRY,when=at)
    if action == 'screen_route':
        return attach_pending_screening_route(case,principal=r,expected_revision=revision,
                    site_id=require(data,'site_id'),registry=REGISTRY,when=at)
    if action == 'xray_capture':
        # Captured image reference only. NEVER turn manual metadata into model output.
        reference = require(data,'image_ref')
        if not reference.startswith('DEMO-'):
            raise ValueError('only synthetic DEMO- image refs may be used')
        block = build_xray_block(available=True,image_ref=reference,captured_at=at)
        return attach_screening_tests(case,xray=block,actor_id='demo-lab-1',actor_role='lab',
                                      event_at=at if case['case_status']=='pending_additional_test' and
                                      set(case['review_history'][-1]['requested_tests']) <=
                                      ({'xray'} | ({'esr'} if case['esr']['available'] else set())) else None)
    if action == 'esr_result':
        value = data.get('value')
        upper = data.get('lab_upper_limit')
        if type(value) not in (int,float) or type(upper) not in (int,float) or not (0 <= value <= 500 and 0 < upper <= 250):
            raise ValueError('enter numeric lab ESR 0..500 and lab upper limit >0..250')
        source = require(data,'reference_source')
        if not source.startswith('DEMO-'):
            raise ValueError('synthetic lab reference source must start DEMO-')
        block = make_esr(value_mm_hr=value, captured_at=at, lab_report_ref=source,
                         upper_limit_mm_hr=upper,
                         lab_reference_description=f'synthetic lab reported reference 0-{upper:g} mm/hr')
        return attach_screening_tests(case,esr=block,actor_id='demo-lab-1',actor_role='lab',
                                      event_at=at if case['case_status']=='pending_additional_test' and
                                      set(case['review_history'][-1]['requested_tests']) <=
                                      ({'esr'} | ({'xray'} if case['xray']['available'] else set())) else None)
    if action == 'diagnostic_order':
        route = next((x for x in reversed(case['routes']) if x['purpose']=='diagnostic_testing' and x['status']!='cancelled'),None)
        if route is None:
            raise ValueError('first record a human diagnostic referral and route')
        return order_diagnostic_test(case,principal=v,expected_revision=revision,
                                     test_type=require(data,'test_type'),lab_id=route['site_id'],
                                     specimen_ref=data.get('specimen_ref') or None,
                                     collected_at=at if data.get('specimen_collected') is True else None,when=at)
    if action == 'diagnostic_result':
        return record_diagnostic_result(case,principal=lab,expected_revision=revision,
                                        test_id=require(data,'test_id'),result=require(data,'result'),when=at)
    if action == 'diagnosis':
        chosen = data.get('supporting_test_ids',[])
        if not isinstance(chosen,list):
            raise ValueError('supporting_test_ids must be a list')
        return record_clinician_diagnosis(case,principal=d,expected_revision=revision,
                classification=require(data,'classification'),supporting_test_ids=chosen,
                clinical_rationale=data.get('clinical_rationale') or None,
                full_course_treatment_decided=data.get('full_course_treatment_decided') is True,
                treatment_plan_confirmed=data.get('treatment_plan_confirmed') is True,when=at)
    if action == 'navigation':
        return assign_pre_diagnosis_navigation(case,principal=av,expected_revision=revision,
                                                asha_id=require(data,'asha_id'),when=at)
    if action == 'confirm_plan':
        return confirm_treatment_plan(case,principal=a,expected_revision=revision,when=at)
    if action == 'start_treatment':
        return mark_treatment_started(case,principal=a,expected_revision=revision,when=at)
    if action == 'treatment_support':
        return assign_treatment_support(case,principal=a,expected_revision=revision,
                                        asha_id=require(data,'asha_id'),when=at)
    if action == 'followup':
        return record_followup(case,principal=f,expected_revision=revision,
                               kind=require(data,'kind'),summary=require(data,'summary'),
                               trend=data.get('trend') or None,when=at)
    if action == 'pickup_schedule':
        return schedule_medicine_pickup(case,principal=f,expected_revision=revision,
                                        scheduled_date=require(data,'scheduled_date'))
    if action == 'pickup_result':
        return record_medicine_pickup(case,principal=f,expected_revision=revision,
                                      scheduled_date=require(data,'scheduled_date'),
                                      status=require(data,'status'),
                                      reschedule_date=data.get('reschedule_date') or None,when=at)
    raise ValueError(f'unsupported action: {action}')
