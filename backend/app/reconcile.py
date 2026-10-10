"""Run periodically (e.g. every five minutes) as an independent Railway job.

    uv run python -m app.reconcile          # report only
    uv run python -m app.reconcile --apply  # repair confirmed stale holds
"""

import argparse
import asyncio
import sys

from .payments import reconcile
from .db import session_scope
from .models import ReconciliationRun


async def record_run(findings: list[str], *, applied: bool, full: bool) -> None:
    async with session_scope() as db:
        db.add(ReconciliationRun(findings=[str(finding)[:500] for finding in findings[:100]],
                                 finding_count=len(findings), applied=applied, full=full))
        await db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile inventory and Stripe Checkout")
    parser.add_argument("--apply", action="store_true", help="expire stale sessions and release safe holds")
    parser.add_argument("--full", action="store_true", help="check all paid orders against Stripe, not just the last 48 hours")
    args = parser.parse_args()
    findings = asyncio.run(reconcile(apply=args.apply, full=args.full))
    asyncio.run(record_run(findings, applied=args.apply, full=args.full))
    for finding in findings:
        print(finding)
    if not findings:
        print("Inventory and overdue holds reconciled.")
    else:
        # A nonzero exit lets cron/job monitoring alert on discrepancies, even
        # when --apply fixed one: the operator should inspect what happened.
        sys.exit(1)


if __name__ == "__main__":
    main()
