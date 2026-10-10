# Phase 10 — global storefront carts

Implemented locally October 10, 2026. This is not production Stripe approval.

## Shopping experience

- The header cart is available beside mobile navigation and at the right of the desktop header. Desktop uses a right-side drawer; mobile uses a full-screen panel.
- Retail and wholesale are independent carts. Approved florists can switch between quantity-labelled buttons; everyone else sees retail and a wholesale access link. There is no combined total or combined payment.
- Add buttons select/open their own channel. The same `both` listing can appear in either basket, but both compete for its single stock balance.
- Quantities, removals, thumbnails, unit prices and subtotals are shared between the drawer and `/checkout/retail` or `/checkout/wholesale`. Each channel's contact/fulfillment fields survive client navigation only in memory, never browser storage; wholesale details clear with access loss. Retail collects guest contact details; wholesale requires a currently active, approved account.
- Native modal semantics make the background inert; explicit Tab wrapping, Escape, focus restoration, labelled controls and live status messages support keyboard and assistive-technology use.

## Persistence and access

`hs-cart-v1:retail` stores listing IDs, quantities and non-sensitive addition counters. Wholesale uses `hs-cart-v1:wholesale:<user-id>`; account identity is returned by `/api/auth/me/`. Selected channel is saved separately. Product details are fetched afresh, not persisted.

Confirmed logout/account change or approval loss clears wholesale state and hides its catalogue. The provider refreshes identity on focus/visibility changes and every 15 seconds; protected API calls always recheck authorization. An aborted or failed identity poll is **not** proof of logout and must not erase saved baskets. Phase 11 still owns revocable sessions, broader CSRF/rate-limit/MFA work and the account lifecycle.

Cart storage never includes customer names, email, addresses, notes or payment credentials. An opaque checkout attempt key and a submitted quantity snapshot are retained for payment recovery. Browser storage must be available for reliable reload recovery. Carts alone do not reserve inventory.

## Checkout and payment recovery

The existing `/api/retail/checkout/` and `/api/checkout/` endpoints now accept an optional UUID `checkout_key`. The database uniquely commits it with the inventory reservation; a retry returns the existing attempt instead of reserving again. Browser Web Locks serialize same-channel checkout across tabs where supported. Existing server-side channel filtering, ordered row locks, delivery-fee calculation, Stripe idempotency and signed webhook verification remain authoritative. Client price snapshots are checked for changes but never determine charged prices.

`GET /api/cart/checkout/<key>/` returns minimal, non-cacheable order/payment status and a resumable URL. Wholesale status additionally requires its original approved account. Neither a success query parameter nor a Stripe return URL proves payment. Pending/delayed payments remain pending until verified by the existing webhook/reconciler; the UI checks again on focus and its polling interval.

Verified paid/fulfilled/refunded orders clear only the submitted quantities. Addition counters preserve items added after submission, including remove/re-add and reload. The other channel is never cleared. Failed or expired checkout retains the basket; an uncertain network response retains the original key.

`DELETE /api/cart/checkout/<key>/` first confirms the Stripe session is unpayable, then locks the order and releases the reservation once. Completed/uncertain sessions cannot be blindly cancelled. A pending session is resumed, not replaced. Cart changes made while it is pending are for a later order; Stripe retains the original submitted total/fulfillment. To change the unpaid order itself, safely cancel it first.

## Deployment

Run `uv run alembic upgrade head` in the backend before deploying this frontend/backend pair. Revision `8a91c04eb672` adds a unique nullable checkout key and saved checkout URL; historical orders are unchanged. Do not downgrade after accepting active cart checkouts: that removes their recovery keys.

Production still needs Phase 6 reconciliation activation and Phase 12 Stripe keys, signed webhook events, same-origin routing and actual hosted Checkout return verification. Browser purchase tests below used explicit local debug payment mode, **not** a real Stripe charge or production webhook.

## Verification recorded

- Full backend suite with disposable Postgres enabled: **158 passed**. Includes duplicate-key reservation races, retail/wholesale shared-stock contention, wrong-channel/changed-price requests, inactive/unapproved/other-account access, resumable pending checkout, safe cancellation, signed delayed-payment events and duplicate webhook processing.
- Frontend cart unit tests: **5 passed**, covering restoration, quantity snapshots, later additions, remove/re-add across reload, independent baskets and stock-change messages.
- ESLint, Ruff and Next production build pass.
- Fresh Postgres upgrade, downgrade/re-upgrade and Alembic schema check pass on disposable databases.
- Headless Chrome at **1440×900** and **390×844**: drawer/full-screen sizing, Tab containment, Escape/focus restoration, navigation/reload persistence, two populated carts, independent retail/wholesale purchases, anonymous guest purchase, logout isolation, no stored contact/payment details and no page errors. Header visibility also checked at 768, 900 and 1024 px.
- Screenshots: `.openchamber/screenshots/phase-10-cart-1440.png` and `phase-10-cart-390.png` (synthetic preview products only).

Repeat unit checks with `npm run test --workspace frontend`; backend checks with `cd backend && uv run pytest -q`. For the opt-in concurrency tests, set `INVENTORY_TEST_DATABASE_URL` to a **fresh, isolated, migrated Postgres database**, never the live shop database. Before launch, repeat the two-channel flows with Stripe-hosted test-mode Checkout, cancellation/expiry/delayed payment, real webhook delivery, price/stock changes, and a screen reader on the owner's supported devices.
