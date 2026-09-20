"""Durable client outbox: submit canonical M0 snapshots and replay until ACK."""
import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from store import LocalOutbox


def sync(outbox, url, *, drop_ack_once=False):
    """Once per invocation; caller schedules retrials when connectivity returns.

    drop_ack_once is TEST-ONLY fault injection: the server commits, while the
    client acts as if the successful response was lost before local ACK.
    """
    outcomes = []
    for row in outbox.pending():
        case_id, rev = row['case_id'], row['revision']
        outbox.record_attempt(case_id, rev)
        request = Request(url.rstrip('/') + '/v1/cases', row['payload'].encode('utf-8'),
                          {'Content-Type':'application/json'}, method='POST')
        try:
            with urlopen(request, timeout=3) as response:
                ack = json.load(response)
            if drop_ack_once:
                drop_ack_once = False
                outbox.error(case_id, rev, 'TEST ONLY: ACK intentionally dropped; safe to retry')
                outcomes.append((case_id,rev,'ack_lost_retry'))
                # Avoid trying a later revision before this one's acknowledgement.
                break
            if (ack.get('case_id'), ack.get('revision'), ack.get('content_hash')) != (case_id,rev,row['content_hash']):
                outbox.error(case_id, rev, 'untrusted/mismatched ACK', needs_attention=True)
                outcomes.append((case_id,rev,'needs_attention'))
                break
            outbox.acknowledge(case_id, rev, row['content_hash'])
            outcomes.append((case_id,rev,ack['result']))
        except HTTPError as exc:
            detail = exc.read(500).decode('utf-8','replace')
            outbox.error(case_id, rev, f'HTTP {exc.code}: {detail}', needs_attention=exc.code in (409, 422))
            outcomes.append((case_id,rev,'needs_attention' if exc.code in (409,422) else 'retry_later'))
            # Never send later revisions after an unacknowledged earlier revision.
            break
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            outbox.error(case_id, rev, f'transport/ACK failure: {exc}')
            outcomes.append((case_id,rev,'retry_later'))
            break
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='local.sqlite3')
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    subs = parser.add_subparsers(dest='command',required=True)
    p = subs.add_parser('enqueue', help='persist a canonical M0 case, even while offline')
    p.add_argument('case_json',type=Path)
    subs.add_parser('sync', help='send pending snapshots; rerun after reconnection')
    subs.add_parser('status', help='show sync metadata only (not medical payload)')
    args = parser.parse_args()
    outbox = LocalOutbox(args.db)
    if args.command == 'enqueue':
        try:
            print(outbox.enqueue(json.loads(args.case_json.read_text(encoding='utf-8'))))
        except (ValueError, OSError) as exc:
            print('ENQUEUE FAILED:',exc,file=sys.stderr)
            return 1
    elif args.command == 'sync':
        for entry in sync(outbox,args.url):
            print(*entry)
    else:
        for row in outbox.status():
            print(json.dumps(row))
    return 0


if __name__ == '__main__':
    sys.exit(main())
