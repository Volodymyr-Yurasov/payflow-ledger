"""End-to-end check against a running service. See README.md for how to run it.

Delivers tests/fixtures/happy_path.json and every scenario in scenarios/ through the
given sender script (signed, with retries), then checks balances and transactions against
scenarios/expected.json. Each scenario uses its own account, so the script is safe to
run repeatedly: re-delivery must not change anything (idempotency).
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = {
    "happy_path": ROOT / "tests" / "fixtures" / "happy_path.json",
    "out_of_order": ROOT / "scenarios" / "out_of_order.json",
    "duplicates": ROOT / "scenarios" / "duplicates.json",
    "edge_cases": ROOT / "scenarios" / "edge_cases.json",
}


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def check_account(base_url: str, account_id: str, expected: dict) -> list[str]:
    errors = []
    balance = get_json(f"{base_url}/accounts/{account_id}/balance")
    for field, value in expected["balance"].items():
        if balance[field] != value:
            errors.append(f"{account_id} {field}: expected {value}, got {balance[field]}")

    items = get_json(f"{base_url}/accounts/{account_id}/transactions")["items"]
    actual = {
        item["authorization_id"]: [
            item["status"],
            item["authorized_amount"],
            item["captured_amount"],
            item["refunded_amount"],
        ]
        for item in items
    }
    if actual != expected["transactions"]:
        errors.append(f"{account_id} transactions:\n  expected {expected['transactions']}"
                      f"\n  got      {actual}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sender", required=True, help="path to the event sender script")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--rounds", type=int, default=2,
                        help="deliver every scenario this many times (idempotency)")
    args = parser.parse_args()

    expected = json.loads((ROOT / "scenarios" / "expected.json").read_text(encoding="utf-8"))
    failures = []
    for name, path in SCENARIOS.items():
        for round_ in range(1, args.rounds + 1):
            print(f"== {name} (round {round_})", flush=True)
            result = subprocess.run(
                [sys.executable, args.sender, str(path), "--url", f"{args.base_url}/webhooks"],
                capture_output=True, text=True,
            )
            print(result.stdout.strip().splitlines()[-1] if result.stdout else result.stderr)
            if result.returncode != 0:
                failures.append(f"{name}: sender failed\n{result.stdout}\n{result.stderr}")
            for account_id, account_expected in expected[name].items():
                failures += check_account(args.base_url, account_id, account_expected)

    if failures:
        print("\nFAILED:\n" + "\n".join(failures))
        return 1
    print("\nAll scenarios match the expected balances and transactions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
