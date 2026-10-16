# Honey Summer project status

**Single source of truth for implementation, staging validation and production
validation.** Consolidated October 14, 2026 UTC from the master plan, code/tests,
GitHub PRs/releases, provider state and existing closeouts/runbooks. No production
cutover, live customer transaction or launch authorization is claimed here.

## Status rules

- **Implementation** means code plus automated/local/test-mode verification. It is
  not deployed acceptance.
- **Staging validation** means evidence from the deployed staging environment
  through its configured providers and Worker → Railway path.
- **Production validation** means evidence from the production environment or an
  explicitly approved controlled production rehearsal.
- `backend/PRODUCTION_READINESS.md` remains the detailed acceptance evidence
  register; this file is the current status index. Historical closeouts, runbooks
  and dated logs remain evidence, not independent status trackers.
- A check is not accepted merely because code or a targeted probe exists. Every
  applicable acceptance row needs dated evidence, an operator and a pass/fail
  result before public launch.
- Files under `deprecated/` are provenance only. Do not use their old status
  statements, tasks or rollout instructions as current requirements. Update this
  file and the acceptance evidence register, not the archived plan.

## Phase status

| Phase | Implementation | Staging validation | Production validation | Current blockers / notes |
| --- | --- | --- | --- | --- |
| 1 — Scaffold/design system | Complete | Partial | Partial — production backend resources and direct health verified; production frontend/domain untouched | Final licensed font assets remain Phase 13. Budgets, rollback and full runtime acceptance remain open. |
| 2 — Marketing/inquiries | Complete | Partial | Not started | Deployed forms/mail, inquiry-photo privacy, full media checks and final copy/photos remain open. |
| 3 — Wholesale | Complete; cart path superseded by Phase 10 | Partial | Not started | Deployed approval/login/catalogue/payment/mail and account-boundary checks remain open. |
| 4 — Sanic re-platform | Complete | Partial | Partial — production backend liveness verified | Migrations, release rollback, routing/security and provider acceptance remain open. |
| 5 — Retail checkout | Complete | Partial | Not started | Hosted guest purchases, signed webhooks, returns and receipts remain open. |
| 6 — Inventory/Stripe reliability | Complete | Partial | Not started | Scheduled reconciliation, alerts, concurrent boundaries, refund/async/failure/retry coverage remain open. |
| 7 — In-person sales | Documentation complete; device/account eligibility and setup user-confirmed | Not applicable yet | Not started | Owner sale/refund and stock-recording rehearsal, intended live account/device check and controlled first transaction remain open. |
| 8 — Bouquet proposals/invoices | Complete | Partial | Not started | Hosted invoice send/pay/revise/void/refund, provider webhook, mail, stock-review recovery and business policy remain open. |
| 9 — Owner operations/admin | Complete; owner acceptance assumed, not observed | Partial | Not started | Deployed schedulers/refunds/R2/private-media/mail/reports and owner-device rehearsal remain open. Quote #9 remains review-only. |
| 10 — Separate retail/wholesale carts | Complete | Partial | Not started | Real hosted Checkout, returns/webhooks, cancellation/expiry/delayed payment, two-cart recovery and supported-device checks remain open. |
| 11 — Accounts/security | Complete; optional operator MFA policy approved | Partial | Not started | Cross-worker revocation, broader rate limits, real token expiry/recovery, security-mail delivery, privacy/incident response and deployment-header checks remain open. |
| 12 — DevOps/production acceptance | In progress | In progress | Partial — direct production backend health only | All detailed acceptance rows remain open. Backups/restore, scheduled jobs, alerts, provider rehearsals and launch sign-off are not complete. |
| 12.5 — Automated quality/release checks | Partial baseline; scope incomplete | Partial HTTP smoke evidence; broader automation open | Not accepted | CI runs an explicit frontend TypeScript check and a blocking high-severity audit of production dependencies, in addition to tests, lint and migrations. Full-tree dependency audit still reports 8 high-severity development-tool findings; secret scans, backend type checks, complete migration validation and required failure rehearsals remain open. |
| 12.6 — IaC/drift control | Partial baseline; scope incomplete | Partial Railway/Wrangler configuration evidence | Not accepted | Railway IaC and Wrangler configuration exist. Cloudflare/GitHub settings are not fully codified; secure state, approved applies and drift detection remain open. |
| 13 — Polish/launch | Partial | Not applicable | Not started | Final copy/photos/fonts/licensing, accessibility/SEO, client approval, cutover and post-cutover checks remain open. |

## Staging validation summary

Completed targeted checks are evidence only; they do not close a detailed
acceptance row unless the register explicitly says so.

- Releases and routing: CI → staging → manual production approval exists;
  multiple staging releases have succeeded. Staging Worker is deployed behind
  `https://staging.hellohoneysummer.com`; direct Railway protected routes are
  gated, with health publicly available. Production frontend remains outside the
  release chain.
