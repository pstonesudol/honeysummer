# Phase 12 — consolidated production acceptance

**Current status index:** [`../STATUS.md`](../STATUS.md). This file is the detailed
acceptance evidence register; feature closeouts, runbooks and dated staging logs
are supporting evidence, not separate status trackers. Ownership reconciled
October 10, 2026. **Every acceptance checkbox below remains open unless and until
it is explicitly checked with evidence.** Local builds, sandbox API checks,
targeted staging passes and signed mock webhooks do not prove deployed/live
verification or complete a row.

## Ownership and completion

Current targeted staging retests (October 14, 2026 UTC), including PR #23/#24
regression results and remaining operational gates, are tracked in
`PHASE12_STAGING_VALIDATION_2026-10-14.md`. This newer evidence supersedes earlier
upload-failure/mobile-defect snapshots only for the cases explicitly retested;
it does not close the consolidated acceptance rows below.

- Feature phases own implementation, automated/local/test-mode verification, functional acceptance and operating instructions. Phase 12 owns production setup, deployed staging/provider rehearsals and controlled live operational acceptance.
- Phase 13 owns final brand/content approval, launch authorization, cutover and post-cutover smoke/rollback checks. It consumes this register instead of repeating production setup.
- Moving a check here does not waive it. Defects return to their feature phase for correction, then Phase 12 retests. Unfinished security/features are not DevOps tasks.
- Phase 7 device/account eligibility and Tap to Pay setup were confirmed by the user on October 10, 2026; owner practice/stock-recording rehearsal remains unverified separately. Phase 8 implementation/local closeout is complete (`../deprecated/PHASE8_CLOSEOUT.md`); its actual hosted provider verification and pre-live business-policy confirmation remain here. Phase 11 implementation/local verification is complete (`../deprecated/PHASE11_CLOSEOUT.md`); every deployed security/mail/operational check below remains open. Phase 9 owner acceptance was assumed at the user's prior instruction, not observed.
- Use isolated staging/provider test mode first. Actual live charges, refunds, emails, stock changes and DNS changes need explicitly authorized controlled procedures. Never run synthetic fixtures on the live shop database or blindly retry uncertain sends/refunds. Production debug payment bypasses must be disabled.

For **each accepted check**, record its ID, operator, timestamp, deployment/git revision, environment/provider mode, redacted evidence link, expected/actual result, blockers/fixes and retest outcome. No checkbox is acceptance without evidence and operational sign-off. Document any inapplicable scope decision; safety-critical failures block launch. Do not record secrets, recovery tokens, private photos or unnecessary customer data here.

## A. Hosting, routing and release — Phases 1–4

### Initial Railway configuration preparation — October 10, 2026

- Read-only CLI inspection confirmed Honey Summer staging has a running Postgres
  18 service and its 500 MB volume in `iad`; production has no deployed resources.
  The backend exists as a pending dashboard change, not a deployed service.
- Imported staging infrastructure with variables unmanaged (no secret values)
  and created `.railway/railway.ts` for both environments. Replaced the deprecated
  per-service `railway.json`; installed the pinned Railway TypeScript SDK.
- Read-only CLI plans: staging adds one backend; production adds Postgres, its
  volume and one backend. Both report zero changes/deletions to existing resources.
  Existing staging database/volume match the imported configuration.
- Following explicit user approval, applied **staging only** using the Railway
  CLI. The backend instance now exists with the declared build, migration,
  start and health-check settings; Railway triggered a GitHub build at revision
  `49454ca129348199f858698b2a3560a76796ef16` (deployment
  `e7de0706-3465-441c-b6f1-6a15fee4f255`, created `2026-10-11T02:54:42.401Z`).
  The existing staging Postgres/volume were unchanged; production remains empty.
- Staging deployment `1372843b-c902-4792-aa68-2a52629f7adc` ran the initial
  migrations through `b2e5a8d1c3f4` after correcting the database reference,
  but failed health checks: Sanic received literal `$PORT`. Corrected the IaC
  start command to use `sh -c` with `exec` and applied staging configuration
   again. Subsequent user dashboard evidence showed an active successful
   staging deployment; runtime logs confirmed a ready Sanic worker on port 8080.
- The user generated `https://honeysummer-staging.up.railway.app` targeting
  port 8080. The assistant fetched `/api/health/` over HTTPS and received
  `{"status":"ok","service":"honey-summer-api"}`. This proves direct API
  liveness only, not Workers proxy/security or database/provider readiness.
- **Production acceptance and launch are not verified.** Workers routing,
  providers, backups/restore and all checks below remain open.

### Worker configuration preparation — October 10–11, 2026

- Prepared named staging/production environments in `frontend/wrangler.jsonc`,
  independent self-bindings, explicit build/preview/deploy scripts and
  `frontend/WORKERS_DEPLOYMENT.md`. Production requires its own HTTPS backend;
  staging uses the verified Railway API origin. No custom-domain routes added.
- Build and deploy use identical generated runtime configuration. Both rebuild
  per environment, reject ambiguous targets, and avoid concurrent shared outputs.
  Staging emits noindex/nofollow metadata; this is not access control.
- Local verification: 11 frontend tests, ESLint, staging Next/OpenNext build and
  `wrangler deploy --dry-run --env staging` passed. Checked compiled API/admin/media
  rewrites, staging self-binding and rendered noindex metadata. No hosted Worker,
  production build/provider acceptance or DNS cutover was performed.
- Cloudflare deployment remains blocked on account email verification/member
  access. Confirm the final staging frontend URL and align Railway `PUBLIC_ORIGIN`
  and payment return URLs before hosted testing. All acceptance rows remain open.

### Production Railway provisioning — October 11, 2026 UTC

- After explicit user approval, reviewed and applied the production IaC plan:
  three additions (Postgres, volume and backend), no changes/deletions to existing
  resources. This supersedes the earlier snapshot describing production as empty.
- MCP confirmed production Postgres 18 successfully deployed
  (`8dc9fb4b-2eea-434e-bb08-27167f91176f`) and its 500 MB volume mounted in `iad`.
  The backend build was triggered (`29bef210-19f5-46a9-bce3-dce2af5a5d99`).
- Railway service/volume IDs are project-level and can match staging; the actual
  service and volume instances are scoped to separate environments. No database
  data or staging secrets were intentionally copied by this apply.
- User reported saving production backend variables and generated
  `https://honeysummer-production.up.railway.app`. The assistant fetched
  `/api/health/` over HTTPS and received
  `{"status":"ok","service":"honey-summer-api"}`. Direct production API
  liveness is verified; key isolation/backup, schema state, proxy/security,
  provider flows and backup/restore still require evidence. No live transaction,
  custom-domain route, DNS cutover or launch was authorized/performed.

### Sequential backend release preparation — October 11, 2026 UTC

