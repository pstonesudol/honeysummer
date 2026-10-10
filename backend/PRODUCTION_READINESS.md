# Phase 12 — consolidated production acceptance

Ownership reconciled October 10, 2026. **Every checkbox below is open.** Local builds, sandbox API checks and signed mock webhooks do not prove deployed/live verification.

## Ownership and completion

- Feature phases own implementation, automated/local/test-mode verification, functional acceptance and operating instructions. Phase 12 owns production setup, deployed staging/provider rehearsals and controlled live operational acceptance.
- Phase 13 owns final brand/content approval, launch authorization, cutover and post-cutover smoke/rollback checks. It consumes this register instead of repeating production setup.
- Moving a check here does not waive it. Defects return to their feature phase for correction, then Phase 12 retests. Unfinished security/features are not DevOps tasks.
- Phase 7 owner device eligibility/training remains open. Phase 8 implementation/local closeout is complete (`PHASE8_CLOSEOUT.md`); its actual hosted provider verification and pre-live business-policy confirmation remain here. Phase 11 implementation/local verification is complete (`PHASE11_CLOSEOUT.md`); every deployed security/mail/operational check below remains open. Phase 9 owner acceptance was assumed at the user's prior instruction, not observed.
- Use isolated staging/provider test mode first. Actual live charges, refunds, emails, stock changes and DNS changes need explicitly authorized controlled procedures. Never run synthetic fixtures on the live shop database or blindly retry uncertain sends/refunds. Production debug payment bypasses must be disabled.

For **each accepted check**, record its ID, operator, timestamp, deployment/git revision, environment/provider mode, redacted evidence link, expected/actual result, blockers/fixes and retest outcome. No checkbox is acceptance without evidence and operational sign-off. Document any inapplicable scope decision; safety-critical failures block launch. Do not record secrets, recovery tokens, private photos or unnecessary customer data here.

## A. Hosting, routing and release — Phases 1–4

- [ ] A1 — Workers/OpenNext, Railway and Postgres provisioned; owners, regions, versions, budgets and environment URLs documented; staging/test/live credentials and data isolated.
- [ ] A2 — Real HTTPS same-origin `/api/`, `/admin/`, public media and protected private-media routing, headers, upload limits and health endpoints verified.
- [ ] A3 — Repeatable builds/tests/deploys, protected credentials, release approval and post-deploy checks exercised; debug payment bypasses disabled.
- [ ] A4 — Safe migrations, compatibility/rollback and failed-deploy recovery rehearsed; historical data and checkout recovery keys preserved.

## B. Storefront, wholesale and separate carts — Phases 2, 3, 5, 10

- [ ] B1 — Deployed announcements/copy/gallery/products/availability reflect admin changes; bouquet/wedding/contact inquiries persist and notify correctly.
- [ ] B2 — Wholesale application → approval → notification → login/catalogue works; pending/inactive/suspended/other-account requests and logout/account switching expose no gated information.
- [ ] B3 — Actual hosted guest retail and approved-florist wholesale purchases each have correct snapshots, pickup/delivery details, server fees, currency, total and separate orders/sessions/confirmations.
- [ ] B4 — Two populated carts, `both` listings/shared-stock contention, navigation/reload, last-channel selection and independent fulfillment work on supported desktop/mobile devices.
- [ ] B5 — Actual returns plus signed deployed webhooks clear only verified purchased quantities; other-cart/later additions survive; forged success URLs never prove payment.
- [ ] B6 — Hosted cancel/expiry/delayed success/failure, price/stock/access changes, lost responses and duplicate/cross-tab submissions recover without duplicate reservations or unsafe stock release.
- [ ] B7 — Deployed keyboard/focus/Escape and supported-device screen-reader checks pass for cart, checkout and account entry points.

## C. Payment, inventory and in-person activation — Phases 6, 7

- [ ] C1 — Correct Stripe accounts/keys/event subscriptions/signing secrets/return URLs; actual signed Checkout success/expiry/async/failure/refund events and retries verified.
- [ ] C2 — Deployed concurrent purchase and cancellation/payment boundaries preserve journal and available/reserved/on-hand balances.
- [ ] C3 — Independent reconciliation scheduled/monitored; first report-only production findings reviewed; historical exceptions resolved or safely isolated before approved apply/recovery.
- [ ] C4 — Confirmation outbox retries, webhook outages, stale holds, discrepancies and job failures are visible; alerts reach the responsible operator.
- [ ] C5 — After Phase 7 device eligibility/owner rehearsal, activate the correct live Tap to Pay account/device; verify an approved controlled sale/refund and separately audited stock recording. Dashboard charges do not automatically create Checkout orders.

