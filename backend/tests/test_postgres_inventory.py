"""Run with INVENTORY_TEST_DATABASE_URL pointing to a disposable Postgres DB."""

import asyncio
import os
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import to_async_url
from app.models import FlowerListing, InventoryMovement, Order
from app.orders import StockError, change_stock, load_order, release_order, reserve_order, settle_order


@pytest.mark.asyncio
async def test_postgres_concurrent_checkout_and_adjustment_do_not_oversell():
    url = os.getenv("INVENTORY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set INVENTORY_TEST_DATABASE_URL to an isolated migrated Postgres database")
    engine = create_async_engine(to_async_url(url))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as db:
            listing = FlowerListing(
                name="Postgres concurrency test",
                price=Decimal("1.00"),
                channel="both",
                quantity_available=1,
            )
            db.add(listing)
            await db.commit()
            listing_id = listing.id

        async def checkout(channel):
            try:
                async with maker() as db:
                    await reserve_order(
                        db,
                        items=[{"id": listing_id, "quantity": 1}],
                        channel=channel,
                        customer_name="Buyer" if channel == "retail" else "",
                    )
                return "reserved"
            except StockError:
                return "sold out"

        assert sorted(
            await asyncio.wait_for(asyncio.gather(checkout("retail"), checkout("wholesale")), timeout=10)
        ) == ["reserved", "sold out"]
        async with maker() as db:
            listing = await db.get(FlowerListing, listing_id)
            assert listing.quantity_available == 0
            assert await db.scalar(select(func.count()).select_from(Order).where(Order.status == "pending")) == 1
            assert (
                await db.scalar(
                    select(func.sum(InventoryMovement.delta)).where(InventoryMovement.listing_id == listing_id)
                )
                == 0
            )

        async def adjust():
            try:
                async with maker() as db:
                    locked = await db.scalar(
                        select(FlowerListing).where(FlowerListing.id == listing_id).with_for_update()
                    )
                    await change_stock(db, locked, -1, kind="waste", units=1, reason="Test", source="test")
                    await db.commit()
                return "adjusted"
            except StockError:
                return "sold out"

        assert await adjust() == "sold out"
        async with maker() as db:
            second = FlowerListing(
                name="Checkout vs adjustment",
                price=Decimal("1.00"),
                channel="both",
                quantity_available=1,
            )
            db.add(second)
            await db.commit()
            second_id = second.id

        async def buy_second():
            try:
                async with maker() as db:
                    await reserve_order(db, items=[{"id": second_id, "quantity": 1}], channel="retail")
                return "bought"
            except StockError:
                return "sold out"

        async def adjust_second():
            try:
                async with maker() as db:
                    locked = await db.scalar(
                        select(FlowerListing).where(FlowerListing.id == second_id).with_for_update()
                    )
                    await change_stock(db, locked, -1, kind="waste", units=1, reason="Damaged", source="test")
                    await db.commit()
                return "adjusted"
            except StockError:
                return "sold out"

        outcome = await asyncio.wait_for(asyncio.gather(buy_second(), adjust_second()), timeout=10)
        assert outcome.count("sold out") == 1
        assert sorted(outcome) in (["adjusted", "sold out"], ["bought", "sold out"])
        async with maker() as db:
            assert (await db.get(FlowerListing, second_id)).quantity_available == 0
            assert (
                await db.scalar(
                    select(func.sum(InventoryMovement.delta)).where(InventoryMovement.listing_id == second_id)
                )
                == 0
            )
        async with maker() as db:
            pair = [
                FlowerListing(name=f"Multi {n}", price=Decimal("1.00"), channel="both", quantity_available=2)
                for n in range(2)
            ]
            db.add_all(pair)
            await db.commit()
            ids = [item.id for item in pair]

        async def multi_checkout(order_ids):
            async with maker() as db:
                await reserve_order(
                    db, items=[{"id": item_id, "quantity": 1} for item_id in order_ids], channel="retail"
                )

        await asyncio.wait_for(asyncio.gather(multi_checkout(ids), multi_checkout(ids[::-1])), timeout=10)
        async with maker() as db:
            assert [(await db.get(FlowerListing, item_id)).quantity_available for item_id in ids] == [0, 0]

        async with maker() as db:
            last = FlowerListing(
                name="Cancel versus payment", price=Decimal("1.00"), channel="both", quantity_available=1
            )
            db.add(last)
            await db.commit()
            last_id = last.id
        async with maker() as db:
            order, _ = await reserve_order(db, items=[{"id": last_id, "quantity": 1}], channel="retail")
            order_id = order.id

        async def payment_transition():
            async with maker() as db:
                locked = await load_order(db, order_id, for_update=True)
                if locked.status == "pending":
                    await settle_order(db, locked)
                    await db.commit()

        async def cancellation_transition():
            async with maker() as db:
                locked = await load_order(db, order_id, for_update=True)
                if locked.status == "pending":
                    await release_order(db, locked)
                    locked.status = "cancelled"
                    await db.commit()

        await asyncio.wait_for(asyncio.gather(payment_transition(), cancellation_transition()), timeout=10)
        async with maker() as db:
            status = (await db.get(Order, order_id)).status
            available = (await db.get(FlowerListing, last_id)).quantity_available
            assert (status, available) in (("paid", 0), ("cancelled", 1))
            assert (
                await db.scalar(
                    select(func.sum(InventoryMovement.delta)).where(InventoryMovement.listing_id == last_id)
                )
                == available
            )
    finally:
        await engine.dispose()
