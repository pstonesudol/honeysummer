# Release: full staging → approval → production backend

## What is enforced

1. Open a PR; `main` requires the backend and frontend CI checks, an up-to-date
   branch and PR merge. Force pushes/deletion and administrator bypass are off.
   PR approval count is zero so the sole operator can merge their own PR after CI.
2. Merging starts push CI. `.github/workflows/release.yml` runs only after successful
   **push-to-main CI from this repository**, never PR/fork CI. It checks out the
   CI-tested SHA, not the current tip. A stale queued SHA that is no longer the
   main tip fails closed before deployment.
3. Staging archives only the tracked `backend/` from that SHA, uploads it through
   pinned Railway CLI 5.64.2 and waits for the **returned deployment ID** to reach
   success in the correct project/service/environment. Read-only HTTPS health and
   database-backed catalogue checks must pass. A receipt records SHA, archive
   digest, deployment identity and smoke result. No secret or customer data is
   included in the source artifact/receipt.
   The same staging job then installs locked frontend dependencies, builds/deploys
   `honey-summer-staging` from the same checkout, and verifies the custom-domain
   homepage/order page, noindex metadata, API health/DB catalogue proxy and admin
   login form/secure CSRF cookie attributes. It requires anonymous `/admin/` to return its 302 login
   redirect unchanged (detecting a Worker that follows auth redirects internally).
   It saves a redacted `staging-frontend.json` receipt in the release artifact. Any frontend deploy or
   proxy failure blocks the production approval job. This is an HTTP smoke check,
   not authenticated browser, payment/email or private-media acceptance.
4. Production waits for approval in GitHub environment **`production`**. Required
   reviewer: `pstonesudol`. Administrator bypass is disabled. Self-review is
   permitted deliberately: the sole operator may approve a release they merged;
   this is a manual gate, not a two-person control.
5. After approval, production downloads the same staging source archive and
   verifies its hash, commit and successful staging receipt before uploading it.
   It never deploys whatever happens to be latest on main. Production is rebuilt
   from identical source, not promoted as the identical container image.
6. Production waits for its exact deployment to succeed and repeats the read-only
   smoke checks. Failures/timeouts block success; inspect the captured deployment
   ID before rerunning. A successful backend workflow is not public-launch approval.

The whole workflow is serialized, including the approval wait, so another release
cannot overwrite staging while approval is pending. GitHub retains at most one
pending run per concurrency group; newer queued runs may supersede older queued
runs. Not every intermediate merge is guaranteed to deploy. Reject/cancel an old
release to let a newer one advance. Artifacts expire after 14 days; expired
promotion attempts fail closed and require a new staging verification.

## Railway configuration

Both running backend services have their GitHub source disconnected, and a live
API query confirmed **zero deployment triggers** in each environment. The IaC
file declares an empty source with `/backend` as the build root. Actions uploads
a clean archive whose root contains `backend/`; Postgres, variables and domains
are unchanged. Do not reconnect `main` in Railway or reapply an old IaC revision:
that reintroduces simultaneous, ungated provider deployments.

Authorized administrators can still manually deploy through Railway/CLI. Treat
that as audited break-glass, not a normal release path. This workflow does not
prevent someone with administrative access from changing infrastructure policies.

## Activation and evidence