- Access/security: Cloudflare Access checks, origin-secret gate probes, cookie
  flags, invalid CSRF logout denial, invalid token negative probes and selected
  role/session checks have passed on staging. These are partial checks, not full
  deployed security acceptance.
- Media/storage: staging R2 public/private variables are configured; optimized
  public upload converted a 15.1 MB JPEG to a 312,388-byte 1600×2400 WebP and
  served it with immutable caching. Backend rejected a 50 MiB+1 upload, the Worker
  rejected a 60 MiB+1 request, and malformed image contents were rejected. A new
  private inquiry upload renders through admin at 800×800. Private byte equality,
  exact public-key absence, anonymous denial, recovery and legacy media cleanup
  remain open.
- Payments/orders: seven earlier paid staging Checkout sessions matched stored
  orders; three earlier expired sessions matched cancelled orders. On October 16,
  a $5 Stripe-test retail Checkout was expired through Stripe; the signed
  `checkout.session.expired` event applied, a duplicate signed replay was ignored
  (HTTP 200), and an invalid signature was rejected (HTTP 400). The test order
  remained expired, the listing returned to 35 available, and a report-only
  reconciliation recorded zero findings with `applied=false`. No payment was
  taken. Successful new payment/refund, async/failure, and concurrency rehearsals
  remain open.
- Mail/reporting: Resend provider acceptance was observed for selected messages;
  this is not inbox placement. Sales ledger and packing-slip spot checks matched
  the sampled staging data. Queues and logs showed no current failures in limited
  snapshots, but no alert/escalation acceptance exists.
- Environments: staging and production Railway services are online; R2 variable
  names exist only in staging. Staging backend deployment
  `ccacdc4a-8953-4457-9e75-86bedd7b87c0` was the latest observed staging backend
  success. Exact deployed git SHA is not exposed by Railway metadata.
- Backups — October 16, 2026: the staging-only Railway backup cron and daily
  03:30 UTC schedule are active; two manual backups and the scheduled backup
  succeeded. A full logical restore of snapshot
  `snapshots/2026/10/15/e79086d9ea1c4aa589a5e6a1acad831e/manifest.json.hsbackup`
  into the isolated `staging-restore` Postgres and media buckets completed. The
  restore log reports one database archive, two public objects and two private
  objects; R2 listings confirm both media buckets populated. One prior attempt
  stopped before reading the snapshot because credentials were still staged; it
  wrote no data. Read-only validation confirmed the restored Alembic revision
  matches repository head, aggregate ORM reads succeeded for users/orders/items/
   inquiries/gallery, and the staging app's `/api/retail/flowers/` handler returned
  HTTP 200 with two listings against the restored DB. The application encryption
  key passed a synthetic encrypt/decrypt round-trip. Additional read-only checks
  found zero unvalidated constraints or invalid indexes; all 28 foreign keys,
  27 primary keys, and 15 unique constraints are validated. All populated-table
  ID sequences match their maximum IDs. Both private media references and the
  gallery reference match restored R2 objects; one additional public object is
  unreferenced by current media columns. All rows across 26 mapped application
  tables (389 rows total) deserialized through SQLAlchemy; both private restored
  inquiry images were read with the app's private-media function and decoded as
  valid JPEGs. The two public restored images also decoded successfully. The
  restore-private bucket had no custom domain and its managed `r2.dev` public
  access is disabled. A controlled backup exception exercised the job's failure
  handler; the owner supplied a screenshot of the corresponding GitHub Actions
  failure email at 8:46 PM on October 15, confirming receipt for run `38831354476`.
  The owner independently retrieved `BACKUP_ENCRYPTION_KEY` from escrow and
  confirmed an exact match with the staging backup service using hidden terminal
  prompts; no key material was shared. Escrow retrieval for the separate
  `SECURITY_ENCRYPTION_KEY` was also independently retrieved from escrow and
  matched to the staging app service value; no key material was shared. With
  owner approval, the restore runner, restore Postgres and volume, and both
  restore buckets (including their four restored objects) were removed. Follow-up
  Railway/R2 checks found no restore service, volume, bucket, or pending cleanup
  work; staging app/Postgres/jobs and the encrypted backup bucket remain.
  Production was untouched. The managed service did not support
  `pg_amcheck`/`amcheck`, and no restored MFA or queued-security-mail ciphertext
  was available for application-key validation.
