# PayFlow Ledger

A Flask service that receives PayFlow card webhooks and keeps per-account accounting:
how much is funded, blocked (pending), spent (captured) and refunded.

- `POST /webhooks`: receives signed PayFlow events.
- `GET /accounts/{account_id}/balance`: `available` and `pending`.
- `GET /accounts/{account_id}/transactions`: authorizations with their current state.
- `GET /health`: database check, plus Redis status (informational).

Stack: Python 3.12, Flask, PostgreSQL 16 (SQLAlchemy 2 + Alembic), Redis 7, gunicorn.

---

## 1. Running the service and the tests

```bash
docker compose up                # Postgres + Redis + app on http://localhost:8000
```

Migrations run automatically on start.

**Configuration and secrets.** The webhook secret and the Postgres credentials are read from environment variables. `docker-compose.yml` gives each one a default (`${VAR:-default}`) with the local/test values, including PayFlow's published test secret `whsec_test_123`. That's only so the service starts with one command, as the assignment asks. Normally these values would live only in a gitignored `.env` (or a secret manager), and the compose file would have no defaults. [`.env.example`](.env.example) lists the variables. To override them: `cp .env.example .env`, edit it, and `.env` wins over the defaults.

Check it with PayFlow's sender:

```bash
git clone https://github.com/mekasp/PayFlow.git ../PayFlow
python ../PayFlow/PayFlowEventsSender.py ../PayFlow/happy_path.json
curl localhost:8000/accounts/acc_1/balance
# {"account_id":"acc_1","currency":"USD","available":"585.00","pending":"15.00"}
```

**Tests** (against real Postgres and Redis, in a separate `payflow_test` database):

```bash
docker compose --profile test run --rm tests
```

This runs 127 tests with coverage, and fails below 90% (currently about 98%).
- `tests/unit`: money parsing, signatures, schemas, status derivation, the Redis shield and its circuit breaker.
- `tests/integration`: the HTTP contract, idempotency, every delivery order, lifecycle edge cases, concurrency and spam, replay, and migration/model drift.

**End-to-end** with the real `PayFlowEventsSender.py`, against the running service:

```bash
python scripts/e2e.py --sender ../PayFlow/PayFlowEventsSender.py
```

This delivers `happy_path.json` plus `scenarios/` (out of order, duplicates, edge cases) twice each, then checks every balance and transaction against `scenarios/expected.json`. It uses only the standard library.

**Replaying stored events** (see "quarantine" below):

```bash
docker compose exec app flask --app app events replay --status rejected   # or --status ignored, --type T, --id E
```

---

## 2. Assumptions (where the assignment doesn't say)

| Topic | Assumption |
|---|---|
| Who decides | PayFlow has already approved everything we hear about. We **record** facts and never refuse spending. `available` may therefore go negative. |
| Account visibility | The account row is created by whichever event mentions it first (in any order). The API returns 404 until the first `account.funded` arrives, matching "the first `account.funded` creates the account". |
| Currency | Pinned by the first event seen for the account. An event in another currency is quarantined. |
| One capture per authorization | As in the documented lifecycle. A repeat with the same amount is a no-op; a different amount is quarantined (we can't know which is right). |
| Capture vs. reversal | If PayFlow reports both for one authorization (a contradiction), **capture wins** in either arrival order, because money really moved. A reversal arriving after a capture is quarantined; a capture arriving after a reversal is applied and logged at ERROR. |
| Refunds | Verified PayFlow facts: all are counted (`refunded` = sum of all refunds, as specified). This includes refunds that arrive before their capture, or that total more than the captured amount; those are only logged at WARNING. A refund is identified by `refund_id`, so the same refund under a new event id counts once. |
| Unknown fields | Extra fields in known event types are ignored (forward compatibility). |
| Amount format | Non-negative decimal strings with at most 2 decimals (`"10"`, `"10.5"` and `"10.50"` are all fine). JSON numbers, exponents, signs and more than 2 decimals are rejected. We never silently round money. |
| `authorized_amount` | `null` in `/transactions` until `authorization.created` arrives (e.g. when the capture came first). `created_at` behaves the same way. |
| Ordering of `/transactions` | By the authorization's `created_at` ascending (or first-seen time while that's unknown), then id. |
| Read endpoints | Unauthenticated, no pagination (as the assignment allows). |

