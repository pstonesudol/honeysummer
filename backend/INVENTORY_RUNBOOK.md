# Inventory and Stripe operations

## What the numbers mean

The `/admin/flowers/<id>/inventory` page shows **available** (sellable now),
**reserved** (units in pending checkout orders), and **on hand** (available +
reserved). These are counts of listing units (`stem` or `bunch`), not physical
stems across different unit types. The append-only movement history explains
changes to the available balance: opening/restock/adjustment, reserve (-),
release (+), sale (0: a hold becomes a purchase), refund (0: no automatic
restock), return (+), waste (-), and manual market sale (-). All channels share
one balance. The `sold_out` switch hides purchasing without changing stock.

Create listings with an initial quantity. To change it later, open **View
inventory history and adjust stock**; enter a positive restock, waste, or
market-sale quantity, or a signed correction, and supply a reason (include the
Tap to Pay receipt/reference for market sales). Do not edit inventory via SQL.
Orders cannot be deleted through admin. A flower listing can be deleted only
when it has no order items and no inventory movements; otherwise deactivate it
to preserve invoicing and the append-only stock audit trail.

## Payment lifecycle

- Checkout reserves stock under Postgres row locks in stable listing-ID order.
  The order's hold expires after `CHECKOUT_HOLD_MINUTES` (default 45; allowed
  35–1440). Stripe Checkout gets the same deadline. Both retail and wholesale
  charge only server-priced items and listing-configured delivery fees.
- A signed `checkout.session.completed` with `payment_status=paid`, matching
  session ID, USD currency and exact order total converts the reservation to a
  paid sale. For delayed methods, an unpaid completion remains reserved until
  `checkout.session.async_payment_succeeded` or
  `checkout.session.async_payment_failed`. Configure Stripe to deliver those
  events plus `checkout.session.expired` and `charge.refunded` to
  `/api/stripe/webhook/`. Stripe event IDs are recorded; repeated events do not
  release stock twice or send duplicate order confirmations.
- Cancel a **pending** order in admin only after its Stripe Checkout session is
  confirmed expired/unpayable. A paid order can be marked fulfilled, not
  cancelled/restocked. A full `charge.refunded` event marks it refunded **without
  automatically increasing available stock**. Once physical goods are returned
  and usable, use the order's **Restock** action once; a refund of a fulfilled
  order might not merit restocking. Partial refunds and conflicts require manual
  review. A refund in Stripe is separate from changing inventory in admin.
- With Stripe unconfigured, checkouts are rejected in production (`DEBUG=false`).
  Local `DEBUG=true` permits payment-free checkouts; never use that for live
  orders.

## Run the reconciler

Run an independent scheduled job (for example a Railway cron service every
five minutes, in the backend directory with the same `DATABASE_URL` and Stripe
key) using `uv run python -m app.reconcile --apply`. First inspect with
`uv run python -m app.reconcile` (report-only). No work is scheduled merely by
starting the API. On Railway, create a **separate** service from the same repo
with root directory `/backend`, start command `uv run --no-sync python -m
app.reconcile --apply`, shared Postgres/Stripe/Resend environment variables,
no healthcheck or public domain, and Cron Schedule `*/5 * * * *` (UTC). Do not
replace the API service's web start command. Confirm each run exits so Railway
does not skip the next schedule. Set up the scheduler before accepting live orders and alert
an operator on nonempty output or job failures. The job compares the available
balance to journal deltas and pending quantities to reserve/release/sale units;
it checks stale pending sessions with Stripe, expires open sessions before
releasing stock, settles confirmed paid sessions, compares the most recent 48
hours of paid order totals and full refunds to Stripe (`--full` audits all historical paid
orders), and retries unsent confirmation emails. It **reports**, but never
silently fixes, unknown Stripe states or ledger discrepancies.

When investigating a finding, compare the order in admin with the Stripe
Checkout session and payment intent in the Stripe dashboard. A `409` from the
webhook signals a mismatched amount/session or an invalid transition and is
logged; do not edit the order status or availability directly to silence it.
Escalate payment/refund discrepancies before manually recording a stock
correction. An email failure remains in the outbox for retry; email delivery is
at least once (a crash after sending but before marking sent can resend it).

## Existing data and verification

Alembic seeds an opening balance for existing listings and zero-delta
`legacy_hold` entries for pre-migration pending orders. Old pending orders have
no hold deadline, so the reconciler inspects their Stripe state on its first
run; dry-run before `--apply`. Back up production Postgres before migration.
Existing negative stock must be resolved before the nonnegative constraint can
be applied. The normal suite uses SQLite and does **not** validate `FOR UPDATE`:
run `INVENTORY_TEST_DATABASE_URL=postgresql://... uv run pytest tests/test_postgres_inventory.py`
against a **disposable, migrated Postgres database** to verify concurrent
retail/wholesale checkouts, multi-item lock ordering, and stock adjustments.
