#!/usr/bin/env python3
"""Validate TB M0 synthetic case snapshots: JSON Schema + cross-field clinical invariants.

Requires: pip install 'jsonschema>=4.18,<5'
Run: python validate_cases.py
Run one case: python validate_cases.py --case fixtures/01-symptoms-only.json

The JSON Schema handles field types and allowed values; these additional rules
handle temporal coherence, roles, state changes and medical classification.
Not a substitute for clinical review or authorization on a real server.
"""
import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
STATES = {
    'intake': {'ready_for_review'},
    'ready_for_review': {'pending_additional_test', 'routed_for_diagnostics', 'diagnosed', 'closed'},
    'pending_additional_test': {'ready_for_review', 'routed_for_diagnostics'},
    'routed_for_diagnostics': {'diagnostic_result_available', 'diagnosed', 'closed'},
    'diagnostic_result_available': {'routed_for_diagnostics', 'diagnosed', 'closed'},
    'diagnosed': {'closed'},
    'closed': set(),
}
TRANSITION_ACTORS = {
    ('intake', 'ready_for_review'): {'pharmacist', 'verifier', 'clinician'},
    ('ready_for_review', 'pending_additional_test'): {'verifier', 'clinician'},
    ('pending_additional_test', 'ready_for_review'): {'pharmacist', 'lab', 'verifier', 'clinician'},
    ('ready_for_review', 'routed_for_diagnostics'): {'verifier', 'clinician'},
    ('pending_additional_test', 'routed_for_diagnostics'): {'verifier', 'clinician'},
    ('diagnostic_result_available', 'routed_for_diagnostics'): {'verifier', 'clinician'},
    ('routed_for_diagnostics', 'diagnostic_result_available'): {'lab'},
    ('ready_for_review', 'diagnosed'): {'clinician'},
    ('routed_for_diagnostics', 'diagnosed'): {'clinician'},
    ('diagnostic_result_available', 'diagnosed'): {'clinician'},
    ('ready_for_review', 'closed'): {'verifier', 'clinician'},
    ('routed_for_diagnostics', 'closed'): {'clinician'},
    ('diagnostic_result_available', 'closed'): {'clinician'},
    ('diagnosed', 'closed'): {'clinician'},
}


def stamp(value):
    """The schema validates RFC3339; reject timestamps without a UTC offset."""
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError('timestamp must include Z or an explicit timezone offset')
    return d.astimezone(timezone.utc)


