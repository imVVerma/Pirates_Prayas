"""Integrated two-process, synthetic-only frontend/API for M0–M6.5.

Device port serves the UNCHANGED intake HTML, the reused sync-page styling,
and same-origin proxies. Central port persists and advances canonical revisions.
Stop central process to exercise real network failure + durable M1 retries.
DO NOT expose either loopback server or use with patient information.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import mimetypes
import importlib.util
import json
import re
import sys
import sqlite3
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tb_m1'))
sys.path.insert(0,str(ROOT/'tb_m2'))
sys.path.insert(0,str(ROOT/'m6_5'))
from store import LocalOutbox, CentralReceiver, db_connection, RevisionConflict
from intake_adapter import IntakeError, build_case
from contract import canonical, digest
from device_server import make_handler as make_m2_handler
_spec = importlib.util.spec_from_file_location("tb_m1_http_server", ROOT / "tb_m1" / "server.py")
_m1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m1)
make_m1_handler = _m1.make_handler
from case_view import build_case_view
from workflow import apply, apply_evidence, REGISTRY
from intake_summary import summarize

HERE = Path(__file__).resolve().parent
UUID = r'[0-9a-fA-F-]{36}'
CENTRAL_CASE = re.compile(rf'^/v1/dashboard/cases/({UUID})$')
CENTRAL_ACTION = re.compile(rf'^/v1/dashboard/cases/({UUID})/actions$')
FIELD_REQUEST = re.compile(rf'^/v1/field/cases/({UUID})/requests$')
FIELD_EVIDENCE = re.compile(rf'^/v1/field/cases/({UUID})/evidence$')
MAX_EVIDENCE_BYTES = 6 * 1024 * 1024
MAX_ACTION_BYTES = 64 * 1024

LAB_REFERENCE_DB = ROOT / 'lab-reference-registry.sqlite3'

def _ensure_lab_reference_registry():
    with sqlite3.connect(LAB_REFERENCE_DB) as db:
        db.execute("CREATE TABLE IF NOT EXISTS lab_references (reference TEXT PRIMARY KEY, case_id TEXT NOT NULL, recorded_at TEXT NOT NULL)")

def _lab_reference_status(reference, case_id):
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError('reference_source is required for ESR evidence')
    reference = reference.strip()
    if not reference.startswith('DEMO-'):
        raise ValueError('reference_source must start with DEMO- in the synthetic prototype')
    _ensure_lab_reference_registry()
    with sqlite3.connect(LAB_REFERENCE_DB) as db:
        row = db.execute('SELECT case_id FROM lab_references WHERE reference=?', (reference,)).fetchone()
    if row and row[0] != case_id:
        raise ValueError(f'lab report reference already belongs to another case: {reference}')
    return reference

def _record_lab_reference(reference, case_id):
    reference = reference.strip()
    _ensure_lab_reference_registry()
    with sqlite3.connect(LAB_REFERENCE_DB) as db:
        db.execute(
            'INSERT OR IGNORE INTO lab_references(reference,case_id,recorded_at) VALUES(?,?,?)',
            (reference, case_id, datetime.now(timezone.utc).isoformat())
        )



def _field_request(case):
    latest_review = case['review_history'][-1] if case['review_history'] else None
    requested = [] if not latest_review else list(latest_review.get('requested_tests', []))
    pending = [name for name in requested if not case[name]['available']]
    return {
        'case_id': case['case_id'],
        'revision': case['revision'],
        'case_status': case['case_status'],
        'requested_tests': requested,
        'pending_tests': pending,
        'has_request': case['case_status'] == 'pending_additional_test' and bool(pending),
        'summary': case['case_summary']['brief_text'],
        'screening': {
            'xray_available': case['xray']['available'],
            'esr_available': case['esr']['available'],
        },
    }


def _save_uploaded_xray(case_id, payload, evidence_root):
    if not isinstance(payload, dict):
        raise ValueError('xray upload must be an object')
    filename = str(payload.get('filename', 'xray.bin'))
    mime = str(payload.get('mime_type', ''))
    if mime not in ('image/png', 'image/jpeg'):
        raise ValueError('X-ray upload must be PNG or JPEG')
    encoded = payload.get('content_base64')
    if not isinstance(encoded, str) or not encoded:
        raise ValueError('X-ray upload content is missing')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError('invalid X-ray base64 payload') from exc
    if not raw or len(raw) > MAX_EVIDENCE_BYTES:
        raise ValueError('X-ray upload is empty or exceeds 6 MB')
    digest = hashlib.sha256(raw).hexdigest()
    ext = '.png' if mime == 'image/png' else '.jpg'
    folder = Path(evidence_root) / case_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{digest}{ext}'
    if not path.exists():
        path.write_bytes(raw)
    return f'local-evidence://{case_id}/{digest}{ext}', digest


def _summary_payload(raw):
    if not isinstance(raw, dict):
        raise ValueError('summary body must be a JSON object')
    structured = raw.get('structured') or {}
    if not isinstance(structured, dict):
        raise ValueError('structured summary inputs must be an object')
    text = raw.get('raw_text')
    if text is not None and not isinstance(text, str):
        raise ValueError('raw_text must be text or null')
    return summarize(text, structured)


def central_handler(receiver):
    Base = make_m1_handler(receiver)

    class Handler(Base):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/v1/dashboard/cases':
                with db_connection(receiver.path) as db:
                    rows = db.execute('''SELECT c.payload FROM cases c JOIN
                        (SELECT case_id, MAX(revision) r FROM cases GROUP BY case_id) l
                        ON l.case_id=c.case_id AND l.r=c.revision
                        ORDER BY c.received_at DESC, c.case_id LIMIT 250''').fetchall()
                summaries=[]
                for row in rows:
                    c=json.loads(row['payload']); v=build_case_view(c)
                    summaries.append({'case_id':c['case_id'],'revision':c['revision'],
                                      'case_status':c['case_status'],
                                      'location':v['patient']['location'],
                                      'current_stage':v['current_stage']})
                return self.respond(200,{'cases':summaries})
            match=CENTRAL_CASE.fullmatch(path)
            if match:
                case=receiver.latest(match.group(1))
                return self.respond(200,{'case':case,'view':build_case_view(case)}) if case else self.respond(404,{'error':'case_not_found'})
            match=FIELD_REQUEST.fullmatch(path)
            if match:
                case=receiver.latest(match.group(1))
                return self.respond(200,_field_request(case)) if case else self.respond(404,{'error':'case_not_found'})
            if path == '/v1/dashboard/sites':
                return self.respond(200,{'sites':[{'site_id':s.site_id,'area':s.area,
                    'purposes':sorted(s.purposes),'capacity_available':s.capacity_available,
                    'reachable':s.reachable,'estimated_travel_minutes':s.estimated_travel_minutes}
                    for s in REGISTRY.sites.values()]})
            return super().do_GET()

        def do_POST(self):
            path=urlparse(self.path).path
            evidence_match=FIELD_EVIDENCE.fullmatch(path)
            if evidence_match:
                if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                    return self.respond(415,{'error':'application/json required'})
                try:
                    length=int(self.headers.get('Content-Length','-1'))
                    if length < 0 or length > MAX_EVIDENCE_BYTES:
                        return self.respond(413,{'error':'invalid evidence size'})
                    raw=json.loads(self.rfile.read(length))
                    current=receiver.latest(evidence_match.group(1))
                    if current is None:
                        return self.respond(404,{'error':'case_not_found'})
                    evidence=raw.copy()
                    lab_reference=None
                    if evidence.get('evidence_type') == 'xray':
                        ref,_= _save_uploaded_xray(current['case_id'], evidence.get('upload'), ROOT/'demo-evidence')
                        evidence['image_ref']=ref
                        evidence.pop('upload',None)
                    elif evidence.get('evidence_type') == 'esr':
                        lab_reference=_lab_reference_status(evidence.get('reference_source'), current['case_id'])
                    next_case=apply_evidence(current,evidence)
                    if next_case['revision'] == current['revision']:
                        return self.respond(200,{'result':'already_recorded','case':current,'view':build_case_view(current)})
                    ack=receiver.ingest(next_case)
                    if lab_reference:
                        _record_lab_reference(lab_reference, current['case_id'])
                    return self.respond(201,{'result':ack['result'],'case':next_case,
                                             'view':build_case_view(next_case),'request':_field_request(next_case)})
                except RevisionConflict as exc:
                    return self.respond(409,{'error':'revision_conflict','detail':str(exc)[:700]})
                except (ValueError,TypeError,KeyError,IndexError,UnicodeError) as exc:
                    return self.respond(422,{'error':'evidence_rejected','detail':str(exc)[:700]})
            if path == '/v1/intake/summary':
                if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                    return self.respond(415,{'error':'application/json required'})
                try:
                    length=int(self.headers.get('Content-Length','-1'))
                    if length < 0 or length > 32*1024:
                        return self.respond(413,{'error':'invalid summary size'})
                    return self.respond(200,_summary_payload(json.loads(self.rfile.read(length))))
                except (ValueError,TypeError,UnicodeError,json.JSONDecodeError) as exc:
                    return self.respond(422,{'error':'summary_failed','detail':str(exc)[:500]})
            match=CENTRAL_ACTION.fullmatch(path)
            if not match:
                return super().do_POST()
            if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                return self.respond(415,{'error':'application/json required'})
            try:
                length=int(self.headers.get('Content-Length','-1'))
            except ValueError:
                return self.respond(400,{'error':'invalid Content-Length'})
            if length < 0 or length > MAX_ACTION_BYTES:
                return self.respond(413,{'error':'invalid action size'})
            try:
                raw=json.loads(self.rfile.read(length))
                current=receiver.latest(match.group(1))
                if current is None:
                    return self.respond(404,{'error':'case_not_found'})
                next_case=apply(current,raw)
                if next_case['revision'] == current['revision']:
                    return self.respond(200,{'result':'already_recorded','case':current,
                                             'view':build_case_view(current)})
                ack=receiver.ingest(next_case)
                return self.respond(201,{'result':ack['result'],'case':next_case,
                                         'view':build_case_view(next_case)})
            except RevisionConflict as exc:
                return self.respond(409,{'error':'revision_conflict','detail':str(exc)[:700]})
            except (ValueError,TypeError,KeyError,IndexError,UnicodeError) as exc:
                return self.respond(422,{'error':'action_rejected','detail':str(exc)[:700]})
    return Handler


def _local_latest(outbox, case_id):
    with db_connection(outbox.path) as db:
        row=db.execute('SELECT payload FROM outbox WHERE case_id=? ORDER BY revision DESC LIMIT 1',(case_id,)).fetchone()
    return json.loads(row['payload']) if row else None


def device_handler(outbox,central_url):
    Base=make_m2_handler(outbox,central_url)
    central_url=central_url.rstrip('/')

    def nav(text):
        return ('<nav style="padding:10px 24px;background:#fff;border-bottom:1px solid #ddd;font:14px sans-serif">'
                '<a href="/field">Field intake</a> &nbsp;·&nbsp; '
                '<a href="/field/cases">My cases</a> &nbsp;·&nbsp; '
                '<a href="/intake">Legacy intake</a> &nbsp;·&nbsp; '
                '<a href="/sync">Store & forward / verifier workbench</a> &nbsp;·&nbsp; '
                '<strong>DEMO — SYNTHETIC DATA ONLY</strong> &nbsp; '+text+'</nav>')

    def remote(method,path,body=None):
        uri=central_url+path
        req=Request(uri,data=(json.dumps(body,allow_nan=False).encode('utf-8') if body is not None else None),
                    headers={'Content-Type':'application/json'},method=method)
        try:
            with urlopen(req,timeout=2.5) as r:
                return r.status,json.loads(r.read(1024*1024))
        except HTTPError as exc:
            try: data=json.loads(exc.read(1024*1024))
            except (ValueError,UnicodeError): data={'error':'central_invalid_response'}
            return exc.code,data
        except (URLError,TimeoutError,OSError):
            return 503,{'error':'central_receiver_unavailable',
                        'detail':'Cases remain in local SQLite. Start central receiver then retry sync.'}

    class Handler(Base):
        def do_GET(self):
            path=urlparse(self.path).path
            # CHANGED M7.3: the worker UX is a separate thin skin over the same M2 API.
            if path in ('/field', '/field/'):
                html=(HERE/'field_intake.html').read_text(encoding='utf-8')
                return self.response_bytes(html.encode('utf-8'),'text/html; charset=utf-8')
            if path == '/field/cases':
                html=(HERE/'field_cases.html').read_text(encoding='utf-8')
                return self.response_bytes(html.encode('utf-8'),'text/html; charset=utf-8')
            if path in ('/field_intake.js','/field_cases.js'):
                return self.response_bytes((HERE/path.lstrip('/')).read_bytes(),'text/javascript; charset=utf-8')
            if path in ('/','/intake'):
                # M2 injects its original working bridge; augment only navigation.
                html=(ROOT/'tb_audit'/'intake-spine.html').read_text(encoding='utf-8')
                html=html.replace('<body>','<body>'+nav(''),1)
                html=html.replace('</body>','<script defer src="/intake_bridge.js"></script>\n</body>',1)
                return self.response_bytes(html.encode('utf-8'),'text/html; charset=utf-8')
            if path in ('/sync','/workbench'):
                html=(ROOT/'tb_audit'/'tb-sync-layer.html').read_text(encoding='utf-8')
                html=re.sub(r'<script>\s*\(function\(\) \{.*?</script>',
                            '<script defer src="/app_sync.js"></script>',html,flags=re.S)
                html=html.replace('<body>','<body>'+nav(''),1)
                html=html.replace('Toggle "Go online" above to trigger a sync pass on the queued cases.',
                                  'The device and central receiver run as separate loopback processes. '
                                  'Stop the central receiver to demonstrate loss of connectivity; '
                                  'the outbox stays in SQLite. Sync status is NOT a clinical status.')
                html=html.replace('fully usable offline — nothing blocks on connectivity.',
                                  'saved while the local Python service remains running, even if the central receiver is down.')
                html=html.replace('A background sync trigger checks connectivity opportunistically;',
                                  'The operator retries sync when connectivity returns;')
                html=html.replace('</main>', '''<section class="panel" style="grid-column:1/-1">
                    <h2>Qualified reviewer / laboratory / ASHA — synthetic workbench</h2>
                    <p class="sub">Select a synced case above. All actions require an explicit click; server uses fixed demo actors. No automatic clinical decisions.</p>
                    <div id="caseWorkbench">Select a synced case to inspect the M6.5 read model.</div>
                    </section></main>''',1)
                return self.response_bytes(html.encode('utf-8'),'text/html; charset=utf-8')
            if path == '/app_sync.js':
                return self.response_bytes((HERE/'app_sync.js').read_bytes(),'text/javascript; charset=utf-8')
            if path in ('/v1/dashboard/cases','/v1/dashboard/sites') or CENTRAL_CASE.fullmatch(path) or FIELD_REQUEST.fullmatch(path):
                code,result=remote('GET',path)
                return self.respond(code,result)
            if path=='/v1/dashboard/health':
                code,result=remote('GET','/health')
                return self.respond(code,result)
            return super().do_GET()

        def do_POST(self):
            path=urlparse(self.path).path
            if path == '/v1/intake':
                if not self.same_origin():
                    return self.respond(403,{'error':'cross_origin_request_forbidden'})
                if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                    return self.respond(415,{'error':'application/json required'})
                try:
                    length=int(self.headers.get('Content-Length','-1'))
                    if length < 0 or length > 32*1024:
                        return self.respond(413,{'error':'body missing or too large'})
                    raw=json.loads(self.rfile.read(length))
                    case=build_case(raw)
                    structured={
                        'cough_present':case['symptom_screen']['cough_present'],
                        'cough_duration_days':case['symptom_screen']['cough_duration_days'],
                        'fever':case['symptom_screen']['fever'],
                        'night_sweats':case['symptom_screen']['night_sweats'],
                        'weight_loss':case['symptom_screen']['weight_loss'],
                    }
                    result=summarize(case['symptom_screen']['raw_transcript'],structured)
                    case['case_summary']={'brief_text':result['summary']+'\nFor qualified human review only; no TB diagnosis is stated.',
                                          'generated_at':case['created_at']}
                    queue_result=outbox.enqueue(case)
                    return self.respond(201 if queue_result == 'queued' else 200,
                                        {'result':queue_result,'case':case,'summary':result,
                                         'content_hash':digest(canonical(case))})
                except (IntakeError,ValueError,TypeError,KeyError,UnicodeError) as exc:
                    return self.respond(422,{'error':'invalid_intake','detail':str(exc)[:500]})
            if path == '/v1/intake/summary':
                if not self.same_origin():
                    return self.respond(403,{'error':'cross_origin_request_forbidden'})
                try:
                    length=int(self.headers.get('Content-Length','-1'))
                    if length < 0 or length > 32*1024:
                        return self.respond(413,{'error':'invalid summary size'})
                    return self.respond(200,_summary_payload(json.loads(self.rfile.read(length))))
                except (ValueError,TypeError,UnicodeError,json.JSONDecodeError) as exc:
                    return self.respond(422,{'error':'summary_failed','detail':str(exc)[:500]})
            evidence_match=FIELD_EVIDENCE.fullmatch(path)
            if evidence_match:
                if not self.same_origin():
                    return self.respond(403,{'error':'cross_origin_request_forbidden'})
                if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                    return self.respond(415,{'error':'application/json required'})
                try:
                    length=int(self.headers.get('Content-Length','-1'))
                    if length < 0 or length > MAX_EVIDENCE_BYTES:
                        return self.respond(413,{'error':'invalid evidence size'})
                    raw=json.loads(self.rfile.read(length))
                    case_id=evidence_match.group(1)
                    code,current=remote('GET',f'/v1/dashboard/cases/{case_id}')
                    if code == 200:
                        central_case=current['case']
                        # Pull the latest central revision into the local durable queue first.
                        outbox.enqueue(central_case)
                    else:
                        central_case=_local_latest(outbox,case_id)
                        if central_case is None:
                            return self.respond(code,current)
                    evidence=dict(raw)
                    lab_reference=None
                    if evidence.get('evidence_type') == 'xray':
                        ref,file_digest=_save_uploaded_xray(case_id,evidence.get('upload'),ROOT/'demo-evidence')
                        evidence['image_ref']=ref
                        evidence.pop('upload',None)
                    elif evidence.get('evidence_type') == 'esr':
                        lab_reference=_lab_reference_status(evidence.get('reference_source'), case_id)
                    evidence['expected_revision']=central_case['revision']
                    next_case=apply_evidence(central_case,evidence)
                    outbox.enqueue(next_case)
                    if lab_reference:
                        _record_lab_reference(lab_reference, case_id)
                    sync_code,sync_result=remote('GET','/health')
                    if sync_code == 200:
                        try:
                            from client import sync
                            outcomes=sync(outbox,central_url)
                        except Exception:
                            outcomes=[]
                    else:
                        outcomes=[]
                    return self.respond(201,{'result':'queued','case':next_case,
                                             'view':build_case_view(next_case),
                                             'request':_field_request(next_case),
                                             'sync_outcomes':[{'case_id':c,'revision':r,'status':s} for c,r,s in outcomes]})
                except RevisionConflict as exc:
                    return self.respond(409,{'error':'revision_conflict','detail':str(exc)[:700]})
                except (ValueError,TypeError,KeyError,IndexError,UnicodeError) as exc:
                    return self.respond(422,{'error':'evidence_rejected','detail':str(exc)[:700]})
            match=CENTRAL_ACTION.fullmatch(path)
            if not match:
                return super().do_POST()
            if not self.same_origin():
                return self.respond(403,{'error':'cross_origin_request_forbidden'})
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                return self.respond(415,{'error':'application/json required'})
            try: length=int(self.headers.get('Content-Length','-1'))
            except ValueError: return self.respond(400,{'error':'invalid Content-Length'})
            if length<0 or length>MAX_ACTION_BYTES:
                return self.respond(413,{'error':'invalid action size'})
            try: raw=json.loads(self.rfile.read(length))
            except (ValueError,UnicodeError):return self.respond(400,{'error':'malformed_json'})
            code,result=remote('POST',path,raw)
            return self.respond(code,result)
    return Handler


def run(mode,db_path,port,central_url):
    _ensure_lab_reference_registry()
    if mode=='central':
        store=CentralReceiver(db_path)
        handler=central_handler(store)
    else:
        store=LocalOutbox(db_path)
        handler=device_handler(store,central_url)
    with ThreadingHTTPServer(('127.0.0.1',port),handler) as server:
        print(f'{mode} synthetic-only server http://127.0.0.1:{server.server_port}/'+('field' if mode=='device' else 'health'),flush=True)
        server.serve_forever()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['central','device'])
    parser.add_argument('--db',default=None)
    parser.add_argument('--port',type=int,default=None)
    parser.add_argument('--central-url',default='http://127.0.0.1:8765')
    opts=parser.parse_args()
    run(opts.mode,opts.db or ('central.sqlite3' if opts.mode=='central' else 'device.sqlite3'),
        opts.port or (8765 if opts.mode=='central' else 8766),opts.central_url)
