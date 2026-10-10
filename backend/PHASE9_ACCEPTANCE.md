# Phase 9 closeout — owner acceptance assumed

**October 10, 2026:** Phase 9 implementation is closed with Isabella's acceptance **assumed at the user's explicit direction**, not an observed owner sign-off. The unchecked checklist below is retained as a launch rehearsal, not a claim that Isabella performed it. Security belongs to Phase 11; production verification belongs to Phase 12. Do **not** retry wedding quote #9 or any review-state payment without identifying the original transaction in Stripe first.

## Verified closeout evidence

- Automated suite, lint, frontend build and Alembic schema check are recorded in `PHASE9_CLOSEOUT.md`.
- Real Stripe **test-mode** synthetic quotes #13 and #14: $1 deposit, $0.50 deposit refund, newly accepted $3 itemization with $0.50 retained / $2.50 revised balance; no order on deposit and one order after final payment (#23/#24). App refund and external refund import on the final invoice produced $1 recorded order refunds, exactly once, without stock changes.
- Synthetic quote #15: known unpaid invoice void, replacement with a distinct Stripe ID/revision, simulated lost local ID and exact matching Stripe attachment. Both unpaid invoices were voided after testing.
- The new invoice-refund audit queried Stripe and found journals agree with supported payments. This was report-only and its run was persisted.
- Local inquiry-photo audit found **no photos to migrate**. Migration, private-copy verification and public-original removal have synthetic regression coverage; any separately deployed legacy R2/CDN data still needs its own migration and cache purge.
- Desktop/mobile login, dashboard, content-save and administrative activity were browser-checked using an isolated preview database. This is not the complete owner-device checklist.
- Payment objects in the new Stripe verification were retrieved directly from Stripe; this run did **not** test a deployed signed webhook endpoint. Signed-event route tests and earlier invoice sandbox checks are separate evidence.

## Desktop and phone

- [ ] Log in on a desktop and a phone. Navigate the dashboard, Orders, Inquiries, Flowers, reports, attention queue, site content and logout. Check keyboard-only focus, form labels, validation, readable statuses, long tables and mobile menu. No clipped buttons, inaccessible dialogs or silent failures.
- [ ] Update a business detail, FAQ, social link and scheduled announcement. Preview the public pages before considering them final. Review actual brand copy and photos. Upload a gallery photo with alt text and focal point, reuse it for a listing; verify public R2 delivery only after Phase 11 storage is configured.
- [ ] Submit an inquiry with an inspiration photo; verify the photo appears only behind admin login. Audit **older** inquiry photos separately: migrate them out of public media and verify the public URLs stop working.

## Inventory, customers and preparation

- [ ] Publish a retail and wholesale listing, record harvest, physical count and waste, change a season, then export inventory history. Confirm available stock and movement reasons match the physical counts.
- [ ] Complete a paid retail Checkout in test mode. Confirm exactly one order and one stock deduction, an owner/customer notification or a visible failure, a packing slip, preparation state and a dated pickup/delivery. Complete the order on a phone.
- [ ] Record a phone or market sale with an externally verified payment reference. Confirm catalogue stock moves once, a custom service does not move catalogue stock, and a repeat submission makes no second order.
- [ ] Work an inquiry through follow-up and correspondence notes or .eml import. Check customer history and pending florist applications; security-sensitive account approvals/recovery remain Phase 11.

## Wedding and bouquet payments

- [ ] Draft a multi-line bouquet proposal; revise an unpaid Stripe invoice, then pay a test invoice and verify one paid order and one set of stock movements.
- [ ] Draft a wedding with itemized lines, separately scheduled send and due dates, and three installments totaling the exact quote. Pay only the first invoice: confirm booked work is visible, **no paid order exists**, and paid sales exclude it. Pay the remaining invoices sequentially: one paid order appears only after the last payment.
- [ ] Void a **known unpaid** wedding invoice in test Stripe, revise and send a replacement. Confirm the original remains visible, the new invoice has a distinct Stripe ID, and no duplicate payment request is sent. Test attaching a matching open or fully paid Stripe invoice after a simulated lost local response; reject mismatched amount, revision, out-of-band payment or unrecognized invoice.
- [ ] Issue a partial then remaining refund against a single paid invoice in test Stripe. Verify the intended PaymentIntent, receipt and invoice refund journal, quote/proposal review pause, order net figures where an order exists, and **no automatic restock**. Check a refunded deposit cannot trigger the next scheduled invoice. Verify refunds with uncertain status cannot be retried blindly.
- [ ] For a partially refunded, not-yet-paid wedding, resolve all older invoices in Stripe, capture the customer's written acceptance of a new itemized agreement, and save it. Verify saving sends nothing, net retained payments are credited exactly once, and only the revised balance can be manually sent. Pay that test invoice: check one paid order with the revised lines, retained-payment and refund history, and correct order refund ceiling. A voided or uncertain earlier invoice must not silently trigger another send.
- [ ] Verify an actual physical return with the separate restock action, and check its stock movement. Refund without physical return and confirm the available count does **not** rise.

## Reports and sign-off

- [ ] Export sales, invoice balances, product/channel performance, waste and inventory CSVs. Reconcile gross receipts, recorded refunds and outstanding invoice amounts with test Stripe and local records; do not treat original gross as net accounting or a refunded wedding as a new collectible balance.
- [ ] Review failed notifications, ambiguous payment states and reconciliation-run findings in Needs attention. Confirm each has an operator action or documented manual escalation.
- [ ] Rehearse every applicable scenario on the owner's devices before public launch. Production scheduling, R2, webhooks, alerting and backups remain Phase 12 launch gates, irrespective of assumed Phase 9 acceptance.

**Owner acceptance:** Assumed per explicit user instruction · **Closeout date:** October 10, 2026 · **Exceptions:** no observed owner rehearsal; deployed webhooks/services and legacy remote media not verified; quote #9 remains blocked pending Stripe investigation. No production launch authorization is implied.
