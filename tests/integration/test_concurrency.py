"""Parallel delivery: spam of one event, racing lifecycle events, and a randomized
end-to-end check against an independent reference model."""

from __future__ import annotations

import itertools
import random
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.helpers import captured, created, funded, post_event, refund, reversed_, snapshot

pytestmark = pytest.mark.concurrency


def fire(app, events, workers=32):
    """Deliver all events at once from a thread pool, like parallel PayFlow deliveries."""

    def deliver(event):
        response = post_event(app.test_client(), event)
        return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(deliver, events))


def deliver_until_acknowledged(app, events):
    """Parallel first attempt, then retry anything non-2xx, as PayFlow would."""
    pending = list(events)
    for _ in range(10):
        results = fire(app, pending)
        assert all(code in (200, 409) for code, _ in results), results
        pending = [e for e, (code, _) in zip(pending, results, strict=True) if code != 200]
        if not pending:
            return
    raise AssertionError(f"{len(pending)} events never acknowledged")


def test_spammed_event_is_applied_exactly_once(app, client, db):
    event = funded("evt_spam", "100.00")
    results = fire(app, [event] * 100)

    codes = Counter(code for code, _ in results)
    assert set(codes) <= {200, 409}, codes
    outcomes = Counter(body["outcome"] for code, body in results if code == 200)
    assert outcomes["applied"] == 1
    assert db("SELECT count(*) FROM fundings") == [(1,)]

    # PayFlow retries the 409s later: by then they're plain duplicates.
    assert post_event(client, event).get_json()["outcome"] == "duplicate"
    assert snapshot(client)[0]["available"] == "100.00"


def test_spam_without_redis_relies_on_postgres_alone(app_without_redis, db):
    event = funded("evt_spam", "100.00")
    results = fire(app_without_redis, [event] * 100)

    assert all(code == 200 for code, _ in results)
    outcomes = Counter(body["outcome"] for _, body in results)
    assert outcomes == {"applied": 1, "duplicate": 99}
    assert db("SELECT count(*) FROM fundings") == [(1,)]


@pytest.mark.parametrize("round_", range(10))
def test_racing_lifecycle_events_converge(app, client, round_):
    events = [
        funded("evt_1", "1000.00"),
        created("evt_2", "auth_1", "90.00"),
        captured("evt_3", "auth_1", "100.00"),
        refund("evt_4", "re_1", "auth_1", "10.00"),
        refund("evt_5", "re_2", "auth_1", "20.00"),
        refund("evt_6", "re_3", "auth_1", "5.00"),
    ]
    deliveries = events * 3
    random.Random(round_).shuffle(deliveries)
    deliver_until_acknowledged(app, deliveries)

    balance, [item] = snapshot(client)
    assert balance["available"] == "935.00"
    assert balance["pending"] == "0.00"
    assert (item["status"], item["authorized_amount"], item["captured_amount"],
            item["refunded_amount"]) == ("captured", "90.00", "100.00", "35.00")


# --- randomized check against a reference model ------------------------------------


def generate_events(rng: random.Random, accounts: int = 8) -> list[dict]:
    ids = itertools.count(1)
    clock = itertools.count()
    start = datetime(2026, 10, 19, tzinfo=UTC)

    def eid():
        return f"evt_{next(ids):05d}"

    def at():
        return (start + timedelta(minutes=next(clock))).isoformat().replace("+00:00", "Z")

    def money(low, high):
        return str(Decimal(rng.randint(low * 100, high * 100)) / 100)

    events = []
    for a in range(accounts):
        common = {"account": f"acc_{a}", "currency": rng.choice(["USD", "EUR", "UAH"])}
        for _ in range(rng.randint(1, 3)):
            events.append(funded(eid(), money(100, 2000), at=at(), **common))
        for k in range(rng.randint(0, 6)):
            auth, amount = f"auth_{a}_{k}", money(1, 300)
            events.append(created(eid(), auth, amount, merchant=f"m{k}", at=at(), **common))
            fate = rng.choice(["pending", "captured", "captured", "reversed"])
            if fate == "captured":
                events.append(captured(eid(), auth, money(1, 400), at=at(), **common))
                for r in range(rng.randint(0, 2)):
                    events.append(
                        refund(eid(), f"re_{a}_{k}_{r}", auth, money(1, 50), at=at(), **common)
                    )
            elif fate == "reversed":
                events.append(reversed_(eid(), auth, amount, at=at(), **common))
    return events


def reference_state(events: list[dict]) -> dict[str, tuple[dict, list[dict]]]:
    """Straightforward model of the accounting rules, written independently of the app."""
    fmt = lambda d: str(d.quantize(Decimal("0.01")))  # noqa: E731
    currency, funded_total, refunded_total = {}, defaultdict(Decimal), defaultdict(Decimal)
    auths, refunded_by_auth = {}, defaultdict(Decimal)

    for e in events:
        d = e["data"]
        account, amount = d["account_id"], Decimal(d["amount"])
        currency[account] = d["currency"]
        if e["type"] == "account.funded":
            funded_total[account] += amount
        elif e["type"] == "refund.created":
            refunded_total[account] += amount
            refunded_by_auth[d["authorization_id"]] += amount
        else:
            auth = auths.setdefault(d["authorization_id"], {"account": account})
            if e["type"] == "authorization.created":
                auth.update(authorized=amount, merchant=d["merchant"], created_at=e["created_at"])
            elif e["type"] == "authorization.captured":
                auth["captured"] = amount
            elif e["type"] == "authorization.reversed":
                auth["reversed"] = True

    state = {}
    for account in currency:
        mine = sorted(
            ((i, a) for i, a in auths.items() if a["account"] == account),
            key=lambda pair: pair[1]["created_at"],
        )
        pending = sum(
            (a["authorized"] for _, a in mine if "captured" not in a and "reversed" not in a),
            Decimal(0),
        )
        spent = sum((a.get("captured", Decimal(0)) for _, a in mine), Decimal(0))
        available = funded_total[account] - pending - spent + refunded_total[account]
        balance = {"account_id": account, "currency": currency[account],
                   "available": fmt(available), "pending": fmt(pending)}
        items = [
            {
                "authorization_id": auth_id,
                "merchant": a["merchant"],
                "currency": currency[account],
                "status": "captured" if "captured" in a
                else "reversed" if "reversed" in a else "pending",
                "authorized_amount": fmt(a["authorized"]),
                "captured_amount": fmt(a.get("captured", Decimal(0))),
                "refunded_amount": fmt(refunded_by_auth[auth_id]),
                "created_at": a["created_at"],
            }
            for auth_id, a in mine
        ]
        state[account] = (balance, items)
    return state


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_shuffled_duplicated_parallel_delivery_matches_reference(app, client, seed):
    rng = random.Random(seed)
    events = generate_events(rng)
    deliveries = events + rng.sample(events, k=len(events) * 3 // 10)
    rng.shuffle(deliveries)

    deliver_until_acknowledged(app, deliveries)

    for account, expected in reference_state(events).items():
        assert snapshot(client, account) == expected, account