---

## 3. Key decisions and why

### 3.1 Idempotency: Postgres is the source of truth, Redis is a fail-open shield

PayFlow delivers **at least once**, possibly **in parallel**, so the same event can arrive many times, even simultaneously.

**The guarantee comes from Postgres.** Each event is claimed with
`INSERT INTO webhook_events ... ON CONFLICT (id) DO NOTHING RETURNING id`, **in the same transaction** that applies it to the ledger.
- If two copies race, the second insert blocks on the unique index until the first transaction ends.
- If the first committed, the second sees the conflict and answers `duplicate`.
- If the first crashed and rolled back, the second applies the event.
- "Seen" and "applied" commit together or not at all.

There is a test that crashes a handler mid-write and proves nothing is lost.

**Why not Redis alone (`SET NX`)?** Redis and Postgres can't share a transaction.
- **Mark first, then write.** A crash between the two leaves the event marked "seen" but never applied. The retry is told "duplicate" and the money is lost.
- **Write first, then mark.** A parallel copy can slip through between the two steps.
- **Redis restarts or evicts keys.** All the markers are gone.

**What Redis does do** (`app/services/shield.py`):
- **Done cache.** Written only *after* the Postgres commit. Duplicates are answered without touching the database, which matters when one event is being spammed.
  - The cached value is the payload's SHA-256, so a hit requires identical content.
  - A reused id with *different* content still reaches Postgres, where it's flagged (`duplicate_mismatch`, first version kept).
- **In-flight lock.** `SET NX PX` per event id. While one request processes an event, concurrent copies get `409` and PayFlow retries them later, when they hit the cache. A flood of copies doesn't hold DB connections. The lock is released with a compare-and-delete Lua script, so we never delete someone else's lock.
- **Fail-open with a circuit breaker.**
  - Any Redis error means "no cache, no lock", and the request goes to Postgres, which is fully correct on its own. The tests run with Redis on, off, and unreachable.
  - A failing Redis call can be slow: with the container stopped, every DNS lookup took about 3.3s, and requests approached PayFlow's 10s limit. So after one failure the shield skips Redis for 5s.

**Why the event id and not a payload hash as the dedup key?** PayFlow's contract is that a repeated delivery has the same `id`. A hash only matches identical content: a resend with a changed field, key order or whitespace would be applied twice. The hash is kept as an integrity check instead.

### 3.2 Out-of-order delivery: facts, not state transitions

Each authorization is one row keyed by `authorization_id`.
- **Each event type fills in only its own columns.** `created` sets the authorized amount and merchant, `captured` sets the captured amount, and `reversed` sets the reversal.
- **Status is derived from which facts exist:** captured, else reversed, else pending. It never depends on arrival order.

So `captured` arriving before `created` simply creates the row early; the late `created` fills in the rest on the *same* row.

Two kinds of test check this:
- a Hypothesis test delivers random permutations of the happy path (75 per run, out of 9! possible orders) and requires the exact expected result every time
- a randomized test checks shuffled, duplicated, parallel deliveries across several accounts against an independent reference model of the accounting rules

### 3.3 Balance computed at read time

`available = funded − pending − captured + refunded` is a single SQL statement of `SUM`s over rows that were each written exactly once. There are no running counters that could drift or race. The trade-off is read cost, which is fine at this scale (see section 5).

### 3.4 Concurrency: one lock per account

Every event transaction locks its account row (`SELECT ... FOR UPDATE`).
- Events of one account apply one at a time, so read-modify-write on authorization rows is safe.
- Different accounts run in parallel.
- Each transaction locks the event key and then exactly one account, always in that order, so deadlocks shouldn't happen. If one does (`40P01`/`40001`), it is retried.
- `statement_timeout` (5s) and `lock_timeout` (3s) keep every response under PayFlow's 10s limit.
- A DB that is down or slow returns `503`, so PayFlow retries later.

### 3.5 Response codes: only what a retry can't fix gets a non-2xx