- Reconciliation workers — October 15, 2026: staging-only report-only
  inventory/Checkout and invoice-refund jobs are provisioned at 15-minute and
  daily schedules. Both first manual runs succeeded with zero findings. A
  controlled GitHub dispatch produced the intended failed alert workflow. A
  workflow-dispatch verification on October 16 (run `38845808631`) emitted the
  generic reconciliation alert and failed as designed. The owner supplied a
  screenshot of the corresponding GitHub Actions failure email, confirming
  receipt. Ongoing monitoring and production readiness remain open. See
  `backend/STAGING_RECONCILIATION_RUNBOOK.md`. No production worker was changed.
- Staging read-only operations/smoke check — October 16, 2026, approximately
  03:30–03:45 UTC: Railway reported all five remaining staging services healthy,
  no warnings/critical issues, no recent failures, and no pending changes. The
  15-minute reconciliation service logged successful runs through 03:30:33 UTC;
  the backup service completed at 03:34:51 UTC and logged a new manifest. The
  invoice/refund audit's latest observed run was October 15 at 04:19 UTC; its
  October 16 04:15 UTC run had not yet occurred during this check. Direct staging
  `/api/health/` returned `status: ok`; using the authorized staging browser
  session, the home/order pages loaded and `/api/retail/flowers/` returned two
  listings (35 available Red Flowers; White Flowers unavailable). An unauthenticated
  custom-domain request was shown the Cloudflare Access sign-in page, as expected.
  No cart, order, payment, or customer-submission action was taken. This is a
  point-in-time health/smoke sample, not sustained monitoring or full acceptance;
  the reconciliation log message does not expose persisted finding counts.
- Staging scheduled-job follow-up — October 16, 2026, checked at approximately
  14:11 UTC: the daily invoice/refund audit ran at 04:18:55 UTC and succeeded;
  its report-only log said “Invoice refund journals agree with supported Stripe
  payments.” Railway reported no failures in the preceding 24 hours and no
  warnings/criticals. The reconciliation job's latest observed run also succeeded
  at 14:02 UTC, but its generic log does not expose persisted finding counts.
  These are point-in-time observations, not sustained monitoring or full
  acceptance. No production services or financial data were changed.
- Reconciliation follow-up at approximately 14:15 UTC: Railway's latest
  execution completed successfully at 14:15:04 UTC, with the generic success log
  at 14:15:12 UTC. Railway reported no warnings, critical issues, recent failures,
  or pending work. The log does not disclose persisted finding counts; report-only
  reconciliation and sustained monitoring remain open.
- The next observed reconciliation completed successfully at 14:31:18 UTC; its
  14:31:24 UTC log was the same generic success message. Railway still reported no
  warnings, critical issues, recent failures or pending work. Persisted finding
  counts remain unverified.
- A second sanitized HTTP-log sample at approximately 14:32 UTC covered 501 API
  GET records from 14:27–14:32 UTC; all returned 200, with no 5xx or upstream
  errors. This short recent sample is not an uptime/SLO measurement.
- The reconciliation log sample at approximately 14:35 UTC contained 143 generic
  success messages from Oct 15 03:18:55 through Oct 16 14:31:24 UTC; median gap
  was 15.034 minutes, maximum 17.877 minutes, with no gaps over 20 minutes or
  failure/error messages. Persisted finding counts and alerting on a real finding
  remain unverified, so this is monitoring evidence but not formal acceptance.
- Read-only staging backup check at approximately 14:45 UTC confirmed Railway's
  latest scheduled run succeeded at 03:34:50 UTC; its log at 03:34:51 UTC recorded
  a completed manifest upload. Railway reported no warnings, critical issues or
  recent failures. No backup was triggered and no data was changed; this does not
  replace restore validation or verify backup contents.
- Reconciliation follow-up at approximately 14:48 UTC: the next scheduled
  report-only run succeeded at 14:47:38 UTC and logged the generic success message
  at 14:47:45 UTC. Railway reported zero warnings, critical issues, or recent
  failures and no pending work. Persisted finding counts remain unverified.
- A sanitized API HTTP-log sample checked at approximately 14:48 UTC covered 501
  records from 14:41–14:48 UTC; all were GETs (499 HTTP 200, two HTTP 302), with
  no non-GET method or 5xx. This is a bounded request sample, not an uptime/SLO
  result.
- A click on the empty staging contact form's “Send message” control left the page
  on `/contact`; Railway recorded only 169 GETs and no POSTs between 14:33 and
  14:35 UTC. No inquiry or email was submitted. This is a negative smoke check,
  not evidence of successful inquiry persistence or delivery.
- A sanitized Railway HTTP-log sample checked at approximately 14:13 UTC covered
  501 staging API GETs from 04:20 to 14:13 UTC: 499 returned 200 and two returned
  499 when the client closed the request before a response (2 ms and 8 ms). There
  were no 5xx responses; treat this as a bounded sample, not an uptime guarantee.
