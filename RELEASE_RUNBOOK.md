# Backend release: main → staging → approval → production

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

## Activation still required

The workflow/scripts are prepared locally, but no end-to-end release is claimed.

1. **Create two Railway project tokens manually:** open Honey Summer project
   settings → Tokens and create one restricted to `staging`, one to `production`.
   The authenticated Railway API returned `Not Authorized` for token creation,
   so no tokens were stored by the agent. If the dashboard also denies creation,
   resolve the account/permission restriction; don't use a broader personal token
   as a silent fallback.
2. In GitHub repository **Settings → Environments → staging**, add an environment
   secret named `RAILWAY_TOKEN` with the staging token. In **production**, add the
   same secret name with the production token. Do not put either in source, chat,
   workflow YAML or unscoped repository secrets. The environments were created
   with main-only deployment policies; production has the approval rule above.
3. Review/commit these files on a branch and open a PR. After CI, merge to main.
   No commit, push or PR was performed automatically. While this is pending,
   existing apps stay online but new merges no longer trigger Railway directly.
4. In **Actions → Release backend**, inspect the SHA, exact staging deployment
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

## Frontend is not yet in this pipeline

Cloudflare account verification/member access is blocked. The current workflow is
explicitly **backend only**. After access is resolved, add frontend staging deploy
and proxy/account smoke checks to the staging job, then deploy the same frontend
SHA behind the same production approval. Do not enable independent production
Workers Builds on `main`: that would bypass this sequence. Only after both sides
are integrated and rehearsed can we claim the full-app release chain.

Run local gate tests with `npm run test:release`. The frontend CI job includes them.
Environment reviewer/branch protections/secrets are provider settings, not applied
by repository YAML; preserve and periodically inspect them.