- User explicitly selected manual production approval. Prepared
  `.github/workflows/release.yml`: successful main push CI → exact-SHA staging
  upload → deployment-ID verification and read-only health/catalogue checks →
  protected production approval → same source archive/SHA deployment and checks.
  Serialization includes the approval wait; stale queued main revisions fail closed.
- Applied empty backend sources in staging/production IaC. Live API inspection
  confirmed zero Railway deployment triggers in both environments, so main cannot
  independently deploy production. Existing backend deployments remain successful;
  direct HTTPS catalogue endpoints returned empty arrays in both environments.
- Configured GitHub environments `staging` and `production` with main-only policies.
  Production requires `pstonesudol` approval, disallows admin bypass and permits
  self-review for the sole operator. Protected main requires both CI checks and a
  PR merge with up-to-date checks; admin bypass/force pushes/deletion are disabled.
- Local release gate tests: 3 passed. Actionlint validated the final CI/release
  YAML, including the stale-main check; `git diff --check` passed.
  No workflow has been committed/merged or exercised against Railway by this work.
- Railway project-token creation returned `Not Authorized` (trace
  `4125898916101255932`). No deploy tokens were stored. Create separate
  environment-scoped project tokens and store each as `RAILWAY_TOKEN` in its
  matching GitHub environment. See `../RELEASE_RUNBOOK.md` for activation,
  approval, migration and recovery steps. New merges no longer autodeploy while
  the workflow/token setup is pending.
- This is backend-only preparation; Cloudflare access/frontend orchestration,
  successful/rejected release rehearsals and backup/restore remain open. A3/A4
  and all launch acceptance checkboxes remain unchecked.

### Backend release and hosted staging update — October 11, 2026 UTC

