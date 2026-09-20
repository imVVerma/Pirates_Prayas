"""M2 same-origin localhost intake bridge to M1's durable SQLite outbox.

NO cloud service or browser IndexedDB. This is offline *WAN* with a running
local Python process, NOT a browser-only PWA. Synthetic cases only.
"""
from __future__ import annotations
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tb_m1'))
from client import sync
from contract import canonical, digest
from intake_adapter import IntakeError, build_case
from store import LocalOutbox

ROOT = Path(__file__).resolve().parent
LEGACY_HTML = ROOT.parent / 'tb_audit' / 'intake-spine.html'
BRIDGE_JS = ROOT / 'intake_bridge.js'
MAX_BYTES = 32 * 1024  # Form fields only, not uploaded diagnostic images.


def make_handler(outbox, central_url):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, code, value):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(body)

        def response_bytes(self, data, mime):
            self.send_response(200)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(data)

        def same_origin(self):
            origin = self.headers.get('Origin')
            # No cross-site writes to this unauthenticated localhost demo.
            return origin is None or origin == ('http://' + self.headers.get('Host',''))

        def do_POST(self):
            if urlparse(self.path).path not in ('/v1/intake','/v1/sync'):
                return self.respond(404,{'error':'not_found'})
            if not self.same_origin():
                return self.respond(403,{'error':'cross_origin_request_forbidden'})
            if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                return self.respond(415,{'error':'application/json required'})
            try:
                size = int(self.headers.get('Content-Length','-1'))
            except ValueError:
                return self.respond(400,{'error':'invalid Content-Length'})
            if size < 0 or size > MAX_BYTES:
                return self.respond(413,{'error':'body missing or too large'})
            try:
                raw = json.loads(self.rfile.read(size))
                if urlparse(self.path).path == '/v1/sync':
                    if raw != {}:
                        return self.respond(422,{'error':'expected_empty_sync_request'})
                    outcomes = sync(outbox,central_url)
                    return self.respond(200,{'outcomes': [
                        {'case_id': c, 'revision': r, 'status': s} for c,r,s in outcomes],
                        'outbox':outbox.status()})
                case = build_case(raw)
                result = outbox.enqueue(case)
                return self.respond(201 if result == 'queued' else 200,
                                    {'result':result,'case':case,
                                     'content_hash':digest(canonical(case))})
            except (json.JSONDecodeError, UnicodeError) as exc:
                return self.respond(400,{'error':'malformed_json','detail':str(exc)[:500]})
            except IntakeError as exc:
                return self.respond(422,{'error':'invalid_intake','detail':str(exc)[:500]})
            except (ValueError, TypeError) as exc:
                # A valid new M0 snapshot with a previously-used case_id and
                # different content is a local same-revision conflict (not 500).
                return self.respond(409,{'error':'revision_conflict_or_bad_request',
                                         'detail':str(exc)[:500]})

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ('/','/intake'):
                html = LEGACY_HTML.read_text(encoding='utf-8')
                injected = '<script defer src="/intake_bridge.js"></script>\n</body>'
                if '</body>' not in html:
                    return self.respond(500,{'error':'missing_legacy_body_tag'})
                html = html.replace('</body>',injected,1)
                return self.response_bytes(html.encode('utf-8'),'text/html; charset=utf-8')
            if path == '/intake_bridge.js':
                return self.response_bytes(BRIDGE_JS.read_bytes(),'text/javascript; charset=utf-8')
            if path == '/v1/outbox':
                return self.respond(200,{'outbox':outbox.status()})
            if path == '/health':
                return self.respond(200,{'status':'ok','mode':'synthetic-local-device-only'})
            return self.respond(404,{'error':'not_found'})

        def log_message(self, fmt, *args):
            # No payloads, path parameters, or synthetic pseudonyms in logs.
            return
    return Handler


def run(db_path, port, central_url):
    outbox = LocalOutbox(db_path)
    with ThreadingHTTPServer(('127.0.0.1',port),make_handler(outbox,central_url)) as httpd:
        print('M2 synthetic-only intake running at '
              f'http://127.0.0.1:{httpd.server_port}/intake',flush=True)
        httpd.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='device.sqlite3')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--central-url',default='http://127.0.0.1:8765')
    args = parser.parse_args()
    run(args.db,args.port,args.central_url)