The backend-only release was successfully rehearsed in run
[38109825138](https://github.com/pstonesudol/honeysummer/actions/runs/38109825138)
after user approval. Staging Worker/custom-domain deployment was separately
performed by the user. The frontend staging workflow extension still needs PR
merge and its first Actions rehearsal; it has not been deployed by this edit.

1. **Create two Railway project tokens manually:** open Honey Summer project
   settings → Tokens and create one restricted to `staging`, one to `production`.
    Completed by the user after resolving account verification. The earlier API
    `Not Authorized` error was an account-verification blocker. Don't use a broader
    personal token as a silent fallback.
2. In GitHub repository **Settings → Environments → staging**, add an environment
   secret named `RAILWAY_TOKEN` with the staging token. In **production**, add the
   same secret name with the production token. Do not put either in source, chat,
   workflow YAML or unscoped repository secrets. The environments were created
   with main-only deployment policies; production has the approval rule above.
3. In GitHub **staging**, configure environment secret `CLOUDFLARE_API_TOKEN` and
   variable `CLOUDFLARE_ACCOUNT_ID=1b3166589a8439bce7657a8c372d2791`.
   Both are confirmed present. The token is restricted to the owner's account,
   with Workers Scripts Edit and Account Settings Read. The name "staging" does
   not restrict its provider permissions to one Worker: it can edit other Workers
   in that account. Keep it environment-scoped and audit workflow edits. Do not
   store local OAuth credentials in Actions or silently broaden token permissions.
   The staging custom domain must already be attached; this workflow does not
   change DNS/routes, activate R2 or subscribe to a paid Workers plan.
4. Review and merge the frontend extension PR after CI. In **Actions → Release
   staging and production backend**, inspect the SHA, exact staging deployment
   and smoke receipt. Click **Review deployments → production → Approve and deploy**
   only after the production checklist below. Observe production completion and
   record the run/deployment evidence in `backend/PRODUCTION_READINESS.md`.
5. Rehearse a staging failure/rejected approval and a successful approved release
   before marking the release gate accepted. Unit tests are not that rehearsal.

## Staging Cloudflare Access rollout

User confirmed the custom-domain email-code login works and the alternate
workers.dev URL no longer serves staging after disabling both Worker/preview URLs
in the dashboard. Staging Wrangler now declares `workers_dev: false` to preserve
that choice on redeploy; production settings are unchanged. Direct Railway access
is still an open boundary, not covered by the custom-domain Access application.

After this change merges, run **Actions → Verify staging Access (read-only) →
Run workflow**, selecting **main**. This workflow has no deployment commands or
production job. It checks anonymous and deliberately invalid service-token
requests are denied on the homepage/API health, then runs all existing smoke
probes with the valid staging service token. It prints only a sanitized result.
The expected Access login redirect is pinned to the current Zero Trust team
`cool-thunder-025c`; update the validator if that team domain changes. A successful
run proves the tested custom-domain requests are gated, not all alternate origins
or human-account permission combinations.

1. Zero Trust Free is active in the owner's account. The user saved raw service
   token values as staging environment secrets `CF_ACCESS_CLIENT_ID` and
   `CF_ACCESS_CLIENT_SECRET` (names confirmed, values not read). The token is named
   **Honey Summer staging CI** and has no expiration by user choice. Track manual
   rotation/revocation; never paste values or prefixed headers into source/chat.
2. Merge/deploy the CI preparation before enabling the Access application. The
   frontend smoke client sends the token headers only to the fixed staging origin
   and never follows redirects. Missing/malformed credentials fail before deploy.
   Worker forwarding strips both service headers and the Access JWT before Railway.
   Receipts record only that headers were sent, not credentials or proof of an
   active Access policy. Sending a token to a public site does not verify Access.
3. Create a staging-only self-hosted Access application with an explicit human
   email allowlist and a **Service Auth** policy selecting only this service token.
   Do not use Bypass/Everyone. Confirm allowed addresses with the owner first.
4. Before claiming staging is private, close/protect the alternate workers.dev
   entry point and review direct Railway access. Protecting only the custom domain
   does not protect either alternate origin. Do not blanket-block signed sandbox
   webhooks; define their narrow provider delivery route separately.
5. After activation verify unauthenticated denial, allowed/denied human access,
   service-token CI success and denial without/with an invalid token. Re-run the
   staging smoke step using its environment secrets; do not print token headers.
   This rollout is pending; production policy/domains are unchanged.

## Staging direct-origin gate (pending activation)

This local change adds an opt-in application-layer gate, not a private Railway
network. The Railway domain stays reachable, but all routes/methods require
`X-HoneySummer-Origin-Secret` except exact GET/HEAD `/api/health/` (minimal
liveness) and exact POST `/api/stripe/webhook/` when sandbox `sk_test_` and `whsec_`
credentials are configured. The latter still requires a valid Stripe body
signature in the existing handler; an arbitrary signature header cannot bypass
the gate for other paths. No new Access Bypass policy is created. Sandbox webhook
delivery can use the direct Railway endpoint, outside the custom-domain Access
gate. Provider configuration and real webhook acceptance remain separate tasks.

The gate is disabled by default. When enabled, startup requires DEBUG=false,
PUBLIC_ORIGIN exactly `https://staging.hellohoneysummer.com` and a 43–128 character
URL-safe secret. Production/local startup rejects an enabled staging gate. User
authentication, permissions, CSRF and secure-cookie checks still apply after the
origin gate. Client-supplied origin headers are stripped by the Worker and replaced
only with its staging runtime secret. Server-rendered reads and server actions use
the same runtime binding and reject redirects; staging reads are uncached so the
secret does not enter persistent Next fetch cache. No secret goes in Wrangler vars,
NEXT_PUBLIC variables, build environment/artifacts, receipts or source.

Rollout (requires explicit approval; no provider/Git actions performed by this edit):

1. Generate a random secret privately, e.g. 32 random bytes encoded base64url;
   store it in a password manager. Do not paste it into chat or screenshots.
2. Save the identical value as **STAGING_ORIGIN_SECRET** in GitHub environment
   **staging** (secret), Cloudflare Worker **honey-summer-staging** (runtime secret,
   not plaintext variable), and Railway backend **staging** variables. Do not add
   it to production or local env files. Keep Railway's gate flag false initially.
   Runtime-secret/variable changes may cause provider redeploys: approve/coordinate
   them explicitly and do not change infrastructure during a release verification.
3. Only after approval, publish/review/merge the code. CI staging credential
   preflight now requires this secret before any release deploy. The staging
   backend is still ungated until the flag is enabled; Worker/SSR/CI will already
   send the secret. Wait for successful staging deployment and verify homepage
   content, catalogue and admin login/logout before activation. Production code
   may receive the maintenance change only via the existing manual approval;
   the staging gate and credential must not be configured there.
4. With explicit activation approval, set Railway staging
   **STAGING_ORIGIN_GATE_ENABLED=true**, keeping DEBUG=false and the exact staging
   PUBLIC_ORIGIN. Wait for the deployment; liveness remains available for Railway.
5. Set GitHub staging environment **variable** STAGING_ORIGIN_GATE_ENABLED=true
   to enable the additional direct-origin step in the manual read-only workflow.
   Run **Verify staging Access (read-only)** on main. It must reject missing/wrong
   origin secrets on admin/catalogue/media and accept the authorized catalogue,
   as well as pass the existing custom-domain Access checks. If this step is
   skipped, it is not origin-gate acceptance. Recheck rendered content/forms and
   admin sessions; no payment/email mutations without separate provider approval.
6. Investigate mismatches before retrying. Emergency gate disablement reopens the
   direct origin and needs explicit operator approval; never treat it as accepted
   protection. Rotate matching values in a coordinated maintenance window; there
   is no dual-key grace period. Keep infrastructure variable ownership unmanaged.

## Production approval checklist

- Confirm the SHA/source digest and staging evidence match the intended release.
- Review migrations for backward compatibility and data-loss risk. Production
  backups/isolated restore are still blocked/open: do not approve live-data schema
  changes without a verified recovery plan. Migration rollback is not automatic.
- Confirm independent credentials, intended environment and incident operator.
- Review feature/security acceptance and provider policy changes. Smoke checks
  don't validate payments, refunds, email, private media or all permissions.
- Plan rollback: select the previous verified source revision; evaluate schema
  compatibility before any code redeploy. Do not downgrade migrations blindly.
- No live payment/email fixture, public domain attachment or cutover is authorized
  merely by approving a backend maintenance release.

## Frontend production is not yet in this pipeline

Cloudflare access is resolved. The extension deploys/checks the frontend in
**staging only**; production still promotes **only the backend**. Never interpret a
green production job as a production frontend release or public cutover. A future
approved change must add production frontend credentials/configuration, same-SHA
deployment and proxy checks behind the existing approval. Do not enable independent
production Workers Builds on `main`: that would bypass this sequence. Only after
both sides are integrated and rehearsed can we claim the full-app release chain.

Normal release jobs are serialized, but dashboard/local Wrangler deployments can
still replace staging outside that lock. Do not deploy manually during release
verification/approval. The frontend receipt identifies the CI checkout and probe
results; it is not a runtime cryptographic attestation of the Worker version.
There is no automatic rollback if frontend fails after a successful backend deploy;
review both states and migration compatibility before retrying.

Run local gate tests with `npm run test:release`. The frontend CI job includes them.
Environment reviewer/branch protections/secrets are provider settings, not applied
by repository YAML; preserve and periodically inspect them.