def semantics(case):
    problems = []

    def check(test, message):
        if not test:
            problems.append(message)

    created = stamp(case['created_at'])
    check(stamp(case['consent']['recorded_at']) <= created, 'consent recorded after case creation')
    symptom = case['symptom_screen']
    if symptom['cough_present'] is not True:
        check(symptom['cough_duration_days'] is None, 'duration cannot be supplied when cough is absent/unknown')
    check(stamp(symptom['structured_at']) >= created, 'symptoms structured before case creation')
    if symptom['source'] == 'voice':
        check(case['consent']['audio_recording'], 'voice intake needs explicit recording consent')

    x = case['xray']
    if not x['available']:
        for field in ('image_ref', 'captured_at', 'model_flag', 'model_confidence', 'model_id', 'heatmap_ref'):
            check(x[field] is None, 'unavailable X-ray cannot contain ' + field)
    else:
        check(x['image_ref'] is not None and x['captured_at'] is not None, 'available X-ray requires image_ref and captured_at')
        if x['model_flag'] is None:
            check(x['model_confidence'] is None and x['model_id'] is None and x['heatmap_ref'] is None,
                  'X-ray without inference flag cannot contain model results')
        else:
            check(x['model_confidence'] is not None and x['model_id'] is not None,
                  'model flag requires traceable model_id and raw score')

    e = case['esr']
    if not e['available']:
        for field in ('value', 'captured_at', 'flag', 'reference_range_used'):
            check(e[field] is None, 'unavailable ESR cannot contain ' + field)
    else:
        check(e['value'] is not None and e['captured_at'] is not None, 'available ESR requires reading and timestamp')
        if e['flag'] is not None:
            check(e['reference_range_used'] is not None, 'ESR flag needs source of reference interval')

    summary = case['case_summary']
    check((summary['brief_text'] is None) == (summary['generated_at'] is None), 'summary text/timestamp must appear together')
    if summary['generated_at'] is not None:
        check(stamp(summary['generated_at']) >= created, 'summary generated before case creation')

    hist = case['status_history']
    check(hist[0]['from'] is None and hist[0]['to'] == 'intake', 'first history entry must create intake')
    check(stamp(hist[0]['at']) == created, 'first history timestamp must equal created_at')
    check(hist[0]['actor_role'] in ('pharmacist', 'clinician'), 'intake must be initiated by pharmacist/clinician')
    last = None
    last_time = None
    for i, transition in enumerate(hist):
        frm, to = transition['from'], transition['to']
        at = stamp(transition['at'])
        if i:
            check(frm == last, f'history[{i}] from does not match previous to')
            check(to in STATES.get(frm, ()), f'invalid clinical transition {frm} -> {to}')
            check(transition['actor_role'] in TRANSITION_ACTORS.get((frm, to), ()),
                  f'role {transition["actor_role"]} cannot make transition {frm} -> {to}')
            check(at >= last_time, f'history[{i}] timestamp out of order')
        last, last_time = to, at
    check(last == case['case_status'], 'case_status differs from final history state')
    check(case['revision'] >= len(hist), 'revision lower than recorded number of state events')

    reviews = case['review_history']
    check(len({r['review_id'] for r in reviews}) == len(reviews), 'duplicate review_id')
    previous_review_time = created
    for r in reviews:
        at = stamp(r['decided_at'])
        check(at >= previous_review_time, 'review_history not chronological')
        previous_review_time = at
        if r['decision'] == 'more_tests_needed':
            check(bool(r['requested_tests']), 'more_tests_needed requires explicit requested screening tests')
        else:
            check(not r['requested_tests'], 'non-request reviewer decision cannot carry requested_tests')
        check(at >= created, 'review before case creation')
    if case['case_status'] == 'pending_additional_test':
        check(bool(reviews) and reviews[-1]['decision'] == 'more_tests_needed',
              'pending_additional_test requires latest human review to request additional tests')
    if case['case_status'] == 'routed_for_diagnostics':
        check(bool(reviews) and reviews[-1]['decision'] == 'intervention_required',
              'routed_for_diagnostics requires human referral decision')

    routes = case['routes']
    check(len({r['route_id'] for r in routes}) == len(routes), 'duplicate route_id')
    check(all(stamp(r['routed_at']) >= created for r in routes), 'routing before case creation')
    has_diagnostic_route = any(r['purpose'] == 'diagnostic_testing' and r['status'] != 'cancelled' for r in routes)
    if case['case_status'] in ('routed_for_diagnostics', 'diagnostic_result_available'):
        check(has_diagnostic_route, 'diagnostic-stage case requires active/completed diagnostic route')

    tests = case['diagnostic_tests']
    by_id = {r['test_id']: r for r in tests}
    check(len(by_id) == len(tests), 'duplicate test_id')
    positive = [r for r in tests if r['result'] == 'positive']
    completed = [r for r in tests if r['result'] != 'pending']
    for r in tests:
        if r['result'] == 'pending':
            check(r['result_at'] is None, 'pending diagnostic test cannot have result_at')
        else:
            check(all(r[f] is not None for f in ('lab_id','specimen_ref','collected_at','result_at')),
                  'completed diagnostic test requires lab/specimen/collection/result provenance')
        if r['collected_at'] is not None:
            check(stamp(r['collected_at']) >= created, 'sample before case creation')
        if r['result_at'] is not None:
            check(stamp(r['result_at']) >= created, 'result before case creation')
            if r['collected_at'] is not None:
                check(stamp(r['result_at']) >= stamp(r['collected_at']), 'result before sample collected')
    if case['case_status'] == 'diagnostic_result_available':
        check(bool(completed), 'diagnostic_result_available must have a completed diagnostic test')

    diagnosis = case['diagnosis']
    if diagnosis is not None:
        check(case['case_status'] in ('diagnosed', 'closed'), 'TB diagnosis cannot exist before diagnosed state')
        check(any(h['to'] == 'diagnosed' and h['actor_role'] == 'clinician'
                  and h['actor_id'] == diagnosis['clinician_id'] and stamp(h['at']) == stamp(diagnosis['diagnosed_at'])
                  for h in hist), 'diagnosis must match a named clinician-performed transition')
        linked = [by_id.get(tid) for tid in diagnosis['supporting_test_ids']]
        check(all(item is not None for item in linked), 'diagnosis references unknown diagnostic test')
        if diagnosis['classification'] == 'bacteriologically_confirmed':
            check(any(t and t['result'] == 'positive' for t in linked),
                  'bacteriological confirmation needs cited positive WHO-recognized test')
            check(not diagnosis['clinical_rationale'] or isinstance(diagnosis['clinical_rationale'], str),
                  'unexpected clinical rationale format')
            for test in linked:
                if test and test['result'] == 'positive' and test['result_at']:
                    check(stamp(diagnosis['diagnosed_at']) >= stamp(test['result_at']),
                          'diagnosis made before supporting positive result')
        if diagnosis['treatment_started_at'] is not None:
            check(diagnosis['treatment_plan_confirmed'], 'treatment cannot start without a confirmed treatment plan')
            check(stamp(diagnosis['treatment_started_at']) >= stamp(diagnosis['diagnosed_at']),
                  'treatment start recorded before diagnosis')
        if diagnosis['classification'] == 'clinically_diagnosed':
            check(not positive, 'clinically diagnosed case with positive assay must be reclassified as bacteriologically confirmed')
            check(bool(diagnosis['clinical_rationale']), 'clinical diagnosis requires clinician rationale')
            check(diagnosis['full_course_treatment_decided'], 'clinical diagnosis requires clinician decision to give full TB treatment')
            check(diagnosis['treatment_plan_confirmed'], 'clinical diagnosis requires confirmed care plan')
    elif case['case_status'] == 'diagnosed':
        check(False, 'diagnosed state requires diagnosis evidence')

    assignment = case['asha_assignment']
    phase = assignment['support_phase']
    if phase is None:
        check(assignment['asha_id'] is None and assignment['assigned_at'] is None,
              'unassigned ASHA record has ID/timestamp')
    else:
        check(assignment['asha_id'] is not None and assignment['assigned_at'] is not None,
              'ASHA support must have a named worker and timestamp')
    if phase == 'pre_diagnosis_navigation':
        check(bool(reviews) and reviews[-1]['decision'] in ('more_tests_needed', 'intervention_required'),
              'pre-diagnosis ASHA navigation requires human referral/test-request decision')
    if phase == 'treatment_support':
        check(diagnosis is not None and diagnosis['treatment_started_at'] is not None if diagnosis else False,
              'treatment-support ASHA requires documented actual treatment start')
        if diagnosis and assignment['assigned_at']:
            check(stamp(assignment['assigned_at']) >= stamp(diagnosis['diagnosed_at']),
                  'treatment ASHA assigned before diagnosis')
            if diagnosis['treatment_started_at'] is not None:
                check(stamp(assignment['assigned_at']) >= stamp(diagnosis['treatment_started_at']),
                      'treatment ASHA assigned before treatment initiation')
    if assignment['medicine_pickup_log']:
        check(phase == 'treatment_support', 'medicine pickup records require treatment-support ASHA')
    for entry in assignment['medicine_pickup_log']:
        check((entry['status'] == 'scheduled') == (entry['logged_at'] is None),
              'scheduled pickup has no outcome timestamp; picked_up/missed needs one')
        if entry['logged_at'] is not None and assignment['assigned_at'] is not None:
            check(stamp(entry['logged_at']) >= stamp(assignment['assigned_at']), 'pickup logged before assignment')

    for f in case['followups']:
        check(stamp(f['date']) >= created, 'follow-up before case creation')
        if f['source'] == 'voice':
            check(case['consent']['audio_recording'], 'voice follow-up needs explicit recording consent')
        if f['kind'] == 'treatment':
            check(phase == 'treatment_support', 'treatment follow-up without ASHA treatment support')
            check(diagnosis is not None and diagnosis['treatment_started_at'] is not None if diagnosis else False,
                  'treatment follow-up before documented treatment initiation')
        else:
            check(phase in ('pre_diagnosis_navigation', 'treatment_support'),
                  'navigation follow-up without ASHA assignment')
        if assignment['assigned_at'] is not None:
            check(stamp(f['date']) >= stamp(assignment['assigned_at']), 'follow-up before ASHA assignment')

    if case['case_status'] == 'closed' and diagnosis is None:
        check((bool(reviews) and reviews[-1]['decision'] == 'not_required') or
              (hist[-1]['actor_role'] == 'clinician' and bool(completed)),
              'undiagnosed closure requires no-referral review or clinician review of diagnostic result')
    return problems


