"""Audited offline break-glass, requiring trusted shell access and identity review."""

import argparse
import asyncio
import getpass

from sqlalchemy import select

from .auth import hash_password
from .db import get_engine, session_scope
from .models import User
from .security import deliver_security_mail, password_error, queue_mail
from .security_models import SecurityEvent


async def recover(email: str, password: str, reason: str) -> None:
    """Recover an existing owner only; never promote an arbitrary account."""
    if password_error(password) or not reason.strip():
        raise ValueError(password_error(password) or "An identity-review reason is required.")
    async with session_scope() as db:
        user = await db.scalar(
            select(User).where(User.email == email.lower().strip(), User.role == "owner").with_for_update()
        )
        if not user:
            raise ValueError("Existing owner not found; no account was changed.")
        user.password_hash = hash_password(password)
        user.security_version += 1
        user.is_active = True
        user.mfa_secret = user.mfa_pending = ""
        user.mfa_last_step = 0
        user.recovery_codes = []
        db.add(
            SecurityEvent(
                target_id=user.id,
                action="owner_break_glass",
                outcome="success",
                context="trusted-local-cli",
                reason=reason[:2000],
            )
        )
        queue_mail(
            db,
            user.email,
            "Owner recovery",
            "Offline owner recovery was performed. All sessions were revoked. "
            "Enroll a new authenticator at next sign-in.",
        )
        await db.commit()
    await deliver_security_mail()


async def _run(email, password, reason):
    try:
        await recover(email, password, reason)
    finally:
        await get_engine().dispose()


def main() -> None:
    """Require interactive confirmation; never put a recovery password in arguments."""
    parser = argparse.ArgumentParser(description="Audited last-owner MFA recovery")
    parser.add_argument("--email", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    if input(f"Identity verified? Type the owner email ({args.email}) to confirm: ") != args.email:
        raise SystemExit("Recovery cancelled.")
    password = getpass.getpass("New owner password: ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords did not match.")
    asyncio.run(_run(args.email, password, args.reason))
    print("Owner recovered; authenticator enrollment is required at next sign-in.")


if __name__ == "__main__":
    main()
