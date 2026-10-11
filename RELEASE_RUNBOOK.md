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
