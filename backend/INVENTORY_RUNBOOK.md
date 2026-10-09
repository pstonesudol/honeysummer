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
See [`IN_PERSON_SALES.md`](../IN_PERSON_SALES.md) for phone setup, charge and
refund steps, and how to reconcile Dashboard payments with these movements.
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

## Production activation gate

This section is an operator checklist, **not** an indication that production is
configured. Complete it on the production services before enabling live checkout:

1. Set `DEBUG=false`, a unique `SECRET_KEY`, the production Postgres
   `DATABASE_URL`, `STRIPE_SECRET_KEY` (`sk_live_…`), and `STRIPE_WEBHOOK_SECRET`
   (`whsec_…`) on the API. Never put live secrets in this repository. Set all
    wholesale and retail success/cancel URLs to the public
   HTTPS site. Configure Resend's verified sender and farm notification address.
   Check for mismatched test/live Stripe keys and webhook endpoints before
   proceeding. The frontend must proxy `/api/stripe/webhook/` without altering
   the raw request body or `Stripe-Signature` header.
2. In Stripe, point the live webhook at the public
   `https://<site>/api/stripe/webhook/` endpoint and subscribe to
   `checkout.session.completed`, `checkout.session.expired`,
   `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, and `charge.refunded`. Verify a
   signed event reaches the API successfully; a redirect is **not** proof of
   payment. Check the Stripe webhook deliveries for retries, 400s, or 409s.
3. Take a Postgres backup, apply Alembic migrations, and run
   `uv run --no-sync python -m app.reconcile --full` using the production
   database and Stripe key. Review every finding, especially legacy pending
   holds; do **not** turn on `--apply` until the findings have been understood.
4. Provision a separate Railway cron service as described below. Give it the
   same database, Stripe, and Resend configuration as the API. Observe at least
   one successful run and a clean follow-up. Set up alerts for **both** nonzero
   exits and missed runs; deliberately verify that a failing test run triggers
   an operator notification. Do not mistake a healthy API healthcheck for a
   healthy job.
5. Perform controlled live retail and wholesale purchases, one cancelled or
   expired session, a delayed payment if enabled, and a full refund. Confirm
   stock movement, order status, webhook delivery, customer/farm mail, and
   Stripe totals agree; never use a real customer's order for the exercise.
   Run a report-only `--full` sweep afterward and resolve all discrepancies.
   Record who verified the job, alert and flows and when in the release log.

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
does not skip the next schedule. Set up the scheduler before accepting live
orders and alert an operator on failed runs, including nonzero exits when
findings are printed, and on missed runs (a stopped scheduler produces no
failures). A clean run exits 0; even findings repaired by `--apply` exit 1 so
an operator reviews the incident. The job compares the available
balance to journal deltas and pending quantities to reserve/release/sale units;
it checks stale pending sessions with Stripe, expires open sessions before
releasing stock, settles confirmed paid sessions, compares the most recent 48
hours of paid order totals and full refunds to Stripe (`--full` audits all historical paid
orders), and retries unsent confirmation emails. It **reports**, but never
silently fixes, unknown Stripe states or ledger discrepancies. A pending hold
with no recorded Stripe session ID is **not** released automatically outside
local payment-free development: session creation could have succeeded while
saving the ID and expiring the session both failed. Investigate the order ID in
Stripe's Checkout sessions/events before deciding whether stock is safe to
release.

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