def validate(case, schema):
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = [f'{"/".join(map(str, e.path)) or "$"}: {e.message}' for e in validator.iter_errors(case)]
    if errors:
        return ['SCHEMA ' + s for s in sorted(errors)]
    try:
        return ['INVARIANT ' + s for s in semantics(case)]
    except (KeyError, TypeError, ValueError) as exc:
        return ['INVARIANT validation error: ' + str(exc)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, help='Validate a single JSON case, or run the full M0 gates by default')
    args = parser.parse_args()
    schema = json.loads((ROOT / 'case-schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    if args.case:
        errors = validate(json.loads(args.case.read_text()), schema)
        print(('FAIL ' + str(args.case) + '\n  ' + '\n  '.join(errors)) if errors else 'PASS ' + str(args.case))
        return 1 if errors else 0

    failures = 0
    for path in sorted((ROOT / 'fixtures').glob('*.json')):
        errors = validate(json.loads(path.read_text()), schema)
        if errors:
            failures += 1
            print('FAIL valid fixture', path.name, *['  ' + e for e in errors], sep='\n')
        else:
            print('PASS valid fixture', path.name)
    for path in sorted((ROOT / 'invalid-fixtures').glob('*.json')):
        case = json.loads(path.read_text())
        schema_errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(case))
        if schema_errors:
            print('PASS malformed fixture rejected by schema', path.name)
        else:
            failures += 1
            print('FAIL malformed fixture unexpectedly passed schema', path.name)

    one = json.loads((ROOT / 'fixtures' / '01-symptoms-only.json').read_text())
    three = json.loads((ROOT / 'fixtures' / '03-more-tests-loop.json').read_text())
    four = json.loads((ROOT / 'fixtures' / '04-diagnostic-result.json').read_text())

    # Deliberately cross-field malformed; JSON Schema alone cannot compare timestamps,
    # match linked test IDs, or interpret history. All MUST fail combined validation.
    mutations = [
        ('unavailable X-ray with result', one, lambda c: c['xray'].update(model_flag='abnormal')),
        ('no cough but duration', one, lambda c: c['symptom_screen'].update(cough_present=False)),
        ('ESR absent yet value set', one, lambda c: c['esr'].update(value=51)),
        ('case state disagrees with history', one, lambda c: c.update(case_status='diagnosed')),
        ('revision falls behind history', one, lambda c: c.update(revision=1)),
        ('voice without consent', one, lambda c: c['symptom_screen'].update(source='voice')),
        ('ASHA treatment before diagnosis', one, lambda c: c['asha_assignment'].update(asha_id='DEMO-ASHA',assigned_at='2026-09-20T02:10:00+05:30',support_phase='treatment_support')),
        ('ASHA medicine pickups before diagnosis', one, lambda c: c['asha_assignment']['medicine_pickup_log'].append({'scheduled_date':'2026-09-21','status':'scheduled','logged_at':None})),
        ('request more tests without human decision', three, lambda c: c['review_history'].clear()),
        ('unsupported TB diagnosis from X-ray alone', four, lambda c: c['diagnostic_tests'].clear()),
        ('positive test misclassified as clinical diagnosis', four, lambda c: c['diagnosis'].update(classification='clinically_diagnosed',clinical_rationale='synthetic',supporting_test_ids=[],full_course_treatment_decided=True)),
        ('lab impersonates clinician for diagnosis', four, lambda c: c['status_history'][-1].update(actor_role='lab')),
        ('diagnosis from before positive test result', four, lambda c: c['diagnostic_tests'][0].update(result_at='2026-09-20T05:45:00+05:30')),
        ('diagnosis without treatment plan cannot start treatment follow-up', four, lambda c: c['diagnosis'].update(treatment_plan_confirmed=False)),
        ('treatment support before actual treatment start', four, lambda c: c['diagnosis'].update(treatment_started_at=None)),
        ('pending diagnostic test with completed result timestamp', three, lambda c: c['diagnostic_tests'][0].update(result_at='2026-09-20T05:00:00+05:30')),
    ]
    for label, source, edit in mutations:
        mutated = copy.deepcopy(source)
        edit(mutated)
        errors = validate(mutated, schema)
        if errors:
            print('PASS invariant rejection', label)
        else:
            failures += 1
            print('FAIL invariant unexpectedly accepted', label)

    # Positively test the clinical-diagnosis pathway as well as bacteriological fixture.
    clinical = copy.deepcopy(four)
    clinical['diagnostic_tests'][0]['result'] = 'negative'
    clinical['diagnosis'].update(classification='clinically_diagnosed', supporting_test_ids=[],
                                  clinical_rationale='Synthetic treating clinician assessed full clinical evidence.',
                                  full_course_treatment_decided=True, treatment_plan_confirmed=True)
    errors = validate(clinical, schema)
    if errors:
        failures += 1
        print('FAIL constructed valid clinical diagnosis', *errors, sep='\n  ')
    else:
        print('PASS constructed clinical diagnosis (non-bacteriological)')

    print('\nM0 GATE:', 'PASS' if not failures else f'FAIL ({failures} unexpected outcomes)')
    return int(bool(failures))


if __name__ == '__main__':
    sys.exit(main())
