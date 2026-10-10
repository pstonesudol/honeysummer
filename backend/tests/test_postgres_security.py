"""Opt-in security race tests on a disposable, migrated Postgres database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import token_digest
from app.db import to_async_url
from app.models import User
from app.security import consume_token, encrypt, verify_mfa
from app.security_models import AccountToken


@pytest.mark.asyncio
async def test_postgres_reset_and_mfa_recovery_races_are_single_use():
    url = os.getenv("SECURITY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set SECURITY_TEST_DATABASE_URL to a disposable migrated Postgres database")
    engine = create_async_engine(to_async_url(url))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    uid = None
    token = str(uuid4())
    recovery = str(uuid4())
    try:
        async with maker() as db:
            user = User(
                email=f"{uuid4()}@example.com",
                password_hash="synthetic",
                mfa_secret=encrypt("JBSWY3DPEHPK3PXP"),
                recovery_codes=[token_digest(recovery)],
            )
            db.add(user)
            await db.flush()
            uid = user.id
            db.add(
                AccountToken(
                    token_hash=token_digest(token),
                    user_id=uid,
                    kind="reset",
                    version=0,
                    expires_at=datetime.now(UTC) + timedelta(minutes=30),
                )
            )
            await db.commit()

        async def reset():
            async with maker() as db:
                row = await consume_token(db, token, "reset")
                if row:
                    user = await db.scalar(select(User).where(User.id == uid).with_for_update())
                    user.security_version += 1
                await db.commit()
                return bool(row)

        async def mfa():
            async with maker() as db:
                user = await db.scalar(select(User).where(User.id == uid).with_for_update())
                success = verify_mfa(user, recovery)
                await db.commit()
                return success

        assert sum(await asyncio.gather(*(reset() for _ in range(8)))) == 1
        assert sum(await asyncio.gather(*(mfa() for _ in range(8)))) == 1
        async with maker() as db:
            assert (await db.get(User, uid)).security_version == 1
    finally:
        if uid:
            async with maker() as db:
                await db.execute(delete(AccountToken).where(AccountToken.user_id == uid))
                await db.execute(delete(User).where(User.id == uid))
                await db.commit()
        await engine.dispose()
