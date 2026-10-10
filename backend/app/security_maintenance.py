"""Retry security mail and prune expired secrets using an independent job."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from .db import get_engine, session_scope
from .security import deliver_security_mail
from .security_models import AccountSession, AccountToken, SecurityMail, SecurityThrottle


async def maintain(*, apply=False) -> dict:
    """Report failures; apply retries and bounded operational-state retention only."""
    now = datetime.now(UTC)
    if apply:
        await deliver_security_mail()
        async with session_scope() as db:
            await db.execute(delete(AccountSession).where(AccountSession.expires_at < now))
            await db.execute(delete(AccountToken).where(AccountToken.expires_at < now - timedelta(days=1)))
            await db.execute(delete(SecurityThrottle).where(SecurityThrottle.created_at < now - timedelta(days=1)))
            await db.execute(delete(SecurityMail).where(SecurityMail.accepted_at < now - timedelta(days=30)))
            await db.commit()
    async with session_scope() as db:
        pending = await db.scalar(
            select(func.count()).select_from(SecurityMail).where(SecurityMail.accepted_at.is_(None))
        )
    return {"awaiting_acceptance": pending}


async def _run(apply):
    try:
        result = await maintain(apply=apply)
        print(result)
        return 1 if result["awaiting_acceptance"] else 0
    finally:
        await get_engine().dispose()


def main() -> None:
    """A nonzero status keeps failed/expired security mail visible to job monitoring."""
    parser = argparse.ArgumentParser(description="Security outbox/expiry maintenance")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.apply)))


if __name__ == "__main__":
    main()
