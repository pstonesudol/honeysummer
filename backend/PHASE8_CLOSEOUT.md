# Phase 8 local closeout — October 10, 2026

**Status: implementation and local verification complete. Not production acceptance or observed owner sign-off.**

## Scope reconciled against the saved plan

- Inquiry-linked bouquet draft, customer preview, itemized USD invoice, immutable sent/revision history, internal notes/activity, resend/void/revise, signed invoice payments, stock-aware paid-order conversion and notification/reconciliation tooling are implemented.
- Invoice refunds were delivered in Phase 9. This closeout extends issue/import/full-refund closure to a paid invoice with a stock shortfall and **no booked order**; Stripe payment verification and existing idempotency/uncertain-refund guards still apply.
- Fixed a recovery defect: `stock_review` proposals were selected by reconciliation but rejected by payment application after replenishment. They can now book once after sufficient stock is available. Recorded refunds block payment replay/reconciliation from creating a new order.
- The proposal page now explains physical-stock review, journaled replenishment plus operator reconciliation, or customer-agreed refund/import/closure. A paid snapshot is never silently rewritten, a refund never restocks, and a second payment request is not a recovery strategy.
- Plan 8d describes a branded customer page as optional and view status as “viewed-if-available.” Neither a bespoke customer page nor view tracking is required for the first release. No email/redirect is represented as payment or viewing evidence.
- Plan 8e explicitly accepts stock-shortfall owner review. Automated substitutions are optional future scope, not a first-release blocker. Full-upfront USD pricing remains the bouquet policy; tax automation/deposits are not added here.

## Verification evidence

`uv run pytest -q` in `backend`: **163 passed, 2 skipped** (opt-in Postgres tests). Ruff checks and formatting pass for the changed Python files. No database migration is needed.

Bouquet-specific tests in `tests/test_proposals.py` cover:

- Inquiry-kind/access/CSRF restrictions, draft saving and customer-facing preview, preserved dynamic lines and validation, currency precision and delivery totals.
- Invoice composition and send/payment conversion using mocked Stripe API responses, duplicate-send rejection, one stock journal/order, and no reservation at quoting/sending.
- Actual HMAC-signed local webhook acceptance and invalid-signature rejection; duplicate payment handling. Stripe API responses are mocked, not real provider calls.
- Failed customer notification retained in the outbox, reconciler retry, and no repeat delivery after recorded success.
- Stock shortfall leaves no order; report-only reconciliation does not book; journaled replenishment plus apply creates one order; repeated apply/webhook does not double-deduct.
- Invalid totals/out-of-band payments fail closed; missing secret/signing credentials leave drafts unchanged; ambiguous sends pause for review and reject another send.
- Revision requires an open Stripe invoice and preserves the old snapshot; resend, failed payment followed by success, and stale failure/void events do not undo a booked payment.
- Admin-rendered stock-review instructions and issue/import refund controls are present without a resend/payment button.

`tests/test_invoice_refunds.py` covers issuing and importing refunds for unbooked stock-review proposals, duplicate requests/imports, blocked post-refund booking, full-refund closure without a synthetic order/order-refund ledger, and existing booked bouquet/wedding refund protections. Shared inventory, inquiry-mail and invoice-balance tests retain stock integrity, notification failures, reporting and overdue coverage.

Authenticated Chrome checks at 390px and 1440px verified the new stock-review guidance, saved preview and refund controls on an isolated Sanic server with a disposable SQLite database and synthetic owner/proposal. Stripe/Resend credentials were explicitly disabled; no real records or provider actions were used. Mobile content scrolls to the refund controls and desktop uses the shared admin sidebar layout. Admin markup also has authenticated test-client coverage. Deployed supported-device/assistive-technology rehearsal remains in Phase 12's register.

## Phase 12 handoff — still open

Use `PRODUCTION_READINESS.md`, especially D1/D2/D4 and C3/C4/E3, for isolated deployed Stripe test-mode rehearsal followed by explicitly authorized controlled live acceptance: hosted invoice email/payment, actual provider webhook delivery, resend/revise/void/refund recovery, customer/farm mail, stock-shortfall handling and monitored scheduling.

Local test credentials and signed fixtures are **not** provider integration evidence. Confirm fulfillment/substitution/refund/tax policy with Isabella before live operation. Never retry uncertain historical invoice/refund outcomes blindly.
