# M1 — durable store-and-forward engine (no UI edits)

**Scope:** Synthetic, pseudonymous hackathon cases only. This is a runnable backend **reference implementation**, not a deployed clinical service. The existing `intake-spine.html` and `tb-sync-layer.html` are intentionally untouched; connecting the former through an M0 adapter is M2.

## What exists

- `contract.py`: imports the **same** M0 schema + *combined* validator (schema and semantic invariants). Enforces exact +1 revision for later snapshots; stable case/patient identity and append-only `status_history`, `review_history`, `followups`.
- `store.py`: SQLite `LocalOutbox` and SQLite `CentralReceiver` backed by two **separate** databases (WAL). Each snapshot is uniquely identified by `(case_id,revision)` and a canonical-JSON SHA-256 hash. Local sync state, retry counts, and ACKs are **not** placed into the clinical case.
- `server.py`: minimal localhost HTTP `POST /v1/cases`, `GET /v1/cases/{uuid}`, `GET /health`. Validates every server ingress, accepts exact replay as `duplicate`, refuses modified same-revision payload with 409, and refuses invalid cases with 422. Payload <= 1 MiB; no diagnostic images are transferred.
- `client.py`: enqueue canonical JSON even without a server; manual sync when connectivity returns, retry transient network errors, ACK only for the **matching** ID/revision/hash, retain conflicts locally for investigation. Never send a later revision after a failed earlier one.
- `test_m1.py`: real localhost HTTP + SQLite restart and fault-injection integration tests, including the requested additional-test loop using the **same case ID**.

## Requirements / layout

Python 3.10+ and `jsonschema>=4.18,<5` (needed by the M0 validator). Unpack the ZIP so `tb_m0/` and `tb_m1/` are sibling folders. Do not duplicate/edit `tb_m0/case-schema.json` in other chats.

```bash
python -m pip install 'jsonschema>=4.18,<5'
cd tb_m0
python validate_cases.py
cd ../tb_m1
python -m unittest -v test_m1
```

## Manual demo (two terminals, any order)

Terminal 1, *while offline / before starting the receiver*:

```bash
cd tb_m1
python client.py --db demo-device.sqlite3 enqueue ../tb_m0/fixtures/01-symptoms-only.json
python client.py --db demo-device.sqlite3 status   # pending; survives process restart
```

Terminal 2:

```bash
cd tb_m1
python server.py --db demo-central.sqlite3 --port 8765
```

Terminal 1:

```bash
python client.py --db demo-device.sqlite3 sync
python client.py --db demo-device.sqlite3 status   # acked
# Re-sending exactly the same already-queued case does NOT create a new local entry:
python client.py --db demo-device.sqlite3 enqueue ../tb_m0/fixtures/01-symptoms-only.json
```

The test suite proves dropped-ACK replay and an additional-test return. It intentionally injects a one-time dropped ACK in the Python client **only for tests**, not as a UI button. Use `Ctrl+C` to stop the receiver. DB files remain on disk; to start a wholly fresh demo, use new DB filenames.

## Architecture decisions / boundaries

| Scenario | Behavior |
|---|---|
| Client offline / process restart | Local SQLite retains the exact JSON, revision and status `pending`. |
| Successful server insert | HTTP 201 with case_id, revision, content_hash, result `stored`. |
| Server committed but ACK was lost | Same HTTP request replay gets HTTP 200 `duplicate`; one central row. |
| Conflicting same-revision payload | HTTP 409, client marks `needs_attention`; **never** silently overwrite. |
| Later revision | Only `latest_revision+1`, preserves earlier snapshots and provenance. |
| Optional screening result returns | New revision of **same** `case_id`; `pending_additional_test -> ready_for_review`. |
| Bad case / missing data vs explicitly negative | M0 catches invalid clinical shape; unknown `null` is retained. HTTP 422; not silently repaired. |
| Local clinical stage / sync stage | `case_status` inside M0 snapshot, `sync_status` only in SQLite outbox. |

**Do not use real patient data.** No login, TLS, role-token verification, consent revocation, encryption-at-rest, retention policy, device identity, remote deployment, concurrency reconciliation UI or true browser IndexedDB has been built. HTTP binds to **127.0.0.1 only**; its read endpoint is for local synthetic testing. M0 actor labels are still claims, not authenticated permissions. M4 must enforce verified server-side roles before operational testing. M2 must connect actual intake output to canonical snapshots. This milestone does not validate a medical screening algorithm or confirm a TB diagnosis.