- Supersedes the unmerged/token/access-blocked snapshots above. User merged PR
  [#1](https://github.com/pstonesudol/honeysummer/pull/1), revision
  `c9e0744cc04f998592ec9268ebbcc33697681215`, resolved Railway account verification
  and stored separate `RAILWAY_TOKEN` environment secrets. The first staging run
  failed closed for a missing token; retry succeeded. Release run
  [38109825138](https://github.com/pstonesudol/honeysummer/actions/runs/38109825138)
  completed successfully after the user's manual production approval.
- Railway confirmed staging deployment `6cc7382b-e194-4ba5-a3f2-93b7b01228f3`
  and production deployment `1bcb0d94-fca2-474e-ba63-762e0cb576dc` successful,
  with one running/no crashed replicas. Backend health/catalogue checks passed.
  This verifies one successful backend release sequence, not failure/rollback
  recovery, frontend promotion or public launch acceptance.
- User accepted Cloudflare account membership and authenticated Wrangler against
  the owner's account `1b3166589a8439bce7657a8c372d2791`. User deployed
  `honey-summer-staging`, attached only `staging.hellohoneysummer.com`, and rebuilt
  with that exact frontend origin. Reported Worker version:
  `89a14c62-69dc-45b5-9634-16d3789c5359`. Production frontend/domain remain unchanged.
- Assistant read-only checks at approximately 14:14 UTC: custom-domain homepage,
  `/api/health/`, `/api/retail/flowers/` and `/admin/login` returned HTTP 200.
  Health identified `honey-summer-api`; catalogue returned an array. Browser
  snapshots confirmed homepage, order-page empty catalogue state and admin login
  rendering. Homepage robots metadata contains `noindex`. Admin login CSRF cookies
  have Secure, HttpOnly and SameSite=Lax flags; authenticated session behavior,
  actual CSRF/Origin enforcement and role/session revocation are still unverified.
- No forms submitted, accounts created, payment/email fixtures run or customer
  data changed. Browser reported an image-preload warning; no console errors.
  User's Railway staging screenshot shows matching `PUBLIC_ORIGIN` and `DEBUG=false`.
- Next: scoped Cloudflare CI credentials and frontend release orchestration,
  protected staging access, operator sign-in/proxy/security checks, R2 activation
  with approved usage billing and public/private storage verification. Local OAuth
  is not a GitHub Actions credential. A1–A4/F2 remain open for their broader scope.

### Staging frontend release extension — prepared October 11, 2026

- Extended the existing release staging job to preflight both provider
  credentials/account, deploy backend then build/deploy the staging Worker from
  the same CI-tested SHA. Production still deploys the backend only after the
  existing manual gate; no production Worker/domain or provider policies changed.
- Added fixed-origin, read-only HTTPS smoke checks for homepage/order page with
  noindex, API health/catalogue JSON and admin-entry HTML/secure CSRF cookies.
  Redirects, bad status/type/body, missing noindex/form/cookie flags and network
  errors fail closed. Sanitized evidence includes SHA, Worker, origin, paths and
  verification timestamp; no cookies/customer bodies are retained.
- GitHub metadata confirms staging Cloudflare token secret and correct account-ID
  variable. Seven release tests, eleven frontend tests and frontend ESLint passed.
  Actionlint and `git diff --check` passed. Live validators passed via a public-DNS IP override; normal local Node lookup
  still returned ENOTFOUND. CI uses normal DNS without a bypass. Workflow extension
  still requires merge/first Actions deployment evidence; A3 remains open.

### Staging operator login defect — October 11, 2026

- User supplied successful **Verify staging Access (read-only) #1** evidence on
  main `f33ae005f522c5c3470cc6fc506c9e1c164ecdd5`: anonymous/invalid-token
  custom-domain requests denied, valid CI token passed all probes. This is
  custom-domain Access evidence, not direct Railway origin acceptance.
- With user approval, prepared local staging-only origin gate, Worker/runtime
  server-fetch injection and staging CI direct-probe credentials. Gate is opt-in,
  rejects production/debug scope and unsafe/missing secrets at startup, and leaves
  only exact read-only health and signature-validated configured sandbox webhook
  exceptions. Direct-origin positive/negative checks are opt-in after activation.
  No secrets provisioned, provider settings changed or live code deployed here.
  User explicitly prohibits all Git actions without approval; none performed for
  this work. Hosted activation/retest remains open; rollout is in RELEASE_RUNBOOK.md.

- Access follow-up: user created the staging custom-domain application with the
  CI Service Auth policy and the two-address human Allow policy, added One-time
  PIN and confirmed human email-code login. User also confirmed the custom domain
  still works and workers.dev no longer serves staging with both URL toggles off.
  Preparing a persistent staging-only workers_dev=false setting and a manual
  read-only positive/negative CI token check. Hosted CI after activation remains
  unverified until that workflow runs; direct Railway origin review remains open.
  User reported approving the production backend release; final job success has
  not been independently confirmed here. No production frontend cutover claimed.

- Follow-up: user confirmed hosted admin sign-in, logout/protected-page recheck
  and fresh sign-in after PR #3. This verifies the reported login loop is fixed;
  it does not complete the wider deployed security acceptance checklist.
- Stripe hosted Checkout return follow-up — October 11, 2026: after a staging
  checkout initially returned to localhost, staging-only Railway success/cancel
  URLs were set to `https://staging.hellohoneysummer.com` and the backend
  redeployment succeeded. PR #10 added the checkout-key return recovery and
  duplicate-toast guard; the user confirmed the merged staging flow looked good,
  including the return and confirmation toast. No production settings or live
  payments were involved. This is targeted checkout-return evidence only; it
  does not close B3/B5/C1 or replace signed webhook, expiry, async/failure,
  refund, inventory-recovery and separate-cart acceptance.
- Read-only staging follow-up — October 11, 2026: through the human-authenticated
  Cloudflare Access session, Worker `/api/health/` and retail catalogue returned
  expected responses; anonymous `/api/auth/me/` returned no identity and `/admin/`
  redirected to `/admin/login`. Unauthenticated requests to the public Worker
  received the Access sign-in page. Direct Railway-origin catalogue and admin
  requests returned 403; the explicitly allowed direct-origin health probe
  returned healthy. A manual staging `python -m app.reconcile` report-only run
  completed with zero findings (`applied=false`); it wrote the normal audit row
  and did not alter stock or send mail. Infrastructure inspection found only
  the backend and Postgres services, no scheduled job/cron, no R2 bucket, and no
  Resend or R2 variables on the staging backend. Therefore provider-backed mail,
  media, scheduled reconciliation/alerts and the broader authenticated security
  checks remain open; no provider resources, credentials or alert policies were
  created or changed.
- Security probe follow-up — October 11, 2026: unauthenticated `curl` requests to
  staging admin/auth endpoints received Cloudflare Access redirects with
  `no-store` and Secure/HttpOnly Access-session cookies. In the human browser
  session, `/admin/login` loaded normally. This confirms the outer Access gate
  and the login page are reachable, but does not expose the application response
  headers or session-cookie attributes. No admin credentials were submitted and
  no mutation or rate-limit probe was sent. Authenticated application-header,
  CSRF/Origin/CORS, forwarding/IP, role/session revocation and deployed throttle
  checks remain open; the public Access redirect prevents completing these
  probes without an authorized authenticated test session.
- Authenticated staging inspection — October 11, 2026: user signed in through
  the browser and the admin dashboard and account-security page loaded as an
  active admin. The account-security page reports MFA is not enabled. No account
  settings, credentials, MFA configuration, or sessions were changed. This
  verifies one admin happy path only; MFA enrollment/recovery, session cookie
  attributes, CSRF and proxy-header behavior, role boundaries/revocation,
  throttles and token replay tests remain open.
- MFA follow-up — October 11, 2026: user subsequently confirmed that MFA works
  for the staging admin, including the sign-in flow. No password, authenticator
  secret/code or recovery code was recorded. This addresses the single-account
  MFA setup/sign-in check; recovery-code rehearsal, other roles, MFA recovery,
  and the remaining F2–F5 deployed security checks remain open.
- Resend staging setup — October 11, 2026: user verified
  `staging-updates.hellohoneysummer.com` in Resend. Its dedicated sending DNS
  records were added to Cloudflare without changing root Google mail records;
  all required records resolved and the domain became verified. The staging
  Railway service now has `RESEND_API_KEY` and
  `DEFAULT_FROM_EMAIL=Honey Summer Staging <hello@staging-updates.hellohoneysummer.com>`;
  deployment `38b9ebc5-004d-4220-a031-7e344cf16c50` succeeded. Production was
  untouched. User confirmed a deliberate staging retail order test generated an
  order-confirmation email that arrived in the recipient's spam folder. This
  verifies application-triggered provider acceptance and inbox delivery, but not
  inbox placement. Message headers showed SPF pass, aligned DKIM pass, Microsoft
  DMARC `bestguesspass`/`action=none`, and composite authentication pass, while
  the message was still classified as junk (SCL 5). No explicit DMARC record is
  published for the staging sending subdomain. A public DNS-only recheck on
  October 16 confirmed the staging Resend DKIM TXT record and the `send` host's
  MX/SPF records still resolve, while `_dmarc.staging-updates` remains
  unpublished. Record values were not copied. Authentication-result review is
  complete; optional staging DMARC monitoring, spam placement/reputation work,
  Resend event review, and broader email workflow coverage remain open. A later
  inquiry-email attempt was blocked by required form controls in browser
  automation; read-only database count remained zero, so no inquiry or additional
  email was created/sent. On October 12, 2026, a user-submitted staging contact
  inquiry failed in the storefront-to-backend fetch before Railway received it;
  redacted Worker diagnostics recorded a TypeError at the fetch stage with the
  staging API URL and origin credential present. The server action was changed
  to use the configured Worker self-service proxy and deployed to staging as
  `9851eccb-5def-4819-8c47-ab4f26519400`; the subsequent inquiry reached Railway
  with HTTP 201. Staging persisted provider outcomes as accepted for both the
  customer acknowledgment and farm notification. A Resend dashboard screenshot
  showed both messages as `Delivered`; the user also confirmed the customer
  confirmation arrived. `Delivered` confirms recipient-server acceptance, not
  inbox placement, so farm-mailbox placement remains unconfirmed. A subsequent
  controlled staging wholesale approval showed the account active/approved and
  Resend reported `Delivered` for the account-access update and administrative
  notification. These statuses verify provider acceptance, not mailbox placement.
  Invoice-related emails, link/reply-to review, and broader Resend event/workflow
  coverage remain open.
- Zero Trust Free activated by the user. Staging CI service-token secret names
  confirmed present in GitHub, with raw values kept private. Preparing fixed-origin,
  no-redirect Access-authenticated smoke requests and stripping Access credentials
  before Railway. Application/policies and alternate-origin protection remain
  pending; staging is not yet accepted as Access-protected.

- User reported sign-in returning to the login page without an error. Read-only
  Railway HTTP logs show POST `/admin/login` returning 302, then backend GET
  `/admin/` returning 302 back to GET `/admin/login` (200); no runtime exceptions.
  Inspection of the installed OpenNext fetch proxy found no `redirect: "manual"`:
  it follows the login redirect inside the Worker, losing the session Set-Cookie
  response before it reaches the browser. No passwords/session tokens were read.
- Prepared a supported custom Worker entry point that proxies backend paths with
  manual redirects, preserves separate cookie fields, Origin/body/CSRF/error
  statuses, no-store admin/auth and the existing 12 MiB streaming upload limit.
  Backend absolute redirects become same-origin paths; external payment redirects
  are returned without fetching them. Frontend handling remains OpenNext-managed.
- Regression coverage includes login/logout redirects/cookies, API/media routing,
  external redirects, invalid origins, and declared/chunked upload limits. Added
  anonymous admin 302 preservation to the staging smoke gate so this defect can be
  caught without login credentials. Local staging OpenNext build and Wrangler
  dry-run passed, along with eighteen frontend tests, eight release tests, ESLint
  and `git diff --check`. Actual corrected hosted sign-in/logout must be retested after
  the fix merges/deploys; A2/A3/F2/F3 remain open. No account/security bypass added.

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
- [ ] C5 — Device/account eligibility and Tap to Pay setup are user-confirmed (October 10, 2026). After the separate Phase 7 owner rehearsal, verify the intended live account/device and an approved controlled sale/refund with separately audited stock recording. No live transaction evidence is claimed by that confirmation. Dashboard charges do not automatically create Checkout orders.

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

- Staging F2 spot-check — October 12, 2026: in Chrome DevTools the admin session
  cookie was observed with Secure, HttpOnly, SameSite=Lax and Path=/; CSRF cookies
  were Secure/HttpOnly, with the admin CSRF cookie SameSite=Lax and security CSRF
  cookie SameSite=Strict. A same-origin POST to `/admin/logout` with a deliberately
  invalid CSRF token returned HTTP 403 (`Invalid CSRF token`) and did not sign out
  the session. A valid staging logout returned HTTP 302 to the login page; its
  response cleared the admin cookie (empty response-cookie value), and the cookie
  was absent from browser storage afterward. Unauthenticated requests to staging
  admin/API paths were redirected
  by Cloudflare Access. A browser request from `https://example.com` to a
  deliberately nonexistent staging API probe path returned HTTP 403; the browser
  reported no `Access-Control-Allow-Origin` header and blocked response access.
  This verifies denial of that cross-origin mutation, not the complete CORS policy
  or valid same-origin form behavior. Read-only Railway staging inspection found
  no `TRUSTED_PROXY_CIDRS` service variable or shared variable. With the setting
  empty, the application ignores `X-Forwarded-For` for security-context hashing
  and hashes the direct peer address instead; this is spoof-resistant but does not
  establish per-client IP attribution through the deployed proxy. Confirm the
  platform's trusted proxy ranges and exercise forwarding behavior before enabling
  any allowlist. Full cookie lifecycle remains open. Cookie values were not
  recorded.

- [ ] F1 — Source-phase implementation, permission matrix, local adversarial tests/security review and admin recovery/break-glass instructions completed first.
- [ ] F2 — Real proxy preserves Secure/HttpOnly/SameSite cookie flags/scope, CSRF/Origin/CORS protections and trusted forwarding/IP handling.
- Staging F3 anonymous check — October 12, 2026: after the application admin
  session cookie was confirmed absent following logout, opening `/admin/` showed
  the login page rather than the dashboard. While signed out, `/wholesale` showed
  the sign-in/request-access form and no wholesale catalogue or prices. These
  verify the anonymous admin and florist boundaries. The existing approved
  staging florist account then signed in successfully and reached its wholesale
  home; no stems were listed, so catalogue/pricing authorization and purchase
  behavior could not be exercised. Florist sign-out returned to the sign-in form,
  which remained after reload. A dedicated staging staff test account was then
  created: sign-in reached the orders area, `/admin/orders/preparation` was
  accessible, and `/admin/security/access` was denied. No orders were changed.
  Follow-up on October 12, 2026: after suspension and reactivation, the old
  staff session was redirected to sign-in and a fresh sign-in reached the staff
  orders area. A read-only session-registry check showed one stale-version
  session and two current-version sessions. This verifies revocation/reactivation
  on staging's single backend replica, not cross-worker revocation. At 11:07 PM
  EDT, reloading the untouched staff `/admin/orders` tab returned the application
  sign-in page; a read-only registry check showed the current-version sessions
  had been idle over 35 minutes. The 30-minute idle-expiry check passed on this
  replica. The user then signed in fresh; the staff orders area loaded and the
  registry gained a new unique hashed session record with a 12-hour lifetime
  while the prior idle sessions remained expired. This verifies server-side
  session rotation without reading cookie values. Staff sign-out then redirected
  to the login page; the session registry dropped from four rows to three and
  from three current-version rows to two, and a fresh `/admin/orders` request
  stayed at login. Actual 12-hour absolute expiry and cross-worker revocation
  remain unverified.
- [ ] F3 — Roles/approval/active state, revocation across workers, session rotation and idle/absolute expiry verified for anonymous/florist/staff/admin access.
- [ ] F4 — Rate limits, enumeration resistance, single-use/expired/replayed reset/invite tokens, reauthentication, admin/staff MFA and recovery verified against deployment.
- [ ] F5 — Redacted audit events, security/privilege/mail alerts, privacy/retention/export handling and admin incident response exercised.

## G. Operations and launch handoff — all phases

- [ ] G1 — Redacted logs, uptime/error/usage alerts, retention, incident owners, runbooks and manual reconciliation verified; escalation rehearsed.
- [ ] G2 — Automated Postgres backups/retention and an actual restore to an isolated environment verified, including media recovery; successful backup alone is insufficient.
  - **Blocked — October 11, 2026 UTC:** Railway API inspection found no volume
    backup schedules for staging or production. Attempting production
    daily/weekly/monthly schedules returned `BAD_USER_INPUT`: "Manual backups
    and backup schedules are only available for Pro workspaces" (trace
    `1630370919026007653`). No backup policy was enabled; no restore was run.
    Production PITR inspection also reported disabled/unwired, not an active
    substitute. No workspace upgrade or PITR-enabling redeploy was authorized.
  - **Current direction — October 14, 2026:** use a logical `pg_dump` job over
    Railway private networking; encrypt the DB dump and staging public/private R2
    objects client-side; upload to a dedicated private R2 backup bucket. A daily
    03:30 UTC schedule and 14-day retention are configured. Railway cron is expected
    not to require a plan upgrade; metered compute/storage may still incur charges.
  - Local code and tests are in `app/backup.py`, `app/restore_backup.py`,
    `tests/test_backup.py`, `tests/test_restore_backup.py`, and
    `backup.Dockerfile`. GitHub workflows provide failure alerts and an on-demand
    staging run trigger; details are in `BACKUP_RUNBOOK.md` and
    `STAGING_BACKUP_SETUP_REVIEW.md`. The staging-only cron service completed two
    manual runs, each producing an encrypted database dump, four media objects,
    and a final manifest. Its private R2 destination has 14-day snapshot retention.
    A separate staging restore Postgres service and two restore buckets were
    provisioned with public access disabled for the rehearsal. On October 16,
    2026 UTC, snapshot
    `snapshots/2026/10/15/e79086d9ea1c4aa589a5e6a1acad831e/manifest.json.hsbackup`
    was restored through the guarded workflow to
    `staging-restore-postgres.railway.internal/railway` and the isolated public
    and private restore buckets. The successful Railway run log reports one
    database archive, two public media objects and two private media objects;
    R2 object listings confirm two objects in each target bucket. The run
    authenticated/decrypted the snapshot, checked ciphertext and plaintext media
    hashes, verified the targets were empty before writing, and `pg_restore`
    completed successfully. An earlier attempt crashed before reading the backup
    because the four newly entered credentials were still staged; it made no
    writes. The credentials were activated only in staging and have a 24-hour
    TTL. A read-only SQL check confirmed restored Alembic revision
    `d4a7b0c3e6f9`, matching repository head. SQLAlchemy ORM reads succeeded for
    users, orders, order items, inquiries and gallery images; aggregate counts
    matched the restored staging snapshot (5, 10, 10, 5 and 1 respectively). The
    staging application's `SECURITY_ENCRYPTION_KEY` passed a synthetic
    encrypt/decrypt round-trip; the restored database has no nonempty MFA or
    queued-security-mail ciphertext to test against it. A disposable local
    invocation of the staging app's `/api/retail/flowers/` handler, connected only
    to the isolated restore database over a Railway SSH tunnel, returned HTTP 200
    with two listings. Further read-only checks found no unvalidated public
    constraints or invalid indexes; all 28 foreign keys, 27 primary keys, and 15
    unique constraints are validated. Each populated table's ID sequence matched
    its maximum ID, avoiding an immediate sequence collision on future inserts.
    Full ORM `SELECT`/row-deserialization checks succeeded for all 26 mapped
    application tables (389 rows). Both restored private inquiry images were read
    using the application's `read_private_image` function and decoded as valid
    JPEGs; both public restore-bucket objects decoded as valid images as well.
    Cloudflare reports no custom domain on the private restore bucket and confirms
    its managed `r2.dev` public-access endpoint is disabled.
    The two restored private inquiry-media references and the restored gallery
    image reference exist in their corresponding R2 buckets. One additional
    public object is not referenced by current `flower_listings`, `gallery_images`
    or inquiry media columns; it was retained as part of the snapshot and not
    treated as corruption. A PostgreSQL `pg_amcheck` binary and `amcheck` extension
    were unavailable on the managed restore service, so low-level page checks were
    not run. Production was untouched.
    - The owner independently retrieved both `BACKUP_ENCRYPTION_KEY` and
      `SECURITY_ENCRYPTION_KEY` from escrow and confirmed exact matches with their
      staging service values using hidden terminal prompts; no key material was
      shared. The configured application key passed a synthetic round-trip, but
      the restored database contained no MFA or queued-security-mail ciphertext
      to validate against it. After explicit owner approval, cleanup removed the
      restore runner, restore Postgres and its 5 GB volume, both restore buckets,
      and their four restored media objects. Follow-up Railway/R2 inventory found
      no restore service, volume, bucket, or pending cleanup operation; staging
      app/Postgres/jobs and the encrypted backup bucket remain. The short-lived
      restore credentials were attached to the deleted restore resources and are
      no longer present there. Production was untouched. On October
      16 a controlled in-process exception replaced `create_backup` before any
      storage operation; the backup job dispatched
      `staging-backup-alert.yml` (run `38831354476`), which emitted the generic
      notification. This exercises the job's failure handler without writing a
      backup. On October 15 at 8:46 PM, the owner supplied a screenshot of the
      corresponding GitHub Actions failure email, confirming alert receipt.
      The backup encryption key also encrypts copied media;
      `SECURITY_ENCRYPTION_KEY` is a separate application key and was not needed
      for this raw archive restore.
      The staging logical recovery rehearsal is complete. The G2 production
      acceptance checkbox remains open: production backup policy, isolated restore
      evidence, operational monitoring, and launch sign-off are not established by
      staging evidence. The managed restore service lacked `pg_amcheck` and the
      `amcheck` extension, so low-level page verification was unavailable.
  - The October 11 note that R2 was blocked predates the October 13 creation of
    staging public/private media buckets. Those media buckets are not reused for
    database backups. Restore must use the isolated restore targets and scoped
    credentials; public TCP and SSH access remain disabled.
  - Railway native volume restores are limited to the same project/environment
    and replace the service mount on apply; never test that operation against
    the working production database. A logical restore to a disposable Postgres
    verifies logical recovery, not native snapshot restore. Back up the separate
    application `SECURITY_ENCRYPTION_KEY` separately and preserve the backed-up
    public/private media. Staging targets used for the October rehearsal have been
    cleaned up; provision fresh isolated targets for any future restore. Production
    G2 remains open.
- [ ] G3 — Intended domain, redirects, DNS/TLS, Workers routes, Railway origin and email DNS checked before cutover; TTL/rollback/contact plan approved.
- [ ] G4 — All applicable checks pass with evidence; source feature/owner acceptance or explicit prior waivers reconciled, no unresolved launch blockers, operational sign-off recorded.
- [ ] G5 — Handoff to Phase 13 for final assets/copy/licensing/SEO/accessibility approval, launch authorization, public cutover and post-cutover smoke/rollback checks.

### Additional staging acceptance evidence — October 12, 2026

- Read-only Railway checks found the staging API and Postgres online with one
  running replica each, no recent deployment failures/issues, no pending Railway
  changes, and successful backend deployment
  `164097df-fc42-4a3e-95b0-0966d4b7d585`. The database is at Alembic head
  `c3f6a9b2d5e8`; `alembic check`
  reported no new upgrade operations. Runtime configuration reported `DEBUG=false`,
  the staging public origin and origin gate enabled, and Stripe test-mode keys.
  This is staging-only evidence; production was not inspected or changed.
- Ran `python -m app.reconcile --full` in staging report-only mode. The durable
  run record shows `applied=false` and zero findings; inventory and overdue holds
  were not changed. This is a manual full reconciliation rehearsal, not a
  scheduled or monitored job, and does not close C3/C4.
- Ran the staging invoice/refund journal audit in report-only mode; it reported
  that journals agree with supported Stripe payments. No refund, restock or
  order change was made. The persisted audit does not replace scheduled
  monitoring, so C4/D5 remain open.
- Read-only security-mail outbox counts showed 26 of 26 messages accepted by
  Resend, with no attempted-but-unaccepted or never-attempted records. Provider
  acceptance is not inbox delivery. No privacy-request records exist, so export
  or deletion handling was not rehearsed and F5 remains open.
- The order-notification outbox has 14 records, all marked sent with no pending
  notification retries and at most one recorded attempt. That application status
  alone is not inbox-delivery evidence; broader E3 workflow/retry coverage remains
  open.
- Read-only security-audit counts for the dedicated staff test account show one
  successful suspension, one successful reactivation, and four successful
  password sign-ins (including the post-idle reauthentication). This confirms
  these actions were logged, not the full redaction/retention or alert-response
  requirements; F5 remains open.
- A one-hour read-only Railway HTTP-log sample (22:00–23:00 EDT) contained 209
  requests (200, 302, 400 and 403 responses), with no 5xx responses or upstream
  errors. This is a point-in-time log check, not configured uptime/error alerting
  or an escalation rehearsal; G1 remains open.
- Origin-gate probes against the staging Railway URL returned HTTP 200 for the
  health exception and HTTP 403 for the retail catalogue and admin login. Through
  the authenticated staging Worker, the health route returned `status: ok` and
  the retail catalogue rendered. Direct-origin protected-route denial is verified;
  an unauthenticated request to the staging custom-domain homepage returned HTTP
  302 to the Cloudflare Access gate. The broader A2 routing/media/upload checks
  remain open. The public Worker also served the static
  `/images/photography/flower-bucket-portrait.jpg` asset (1200×1800); this does
  not verify R2 uploads, cache policy, or protected private-media routing.
- Read-only Stripe test-account verification found one enabled staging webhook
  endpoint with the eight expected event types. All ten persisted Stripe event
  records were retrievable from that test account and matched their stored event
  types: seven `checkout.session.completed` events were applied and three
  `checkout.session.expired` events were ignored. Staging has seven paid retail
  orders and three cancelled retail orders; inventory summaries showed no
  negative available quantities or sold-out listings with positive stock. This
  verifies those historical checkout/expiry outcomes only; signed retry/replay,
  async/failure, refund and concurrency cases remain open.
- An unsigned empty POST to the staging direct-origin Stripe webhook returned
  HTTP 400. The Stripe-event record count remained ten afterward, confirming this
  invalid-signature probe did not enter the event ledger. This negative check does
  not replace a new signed delivery/retry rehearsal.
- A read-only comparison of all seven matched paid Checkout sessions against
  their stored order-item snapshots plus delivery fees found no amount, currency,
  order-status or `order_id` metadata mismatches. All three matched expired/unpaid
  sessions had local cancelled/expired orders. This validates those examples,
  not concurrent purchase behavior or fulfillment details.
- Follow-up exception: Stripe test mode lists eight `complete/paid` Checkout
  sessions, but only seven match an order's stored Stripe session ID. The unmatched
  session was created October 11 at 18:43 UTC for USD 30.00 (two units of
  `myproduct`); its test-mode PaymentIntent succeeded and has no refund recorded.
  It has no application metadata or client reference, and its completion event
  has no `stripe_events` record. The webhook handler ignores events without an
  `order_id` but does not persist that ignored outcome, so the missing ledger
  record does not establish delivery failure. The app's Checkout creation code
  sets an `order_id` metadata value, so this does not appear to be an app-created
  Checkout; no local order exists and the staging catalog has no exact
  `myproduct` listing. On October 16, the owner supplied a Stripe Dashboard
  screenshot showing the line-item product annotated “created by Stripe CLI.”
  This strongly supports an intentional Stripe CLI/test fixture, although it does
  not prove which command created the Checkout session itself. It remains an
  unmatched successful test-mode payment with no local order; the full report-only
  reconciliation did not surface it. It was left untouched; no cancellation or
  refund was attempted. Treat it as a known test artifact, not a production or
  customer transaction, while retaining the mismatch as audit evidence.
- The single bouquet proposal has a linked Stripe invoice; Stripe reports that
  invoice open, and the proposal has no associated order. No payment, resend or
  additional invoice action was taken. Invoice-paid webhooks and the wider D1/D4
  workflows remain open.
- Non-purchasing retail cart smoke tests added one available item, confirmed its
  displayed item/subtotal and wholesale-access boundary, changed quantity to two
  and confirmed the $10 subtotal, reloaded the page and confirmed the one-item
  cart persisted, navigated to Our Story and confirmed the cart remained, then
  removed the item. At that time checkout was not started and inventory was not
  reserved. Separate carts/shared-stock contention remained untested. At 390px,
  the cart drawer itself fit the viewport and exposed
  a labeled quantity input, remove control and close control; full
  keyboard/focus/screen-reader testing remains open.
  A read-only catalog summary found two retail listings (one purchasable) and no
  wholesale listings, so a wholesale catalog/purchase could not be exercised.
  - October 16, 2026 Checkout follow-up: confirmed the staging Stripe secret is
    test-mode. Created a $5 retail Checkout for a synthetic staging test buyer,
    then expired it through Stripe's test API without payment. Stripe delivered
    the signed `checkout.session.expired` event; the local order is `expired`,
    the event ledger records it once as applied, and the listing returned to 35
    available stems. A second signed delivery of the same event returned HTTP 200
    without a duplicate ledger row; an invalid signature probe returned HTTP 400.
    A subsequent report-only reconciliation persisted `applied=false` with zero
    findings. The browser cart was cleared. No payment was taken and no production
    service was touched. This does not verify a new successful paid checkout,
    refund/restock flow, delayed/asynchronous payment, or concurrent purchase.
  On the 390px mobile viewport, the closed navigation control extended beyond the
  right viewport edge (its inspected bounds were x=355–445). The wedding inquiry
  form also retained a two-column layout at that width: its first-column controls
  were only 75px wide and began at x=-15, visibly clipping labels/fields in the
  captured page. Inquiry form controls also appeared without accessible names in
  the browser snapshot. Treat mobile navigation/form usability and accessibility
  acceptance as unresolved; B1/B4/B7 are not passed.
- October 13, 2026 R2 follow-up: the owner activated Cloudflare R2 and created
  `honeysummer-staging-public` and `honeysummer-staging-private`. The public
  bucket's custom domain `media-staging.hellohoneysummer.com` reached an active
  state; its empty root returned the expected R2 object-not-found response. The
  private bucket was left private and has no custom domain. The owner set all six
  R2 variables on the staging backend; Railway's staging deployment succeeded
  with one running replica. Variable names were verified without reading values.
  An admin gallery upload of a 15.1 MB image failed at the still-deployed upload
  limit. Railway showed no gallery POST and the database had no matching gallery
  row, so a successful app upload/public delivery is not verified. The 50 MiB
  image and 60 MiB Worker limits in this local change have not yet been deployed.
  Staging private-media access and upload persistence remain unverified. No R2
  resources or variables were added to production.
- Staging reconciliation follow-up — October 15, 2026: Railway now has
  `honeysummer-staging-reconcile` (`*/15 * * * *`) and
  `honeysummer-staging-invoice-refund-audit` (`15 4 * * *`). Both use staging
  backend DB/Stripe references and are report-only; neither command includes
  `--apply`. A manual execution of each completed successfully, and both logs
  reported clean results. The reconciliation alert dispatcher was executed from
  the runner's staging Railway environment; GitHub accepted the dispatch and the
  expected workflow failed with a generic reconciliation alert. On October 16,
  a controlled workflow-dispatch verification (run `38845808631`) emitted the
  generic reconciliation alert and failed as designed. The owner supplied a
  screenshot of the corresponding GitHub Actions failure email, confirming
  receipt. This verifies notification delivery for the controlled workflow test,
  not detection/dispatch of a real reconciliation failure. C3/C4/D5 remain open
  pending sustained monitoring, review of future findings, and any
  separately approved production plan. No production resources/configuration
  changed.
- Staging read-only operations/smoke sample — October 16, approximately
  03:30–04:12 UTC: Railway reported the five remaining staging services healthy,
  no warnings/critical issues or recent failures, and no pending changes. The
  15-minute reconciliation logs showed successful runs through 04:00:27 UTC. The
  backup run completed at 03:34:51 UTC and logged a completed manifest. The
  invoice/refund audit's latest observed run was October 15 at 04:19 UTC; the
  October 16 04:15 UTC schedule had not yet fired during this sample. Direct
  staging `/api/health/` returned `status: ok`; through the authorized staging
  browser session, the home and order pages rendered and `/api/retail/flowers/`
  returned two listings. An unauthenticated custom-domain request reached the
  expected Cloudflare Access sign-in gate. HTTP requests to both the staging
  custom domain and Railway health URL returned 301 redirects to their HTTPS
  equivalents. No cart/order/payment/customer form was submitted. The generic
  reconciliation log message does not expose persisted
  finding counts; this short sample is not sustained monitoring or full
  acceptance. Production was untouched.
- Staging reconciliation spot-check — October 16, approximately 14:08 UTC:
  Railway reported the 15-minute report-only reconciliation job's latest
  execution succeeded at 14:02:22 UTC; the latest corresponding log entry at
  14:02:30 UTC said `Inventory and overdue holds reconciled.` Railway reported
  zero warnings, critical issues, or recent failures and no pending work. The
  generic log does not expose finding counts or prove a clean persisted report;
  this remains an operational spot-check, not sustained monitoring or formal
  acceptance. No job was manually triggered, no data was changed, and production
  was untouched.
- Staging reconciliation follow-up — October 16, checked at approximately
  14:15 UTC: Railway reported the 15-minute report-only job succeeded at
  14:15:04 UTC; its 14:15:12 UTC log said `Inventory and overdue holds
  reconciled.` Railway reported zero warnings, critical issues, or recent failures
  and no pending work. The log still does not expose persisted finding counts.
  No job was manually triggered; sustained monitoring/formal acceptance remain
  open, and production was untouched.
- Staging reconciliation follow-up — October 16, checked at approximately
  14:32 UTC: the next scheduled execution succeeded at 14:31:18 UTC; its
  14:31:24 UTC log said `Inventory and overdue holds reconciled.` Railway
  continued to report zero warnings, critical issues, recent failures, or pending
  work. The log does not expose persisted finding counts, so this remains a
  point-in-time report-only observation rather than accepted reconciliation.
  Production was untouched.
- Staging reconciliation log-window review — October 16, approximately 14:35 UTC:
  the sanitized deploy stream contained 143 `Inventory and overdue holds
  reconciled.` messages from October 15 03:18:55 through October 16 14:31:24 UTC.
  The median gap was 15.034 minutes and maximum gap 17.877 minutes; there were no
  gaps over 20 minutes and no failure/error messages in the 286-entry sample.
  Railway separately showed no recent failures or active issues. This is evidence
  of regular report-only execution over this window, but does not reveal persisted
  finding counts or prove alert handling when a real finding occurs; C3/C4 remain
  open. Production was untouched.
- Staging scheduled-backup follow-up — October 16, checked at approximately
  14:45 UTC: Railway reported the latest scheduled backup completed at 03:34:50
  UTC; the 03:34:51 UTC log recorded a completed manifest upload. Railway reported
  zero warnings, critical issues, or recent failures. No backup was manually
  triggered and no restore/data action was taken. This confirms only the scheduled
  job's reported completion, not manifest contents or a fresh restore; production
  was untouched.
- Staging reconciliation follow-up — October 16, checked at approximately
  14:48 UTC: Railway reported the latest scheduled report-only execution
  succeeded at 14:47:38 UTC; its 14:47:45 UTC log said
  `Inventory and overdue holds reconciled.` Railway reported zero warnings,
   critical issues, or recent failures and no pending work. The generic message
   still does not expose persisted finding counts. No job was manually triggered;
   production was untouched.
- Staging API HTTP-log follow-up — October 16, approximately 14:48 UTC: the
  latest 501 records covered 14:41–14:48 UTC and were all GET requests (499 HTTP
  200, two HTTP 302), with no non-GET method or 5xx response. This bounded sample
  does not establish uptime/SLO and no request was generated for the check;
  production was untouched.
- Staging Resend DNS follow-up — October 16, approximately 15:05 UTC: a public
  DNS-only lookup confirmed the staging Resend DKIM TXT, `send`-host MX, and SPF
  records resolve; `_dmarc.staging-updates` remains unpublished. No record values
  were copied or changed. This does not verify message delivery or inbox
  placement; production was untouched.
- Staging API HTTP-log follow-up — October 16, approximately 15:06 UTC: a
  sanitized sample of 415 API records from 15:00–15:04 UTC contained only GETs,
  all HTTP 200, with no POSTs. This is a bounded smoke-traffic sample, not an
  uptime/SLO measurement; production was untouched.
- Staging API HTTP-log follow-up — October 16, approximately 15:10 UTC: the
  latest 501 sanitized records covered 15:02–15:09 UTC; all were GET requests
  returning HTTP 200, with no POSTs or 5xx. This remains a short, bounded sample,
  not uptime/SLO evidence; production was untouched.
- Staging reconciliation follow-up — October 16, checked at approximately
  15:02 UTC: Railway reported the next scheduled report-only run succeeded at
  15:01:48 UTC; its 15:01:46 UTC log said `Inventory and overdue holds
  reconciled.` Railway reported zero warnings, critical issues, recent failures,
  and no pending work. The generic message does not expose persisted finding
  counts. No job was manually triggered; production was untouched.
- Staging reconciliation follow-up — October 16, checked at approximately
  15:30 UTC: Railway reported the next scheduled report-only run succeeded at
  15:30:06 UTC; its 15:30:09 UTC log said `Inventory and overdue holds
  reconciled.` Railway continued to report zero warnings, critical issues, recent
  failures, and no pending work. No job was manually triggered; production was
  untouched.
- Staging persisted reconciliation/attention review — October 16, approximately
  15:35 UTC: in the authenticated staging admin, the read-only “Needs attention”
  page showed 20 persisted reconciliation rows, each `Report · 0 findings`, from
  06:46 through 11:30 EDT (10:46–15:30 UTC). It also showed no unconfirmed order
  or invoice refunds, failed inquiry emails, unsent confirmations, or wedding
  quotes/bouquet proposals awaiting review. No individual order/customer/finding
  records were opened or changed. This confirms durable zero-finding summaries
  over that window and the admin's current attention summary, but not alert
  behavior on a real finding or longer-term monitoring; C3/C4 remain open.
  Production was untouched.
- Staging Railway environment status follow-up — October 16, approximately
  15:06 UTC: all five services reported healthy (three scheduled jobs
  `cronSucceeded`, two services `online`), with zero warnings, critical issues,
  recent failures, and no pending work. This is only an operational snapshot; it
  does not verify durable reconciliation findings or acceptance workflows.
  Production was untouched.
- Staging reconciliation follow-up — October 16, checked at approximately
  15:17 UTC: Railway reported the next scheduled report-only run succeeded at
  15:16:24 UTC; its 15:16:28 UTC log said `Inventory and overdue holds
  reconciled.` Railway reported zero warnings, critical issues, recent failures,
  and no pending work. Persisted finding counts are still awaiting authenticated
  operator review. No job was manually triggered; production was untouched.
- Staging invoice/refund audit follow-up — October 16, checked at approximately
  14:11 UTC: the daily scheduled run completed at 04:18:55 UTC with status
  `succeeded`; its 04:18:57 UTC report-only log said “Invoice refund journals
  agree with supported Stripe payments.” Railway reported zero failures during
  the preceding 24 hours, with no warnings or critical issues. This verifies this
  run's aggregate report only; individual invoice/payment cases, alert behavior on
  a real mismatch, and sustained monitoring remain open. The job was not manually
  triggered and no financial action was taken; production was untouched.
- Staging API HTTP-log spot-check — October 16, approximately 14:13 UTC: the
  latest 501 GET records spanned 04:20–14:13 UTC; 499 returned HTTP 200 and two
  returned 499 with Railway logging that the client closed before a response
  (2 ms and 8 ms). No 5xx responses appeared in this sample. This does not
  identify the client or establish an uptime/SLO result; no request was generated
  for this check and production was untouched.
- Staging API HTTP-log follow-up — October 16, approximately 14:32 UTC: the
  latest 501 GET records covered 14:27–14:32 UTC; all returned HTTP 200, with no
  5xx responses or upstream errors. This brief sample is not an uptime/SLO
  measurement and no request was generated for the check; production was
  untouched.
- Staging empty-contact-form negative check — October 16, approximately 14:35 UTC:
  clicking “Send message” with all contact fields blank left the browser on
  `/contact`. Railway showed only GET requests and no POSTs during the 14:33–14:35
  UTC window (169 GETs, all HTTP 200). No inquiry or email was submitted. This
  confirms only that no backend submission occurred; successful inquiry handling,
  persistence, and delivery remain open. Production was untouched.
- Staging accessibility follow-up — October 16, approximately 14:41 UTC: at a
  390px viewport, the browser panel marked various visible custom inquiry,
  admin-login, wholesale-login, and recovery fields as lacking accessible names.
  Source inspection confirms explicit label associations in
  `frontend/src/components/inquiry-form.tsx`, `backend/templates/admin/login.html`,
  `backend/templates/partials/security_body.html`, and the wholesale sign-in's
  wrapping `<label>` elements. Treat the panel output as an apparent snapshot/tool
  discrepancy, not a confirmed label defect. The login's “Forgot password?” link
  opens `/admin/security/recovery`; its “Send recovery link” control was not
  clicked. No form was submitted. Assistive-technology verification remains open;
  production was untouched.
- Staging retail/mobile UI spot-check — October 16, approximately 14:24 UTC: in
  the authorized browser, `/api/health/` returned `status: ok` and the retail
  catalogue returned the same two listings as before (35 Red Flowers available,
  White Flowers unavailable). At a 390px viewport, `/checkout/retail` showed an
  empty cart, $0 estimated total and a disabled checkout button. No item was added
   or checkout submitted. This confirms only a read-only storefront state and does
   not close deployed purchase/return/webhook checks B3/B5.
- Staging wholesale checkout unauthenticated view — October 16, approximately
  14:49 UTC: at 390px, `/checkout/wholesale` displayed “Wholesale checkout
  requires an approved account” with sign-in/request-access navigation and no
  order controls. No login, account request, or checkout was attempted. This is
  only a public UI guard observation, not a backend authorization or approved
  account checkout test; B5 remains open. Production was untouched.
- Staging unauthenticated admin view — October 16, approximately 14:50 UTC:
  visiting `/admin/orders` without an application session redirected to
  `/admin/login`; no order data was shown. `/admin/security/` displayed a
  sign-in-required message without account details. These are read-only UI guard
  observations only; they do not verify authenticated operator authorization,
  roles, or session security. No credentials or state-changing requests were used;
  production was untouched.
- Local form/layout regression run — October 16, 2026: the isolated Playwright
  suite passed 25/25 checks at 320, 390, 520, 521, 768, 850, 851 and 1440px,
  covering contact, bouquet and wedding forms, computed accessible names,
  descriptions, keyboard navigation and control bounds. Assertions were corrected
  to allow the file input's additional live upload-status description and to
  compare its inner control against the padded preview wrapper. This used a local
  fallback server and stubbed API only; it is not deployed-staging evidence and
  does not close B7. Test-only change is proposed in PR #52.
- Staging R2 media access spot-check — October 16, 2026: Cloudflare listed two
  objects in each staging bucket. A metadata-only inspection showed the public
  objects use `public, max-age=31536000, immutable`; one is a 15,118,440-byte
  JPEG, so the previously noted legacy oversized public object remains an open
  cleanup/acceptance exception. A HEAD request through the active staging media
  custom domain returned HTTP 200 with `image/webp` and the expected immutable
  cache header for a public object. A HEAD request using a private-bucket object
  path through that same public hostname returned HTTP 404, with no redirect or
  content headers, consistent with the private object not being publicly served.
  Object paths and contents were not recorded or downloaded. This spot-check does
  not verify signed private-media authorization, upload persistence, full cache
  policy, or all legacy objects; no data or configuration changed, and production
  was untouched.
- Staging backend-origin guard spot-check — October 16, 2026, approximately
  04:06 UTC: unauthenticated GET requests to the Railway backend's `/admin/login`
  and `/admin/orders` routes returned HTTP 403 `Origin access denied`, with
  `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, and `Referrer-Policy: strict-origin`. The backend
  `/api/health/` route returned HTTP 200 with `status: ok`. This confirms only
  these unauthenticated direct-origin responses; it does not verify authenticated
  same-origin admin routing or session behavior. No credentials were used and no
  state-changing request was sent; production was untouched.
- Trusted proxy CIDR configuration and trusted client-IP attribution remain
  blocked/open.
- Backup alert follow-up — October 15, 2026: invoked the backup dispatch helper
  from the staging backup service environment without running a backup. GitHub
  accepted the dispatch and the expected failed backup-alert workflow emitted
  its generic message. This verifies the dispatch token/API/workflow path, not a
  failure injected into the backup execution itself. Receipt of this specific
  receipt for the earlier dispatch-only notification was not separately
  confirmed. The later controlled backup-handler run's email receipt is confirmed
  above. The owner confirmed escrow retrieval and matching staging values for both
  encryption keys; the restore resources and temporary restore credentials were
  subsequently removed with approval. Reconciliation-alert receipt and
  production backup/restore acceptance remain open.

## Future features

Keep code and isolated regression/security/functional acceptance in the feature phase. Add its deployed provider/configuration/operational cases here with source-phase references, not another scattered “production verification open” status. Feature completion and production acceptance are tracked separately; both are required when applicable to launch.
