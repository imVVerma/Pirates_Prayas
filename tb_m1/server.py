"""Loopback-only HTTP receiver for M1. NOT authenticated or production safe."""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from store import CentralReceiver, InvalidCase, RevisionConflict

MAX_BYTES = 1024 * 1024   # Enforces portable case snapshots, not image binaries.
CASE_ROUTE = re.compile(r'^/v1/cases/([0-9a-fA-F-]{36})$')


def make_handler(receiver):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, code, value):
            raw = json.dumps(value).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if urlparse(self.path).path != '/v1/cases':
                return self.respond(404, {'error':'not_found'})
            if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                return self.respond(415, {'error':'application/json required'})
            try:
                size = int(self.headers.get('Content-Length','-1'))
            except ValueError:
                return self.respond(400, {'error':'invalid Content-Length'})
            if size < 0 or size > MAX_BYTES:
                return self.respond(413, {'error':'body missing or too large'})
            try:
                case = json.loads(self.rfile.read(size))
                ack = receiver.ingest(case)
                return self.respond(200 if ack['result']=='duplicate' else 201, ack)
            except RevisionConflict as exc:
                return self.respond(409, {'error':'revision_conflict','detail':str(exc)[:500]})
            except (ValueError, UnicodeError, InvalidCase, TypeError) as exc:
                return self.respond(422, {'error':'invalid_case','detail':str(exc)[:500]})

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/health':
                return self.respond(200, {'status':'ok','mode':'synthetic-only'})
            match = CASE_ROUTE.fullmatch(path)
            if match:
                case = receiver.latest(match.group(1))
                return self.respond(200, case) if case else self.respond(404, {'error':'not_found'})
            return self.respond(404, {'error':'not_found'})

        def log_message(self, fmt, *args):
            # Do not log case payloads/patient identifiers by default.
            return
    return Handler


def run(db_path, port=8765):
    receiver = CentralReceiver(db_path)
    with ThreadingHTTPServer(('127.0.0.1', port), make_handler(receiver)) as httpd:
        print(f'M1 synthetic-only receiver listening at http://127.0.0.1:{httpd.server_port}',flush=True)
        httpd.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='central.sqlite3')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    run(args.db, args.port)
