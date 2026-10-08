"""Run periodically (e.g. every five minutes) as an independent Railway job.

    uv run python -m app.reconcile          # report only
    uv run python -m app.reconcile --apply  # repair confirmed stale holds
"""

import argparse
import asyncio

from .payments import reconcile


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile inventory and Stripe Checkout")
    parser.add_argument("--apply", action="store_true", help="expire stale sessions and release safe holds")
    parser.add_argument("--full", action="store_true", help="check all paid orders against Stripe, not just the last 48 hours")
    args = parser.parse_args()
    findings = asyncio.run(reconcile(apply=args.apply, full=args.full))
    for finding in findings:
        print(finding)
    if not findings:
        print("Inventory and overdue holds reconciled.")


if __name__ == "__main__":
    main()
