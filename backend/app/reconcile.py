"""Run periodically (e.g. every five minutes) as an independent Railway job.

uv run python -m app.reconcile          # report only
uv run python -m app.reconcile --apply  # repair confirmed stale holds
"""

import argparse
import asyncio
import sys

from .db import session_scope
from .models import ReconciliationRun
from .payments import reconcile


async def record_run(findings: list[str], *, applied: bool, full: bool) -> None:
    """Persist a summary of one reconciliation run."""
    async with session_scope() as db:
        db.add(
            ReconciliationRun(
                findings=[str(finding)[:500] for finding in findings[:100]],
                finding_count=len(findings),
                applied=applied,
                full=full,
            )
        )
        await db.commit()


async def reconcile_and_record(*, apply: bool, full: bool) -> list[str]:
    """Use one event loop for the audit and its persistent run summary."""
    findings = await reconcile(apply=apply, full=full)
    await record_run(findings, applied=apply, full=full)
    return findings


def main() -> None:
    """Audit stock and Stripe, optionally repairing safe discrepancies."""
    parser = argparse.ArgumentParser(description="Reconcile inventory and Stripe Checkout")
    parser.add_argument("--apply", action="store_true", help="expire stale sessions and release safe holds")
    parser.add_argument(
        "--full", action="store_true", help="check all paid orders against Stripe, not just the last 48 hours"
    )
    args = parser.parse_args()
    findings = asyncio.run(reconcile_and_record(apply=args.apply, full=args.full))
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
