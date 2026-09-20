"""M2 legacy-HTML -> frozen M0 snapshot adapter (synthetic, adult-only demo).

Only initial symptom-only submissions are accepted here. Test-available screenshots
lack capture provenance and MUST NOT be silently promoted to clinical evidence.
M3's verified adapter can attach tests in a later canonical M0 revision.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
from datetime import datetime
from uuid import UUID
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tb_m1'))
from contract import validate_or_raise

ALLOWED_FIELDS = frozenset({
    'case_id', 'created_at', 'consent_recorded_at', 'consent_confirmed',
    'synthetic_acknowledged', 'age', 'sex', 'location', 'cough_duration_days',
    'fever', 'night_sweats', 'weight_loss', 'xray_available', 'esr_available',
    'cough_present', 'raw_text', 'text_source', 'audio_recording_consent',
    'xray_report_claim', 'esr_report_claim',  # CHANGED M7.3 optional worker claims, NOT evidence
})

class IntakeError(ValueError):
    pass


def _utcaware(value, name):
    if not isinstance(value, str):
        raise IntakeError(f'{name} must be an ISO-8601 timestamp with offset')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise IntakeError(f'{name} must be an ISO-8601 timestamp with offset') from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise IntakeError(f'{name} requires timezone offset')
    return dt


def _signal(v, name):
    if v is not None and type(v) is not bool:
        raise IntakeError(f'{name} must be true, false or null (unknown)')
    return v


def _describe_symptom(label, value):
    if value is None:
        return f'{label}: unknown'
    return f'{label}: {"reported" if value else "not reported"}'


def deterministic_summary(symptoms, report_claims=None):  # CHANGED M7.3
    cough = symptoms['cough_present']
    if cough is None:
        text = 'cough: unknown'
    elif cough:
        text = (f'cough: reported ({symptoms["cough_duration_days"]} day(s))'
                if symptoms["cough_duration_days"] is not None else 'cough: reported (duration unknown)')  # CHANGED
    else:
        text = 'cough: not reported'
    parts = [text]
    parts.extend(_describe_symptom(label, symptoms[key]) for key, label in (
        ('fever', 'fever'), ('night_sweats', 'night sweats'), ('weight_loss', 'weight loss')))
    narrative = symptoms['raw_transcript']  # CHANGED: same verified-text path for typed/transcribed input
    narrative_part = ('\nWorker-entered narrative (verbatim, not AI-interpreted): ' + narrative) if narrative else ''
    report_note = ('\nWorker-reported report availability (UNVERIFIED, no test attached): '
        + f'X-ray={report_claims["xray"]}; ESR={report_claims["esr"]}.') if report_claims else ''
    return ('Structured symptom report: ' + '; '.join(parts) + '. '
            'Chest X-ray: not attached; ESR: not attached.' + report_note + narrative_part + '\n'
            'For qualified human review only; no TB diagnosis is stated.')


def build_case(raw):
    """A pure, deterministic transformation: identical request -> identical snapshot.

    The client sends created_at once at submission; it is not assigned again on
    retry. Case state is READY_FOR_REVIEW and revision=2; both initial status
    history entries share this timestamp, as M0 allows.
    """
    if not isinstance(raw, dict):
        raise IntakeError('intake payload must be a JSON object')
    unknown = set(raw) - ALLOWED_FIELDS
    missing = (ALLOWED_FIELDS - {'cough_present', 'raw_text', 'text_source', 'audio_recording_consent',
        'xray_report_claim', 'esr_report_claim'}) - set(raw)  # CHANGED M7.3 optional
    if unknown or missing:
        raise IntakeError(f'intake fields: unknown={sorted(unknown)} missing={sorted(missing)}')
    try:
        case_id = str(UUID(raw['case_id']))
    except (ValueError, TypeError, AttributeError) as exc:
        raise IntakeError('case_id must be a UUID') from exc
    if case_id != raw['case_id']:
        raise IntakeError('case_id must use canonical lower-case UUID form')
    if raw['consent_confirmed'] is not True:
        raise IntakeError('explicit collection and verifier-sharing consent is required')
    if raw['synthetic_acknowledged'] is not True:
        raise IntakeError('M2 accepts synthetic demo data only')
    created = _utcaware(raw['created_at'], 'created_at')
    consent = _utcaware(raw['consent_recorded_at'], 'consent_recorded_at')
    if consent > created:
        raise IntakeError('consent must be recorded before or at case creation')
    age = raw['age']
    if type(age) is not int or age < 18 or age > 120:
        raise IntakeError('age must be an adult integer from 18 to 120 (M0 scope)')
    sex = raw['sex']
    if not isinstance(sex, str) or sex not in ('male','female','other','not_recorded'):
        raise IntakeError('sex must use canonical M0 enum')
    location = raw['location']
    if not isinstance(location, str) or not re.fullmatch(r'DEMO-[A-Za-z0-9_-]{1,60}', location):
        raise IntakeError('location must be a synthetic code such as DEMO-AREA-A; do not submit real locations')
    cough_days = raw['cough_duration_days']
    if cough_days is not None and (type(cough_days) is not int or not 0 <= cough_days <= 36500):
        raise IntakeError('cough_duration_days must be a nonnegative integer or null')
    for name in ('fever','night_sweats','weight_loss'):
        _signal(raw[name],name)
    for name in ('xray_available','esr_available'):
        if type(raw[name]) is not bool:
            raise IntakeError(f'{name} must be boolean')
        if raw[name]:
            raise IntakeError(f'{name}: existing UI lacks capture/provenance metadata; wait for M3 adapter, do not fabricate evidence')
    # CHANGED M7.3: keep old M2 payload valid and accept explicit cough yes/no/unknown.
    cough_present = raw.get('cough_present', None if cough_days is None else cough_days > 0)
    _signal(cough_present, 'cough_present')
    if cough_present is not True and cough_days not in (None, 0):
        raise IntakeError('nonzero cough days conflict with cough absent/unknown')
    if cough_present is True and cough_days == 0:
        raise IntakeError('reported cough cannot have zero days; enter days or leave unknown')
    raw_text = raw.get('raw_text')
    if raw_text is not None and (not isinstance(raw_text, str) or len(raw_text) > 2500):
        raise IntakeError('raw_text must be text of at most 2500 characters')
    raw_text = raw_text.strip() if raw_text else None
    source = raw.get('text_source', 'text')
    if source not in ('text', 'voice'):
        raise IntakeError('text_source must be text or voice')
    audio_consent = raw.get('audio_recording_consent', False)
    if type(audio_consent) is not bool:
        raise IntakeError('audio_recording_consent must be boolean')
    if source == 'voice' and (not audio_consent or not raw_text):
        raise IntakeError('voice transcription needs explicit voice-processing consent and editable text')
    # CHANGED M7.3: nonclinical report claims survive in the human summary, never in evidence blocks.
    claims = None
    if 'xray_report_claim' in raw or 'esr_report_claim' in raw:
        claims = {'xray': raw.get('xray_report_claim', 'unknown'),
                  'esr': raw.get('esr_report_claim', 'unknown')}
        if any(v not in ('yes', 'no', 'unknown') for v in claims.values()):
            raise IntakeError('report claims must be yes, no or unknown')
    symptoms = {
        'cough_present': cough_present,
        'cough_duration_days': cough_days if cough_present is True and cough_days not in (None, 0) else None,
        'fever': raw['fever'], 'night_sweats': raw['night_sweats'],
        'weight_loss': raw['weight_loss'], 'source': source,
        'raw_transcript': raw_text, 'structured_at': raw['created_at'],
    }
    case = {
        'schema_version': '1.0.0', 'case_id': case_id, 'revision': 2,
        'created_at': raw['created_at'], 'case_status': 'ready_for_review',
        'patient': {'demographics': {'age': age, 'sex': sex, 'location': location},
                    'patient_ref': 'DEMO-PATIENT-' + case_id},
        'consent': {'data_collection': True, 'share_with_verifier': True,
                    'audio_recording': audio_consent, 'recorded_at': raw['consent_recorded_at']},  # CHANGED M7.3
        'symptom_screen': symptoms,
        'xray': {'available': False, 'image_ref': None, 'model_flag': None,
                 'model_confidence': None, 'heatmap_ref': None, 'model_id': None,
                 'captured_at': None},
        'esr': {'available': False, 'value': None, 'flag': None,
                'reference_range_used': None, 'captured_at': None},
        'case_summary': {'brief_text': deterministic_summary(symptoms, claims),
                         'generated_at': raw['created_at']},
        'review_history': [], 'routes': [], 'diagnostic_tests': [],
        'diagnosis': None,
        'asha_assignment': {'asha_id': None, 'assigned_at': None,
                            'support_phase': None, 'medicine_pickup_log': []},
        'followups': [],
        'status_history': [
            {'from': None, 'to': 'intake', 'at': raw['created_at'],
             'actor_id': 'demo-pharmacist-1', 'actor_role': 'pharmacist'},
            {'from': 'intake', 'to': 'ready_for_review', 'at': raw['created_at'],
             'actor_id': 'demo-pharmacist-1', 'actor_role': 'pharmacist'},
        ],
    }
    try:
        validate_or_raise(case)
    except ValueError as exc:
        raise IntakeError(f'M0 contract rejected intake: {exc}') from exc
    return case
