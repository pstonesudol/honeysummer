"""Bootstrap the first operator account.

Usage:
    uv run python -m app.seed --email you@example.com --password 'a-strong-secret'
"""

import argparse
import asyncio

from sqlalchemy import select

from .auth import hash_password
from .db import get_engine, session_scope
from .models import Base, User


async def _run(email: str, password: str) -> None:
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    email = email.strip().lower()
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email)
            session.add(user)
        user.password_hash = hash_password(password)
        user.is_admin = True
        user.is_active = True
        await session.commit()
    print(f"Admin ready: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a Honey Summer admin.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.email, args.password))


if __name__ == "__main__":
    main()