- An isolated local Playwright inquiry-form/layout run passed 25/25 checks across
  320–1440px, including labels, mobile navigation keyboard behavior and form
  control bounds. The test assertions were corrected to allow the file upload's
  live status text in its accessible description and to account for the padded
  preview wrapper. This used only a local fallback server; it is not deployed
  staging evidence and does not close B7.
- At approximately 14:24 UTC, the authorized staging browser returned API health
  `status: ok` and the same two retail catalogue listings (35 available Red
  Flowers; White Flowers unavailable). The 390px retail checkout page showed an
  empty cart, $0 estimated total and disabled checkout button. No item was added
  and no checkout was submitted; this is UI smoke evidence only, not B3/B5
  purchase acceptance.
- A 390px staging visit to `/checkout/wholesale` with no wholesale account showed
  “Wholesale checkout requires an approved account” and offered sign-in/request
  access; no checkout controls or order were available. This is a read-only UI
  guard observation only, not API authorization or approved-account checkout
  acceptance.
- A read-only visit to staging `/admin/orders` without an application login
  redirected to `/admin/login`; no order data was shown. The staging recovery and
  account-security pages also showed sign-in required without exposing account
  details. This checks only unauthenticated UI gating, not authenticated operator
  authorization or session security.
- A staging browser accessibility spot-check at 390px on `/order-flowers` showed
  visible custom-request field captions, but the browser panel's accessibility
  summary marked controls as missing names. Source inspection confirms explicit
  `<label htmlFor>` associations in `InquiryForm`, explicit `<label for>` on the
  admin login and recovery pages, and wrapping `<label>` elements on wholesale
  sign-in fields. Treat the panel result as an apparent snapshot/tool discrepancy,
  not a confirmed label defect; retain real assistive-technology verification as
  open.
  The login page's “Forgot password?” link opens `/admin/security/recovery`,
  which renders an email field and “Send recovery link” control; the email field
  appears in source with an explicit label. The recovery control was not clicked.
  No form was submitted.

## Production validation summary

- Production Railway backend and Postgres exist; direct `/api/health/` returned
  healthy. Production frontend/domain, public cutover, R2, Stripe live flows,
  Resend production flows, scheduled jobs, backups/restore and controlled live
  operational checks have not been validated.
- Full credential/data isolation has not been accepted; R2 configuration separation
  and environment-scoped Railway resources provide only partial evidence.
  Do not approve live schema changes or
  customer-impacting flows without a verified backup/restore plan and the existing
  release approval.

## Open launch blockers

1. Production backup/restore policy and an approved production recovery rehearsal;
   the staging logical restore (including media and escrow-key retrieval) is
   complete, but does not establish production recoverability.
2. Production scheduled reconciliation/security/refund jobs and verified operator
   alerts; staging reconciliation-alert receipt and sustained monitoring remain
   open as well.
3. Remaining deployed Stripe, Resend, R2/media and account/security rehearsals.
4. Phase 12.5 automated quality/release checks.
5. Phase 12.6 IaC/drift-control baseline.
6. Phase 7 owner rehearsal and controlled live account/device check.
7. Phase 13 final content/assets/accessibility/client approval and cutover plan.
8. Known exceptions to resolve or explicitly isolate: inquiry #4 deletion error,
   unmatched $30 Stripe test-mode Checkout (owner evidence indicates a Stripe CLI
   test artifact; see the detailed note), historical quote #9 review, legacy
   public full-size JPEG object, private-photo recovery checks, and concurrent
   near-limit upload stress.

## Evidence map

- Archived master scope: `deprecated/honey-summer-plan.md` (historical only).
- Detailed acceptance register: `backend/PRODUCTION_READINESS.md`
- Latest targeted staging log: `backend/PHASE12_STAGING_VALIDATION_2026-10-14.md`
- Release procedure: `RELEASE_RUNBOOK.md`
- Railway configuration: `.railway/README.md`
- Historical closeouts: `deprecated/PHASE8_CLOSEOUT.md`,
  `deprecated/PHASE9_CLOSEOUT.md`, `deprecated/PHASE11_CLOSEOUT.md`.
- Feature/operator docs: `backend/PHASE9_ACCEPTANCE.md`,
  `backend/PHASE10_CART.md`,
  `backend/ACCOUNT_SECURITY.md`, `backend/OWNER_OPERATIONS.md`,
  `backend/INVENTORY_RUNBOOK.md`, `backend/BOUQUET_PROPOSALS.md`,
  `backend/MEDIA_HANDLING.md`, `IN_PERSON_SALES.md`,
  `frontend/WORKERS_DEPLOYMENT.md`
- Code/test audit: 243 backend test functions across 27 files, 21 frontend test
  cases and 18 release/infra test cases were inventoried; CI runs backend tests
  against Postgres including opt-in concurrency settings. Current repo migration
  head is `d4a7b0c3e6f9`.