## D. Bouquet invoices and owner operations — Phases 8, 9

- [ ] D1 — Deployed bouquet draft/preview → hosted invoice send/pay → actual signed invoice webhook → one paid order/notifications; resend/revise/void/expiry/failure/recovery verified.
- [ ] D2 — Stock lost after quoting triggers review, not overselling; agreed owner resolution exercised; invoice and Checkout payment identities stay separate.
- [ ] D3 — Wedding full/deposit/installment schedules, Eastern dates, sequential verified payments and final-order creation pass deployed provider-backed checks; wedding scheduler activated/monitored.
- [ ] D4 — Unpaid invoice revision/void, exact uncertain-ID recovery, invoice/Checkout full/partial refunds, refund journals and revised post-refund agreements preserve history without blind retries or automatic restocking.
- [ ] D5 — Refund auditing/reconciliation jobs persist findings and alert on mismatches; uncertain historical sends remain review-only until individually verified.
- [ ] D6 — Fulfillment/preparation, manual cash/external/Tap to Pay recording, correspondence/customer history and sales/refund/inventory/balance exports agree with controlled deployed scenarios; unpaid balances are not paid revenue.

## E. Durable media and transactional mail — Phases 2, 3, 6, 8, 9, 11

- [ ] E1 — Public/private R2 scopes, nonpublic bucket rules, immutable keys, file/image validation, public delivery/cache and admin-only private access verified.
- [ ] E2 — Uploads survive redeploys; remote/local legacy media reviewed, private copies verified before public removal/CDN purge, and media recovery exercised.
- [ ] E3 — Resend domain/SPF/DKIM/DMARC and live/test separation configured; actual inquiry/approval/order/invoice-related mail, safe absolute links and reply-to verified.
- [ ] E4 — Implemented Phase 11 invite/reset/change/suspension/security emails, expiry text, accessible templates, retries/failure visibility/deduplication verified. Provider acceptance is not falsely labelled inbox delivery.

## F. Deployed account security — Phase 11

- [ ] F1 — Source-phase implementation, permission matrix, local adversarial tests/security review and owner recovery/break-glass instructions completed first.
- [ ] F2 — Real proxy preserves Secure/HttpOnly/SameSite cookie flags/scope, CSRF/Origin/CORS protections and trusted forwarding/IP handling.
- [ ] F3 — Roles/approval/active state, revocation across workers, session rotation and idle/absolute expiry verified for anonymous/florist/staff/owner access.
- [ ] F4 — Rate limits, enumeration resistance, single-use/expired/replayed reset/invite tokens, reauthentication, owner/staff MFA and recovery verified against deployment.
- [ ] F5 — Redacted audit events, security/privilege/mail alerts, privacy/retention/export handling and owner incident response exercised.

## G. Operations and launch handoff — all phases

- [ ] G1 — Redacted logs, uptime/error/usage alerts, retention, incident owners, runbooks and manual reconciliation verified; escalation rehearsed.
- [ ] G2 — Automated Postgres backups/retention and an actual restore to an isolated environment verified, including media recovery; successful backup alone is insufficient.
- [ ] G3 — Intended domain, redirects, DNS/TLS, Workers routes, Railway origin and email DNS checked before cutover; TTL/rollback/contact plan approved.
- [ ] G4 — All applicable checks pass with evidence; source feature/owner acceptance or explicit prior waivers reconciled, no unresolved launch blockers, operational sign-off recorded.
- [ ] G5 — Handoff to Phase 13 for final assets/copy/licensing/SEO/accessibility approval, launch authorization, public cutover and post-cutover smoke/rollback checks.

## Future features

Keep code and isolated regression/security/functional acceptance in the feature phase. Add its deployed provider/configuration/operational cases here with source-phase references, not another scattered “production verification open” status. Feature completion and production acceptance are tracked separately; both are required when applicable to launch.