PayFlow retries anything non-2xx for 72h, so status codes are chosen with that in mind:

| Situation | Response | Stored |
|---|---|---|
| Applied | `200 {"status":"ok","outcome":"applied"}` | yes |
| Duplicate (same id, or the same fact under a new id) | `200` `duplicate` | n/a |
| Same id, different content | `200` `duplicate_mismatch`, WARNING log | first version |
| Unknown event type | `200` `ignored` | yes, replayable |
| Signed but invalid data, wrong currency, or a contradiction | `200` `quarantined`, ERROR log | yes, with reason, replayable |
| Bad or missing signature | `401` | no |
| Not JSON / no `id` or `type` | `400` (we can't even dedupe it) | no |
| Body over 64 KB | `413` | no |
| Same event in flight elsewhere | `409` + `Retry-After` | n/a |
| DB down, timeout or pool exhausted | `503` | rolled back |

**Quarantine** means the event is stored with `status='rejected'` and a human-readable reason, changes no balance, and gets `200`, because a retry would only repeat the same bad data for 72 hours.

**Ignored and rejected events are stored on purpose.** After a `200` PayFlow never resends, so storing them is the only way to recover. Once a fix or a new handler ships, `flask events replay` re-applies them through the same code path.

### 3.6 Other choices

- **The signature is verified on the raw body**, before parsing, with `hmac.compare_digest`. Re-serialized JSON would not match.
- **Money is `Decimal` / `NUMERIC(18,2)` end to end**, never float.
- **Synchronous processing.** Applying an event is a few milliseconds of SQL, far under 10s, and reads are immediately consistent with what was acknowledged. Throughput comes from gunicorn (4 workers × 8 threads). A queue only becomes worth it under much bigger load (see section 5).
- **Layers:** `api/` (HTTP only) → `services/` (ingest, one handler module per event type, ledger queries, shield) → `models/` (tables).
  - `schemas/` (pydantic) validates incoming JSON. `core/` holds framework-free helpers.
  - Adding an event type means adding one handler module and one registry line.

---

## 4. Not done, on purpose

- **Async queue / worker.** Not needed at this scale, and it would make `GET` endpoints eventually consistent. See section 5 for when to add it.
- **Authentication on the `GET` endpoints, and pagination.** Out of scope per the assignment.
- **Multi-currency accounts.** The docs say one currency per account.
- **An admin UI or API for quarantined events.** The CLI plus SQL are enough here.
- **Metrics endpoint and alerting.** Logs are structured JSON with `event_id`, `event_type`, `outcome` and `duration_ms`, so they're ready to be turned into metrics.
- **Refunds detail in `/transactions`.** Only the per-authorization total is shown, as in the spec.

---

## 5. Before production I would

1. **Manage secrets properly.** Remove the defaults from `docker-compose.yml` and make the variables required (`${VAR:?}`), so nothing starts with test credentials. Keep the webhook secret in a secret manager and support **two active secrets** for rotation. Ask PayFlow for a **timestamp in the signature** to block replays of old signed requests.
2. **Add observability.** Metrics for events by outcome, latency, 409/503 rates and Redis breaker state. Alerts on any quarantined event, on refunds exceeding captures, and on anomalies such as a capture after a reversal.
3. **Reconcile.** Run a periodic job comparing our balances with PayFlow's API, if one exists. Webhooks alone can't prove we missed nothing.
4. **Scale the write path when needed.** Add an inbox table plus workers (ack fast, apply asynchronously, partitioned by account to keep per-account ordering cheap). Also keep materialized balance counters instead of `SUM` on every read.
5. **Plan for data growth.** Partition and archive `webhook_events`, with a retention policy that is longer than PayFlow's 72h retry window and meets audit needs.
6. **Make infrastructure highly available.** Managed Postgres with backups and PITR, Redis with a replica (it's only an optimization, but a flapping one adds latency), PgBouncer in front of Postgres.
7. **Harden the edge.** Rate limiting and IP allow-listing for PayFlow at the gateway, authentication on the read API, and request-id propagation in logs.
8. **Ship safely.** CI running lint, tests and the e2e script, plus migrations run as a separate deploy step rather than on container start.
