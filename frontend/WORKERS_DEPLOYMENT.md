# Cloudflare Workers: staging and production

Staging is deployed at `https://staging.hellohoneysummer.com` (October 11, 2026).
Cloudflare account membership and local Wrangler authentication are confirmed.
The user attached the staging custom domain in the dashboard; `wrangler.jsonc`
does not yet manage that domain. Read-only storefront/API/admin-entry checks passed;
full security/provider acceptance remains open. Do not deploy production or
perform public cutover without separate approval.

| Environment | Worker / self-reference | Backend |
|---|---|---|
| staging | `honey-summer-staging` | `https://honeysummer-staging.up.railway.app` |
| production | `honey-summer` | Must supply the production Railway HTTPS origin |

## Backend proxy and authentication redirects

`worker.mjs` is the supported custom Worker entry point. It delegates frontend
pages/assets/images to the generated OpenNext handler, but streams `/api`,
`/admin` and `/media` requests directly to the configured backend using
`redirect: "manual"`. Redirect status/Location and all Set-Cookie fields must
reach the browser; following an upstream login redirect inside the Worker loses
the newly issued session cookie and silently returns the login page again.
Absolute backend redirects become same-origin paths; external Stripe redirects
are preserved without being fetched. Cookies, Origin, CSRF fields, backend error
statuses and the 12 MiB streaming upload limit are retained. Auth/admin responses
are no-store. No credentials or customer data are logged.

Next rewrites remain for local Next development; the Worker wrapper handles these
paths before OpenNext's external-rewrite fetch adapter on deployed Workers. The
staging smoke gate additionally requires an anonymous `/admin/` request to return
the backend's 302 to `/admin/login`, rather than a followed 200 login page. This
regression check needs no seeded credentials. Actual login/logout still requires
operator verification after deployment.

The two named Wrangler environments explicitly declare their own non-inherited
service bindings and variables. Database credentials, Stripe/Resend keys and R2
credentials belong on Railway, **never** in frontend public variables.

## Build locally (no Cloudflare account required)

From the repository root:

```bash
npm ci
npm run build:staging --workspace frontend
```

For production, supply its actual backend origin (not staging, not localhost):

```bash
API_URL=https://YOUR-PRODUCTION-BACKEND.up.railway.app npm run build:production --workspace frontend
```

Bare `deploy`, `preview` and `upload` commands intentionally fail until an
environment is selected. Use the named commands below instead. The helper
validates HTTPS origins, rebuilds for every operation, and uses one generated,
git-ignored config for both build and deploy so API rewrites and runtime variables
match. It removes that file when finished. It prevents concurrent environment
builds in a single checkout because `.next` and `.open-next` are shared outputs.
If an interrupted process leaves `.worker-build-lock`, confirm no build is
running before removing that specific empty directory.

The staging site origin defaults to the **intended**, not yet attached,
`https://staging.hellohoneysummer.com`. Before using a generated Workers URL,
override it explicitly on every build/deploy command:

```bash
NEXT_PUBLIC_SITE_URL=https://honey-summer-staging.ACCOUNT.workers.dev npm run build:staging --workspace frontend
```

Staging builds include noindex/nofollow metadata. This is not authentication;
restrict staging access and use synthetic data, not real customer records.

## After Cloudflare access is available

1. Authenticate Wrangler with your own member account; verify the selected
   account has permission for Workers. Do not deploy to a temporary account.
2. Verify `npm run lint --workspace frontend`, `npm run test --workspace frontend`
   and the OpenNext staging build before release.
3. Deploy staging only, using the intended final staging URL:

   ```bash
   NEXT_PUBLIC_SITE_URL=https://honey-summer-staging.ACCOUNT.workers.dev npm run deploy:staging --workspace frontend
   ```

   Alternatively use `staging.hellohoneysummer.com` after an approved staging
   custom-domain setup. Account names/URLs above are examples, not real values.
4. Set staging Railway `PUBLIC_ORIGIN` to the **exact same frontend origin**.
   Set both channel success/cancel URLs for that frontend as documented in
   `backend/.env.example`; do not leave localhost return URLs.
5. Verify HTTPS `/api/health/`, `/admin/`, public `/media/`, protected private
   photo routing, cookies, Origin/CSRF, uploads and server-side wholesale checks
   through the Worker. A direct Railway health response does not prove proxy
   acceptance. Record evidence in `backend/PRODUCTION_READINESS.md`.
6. Configure provider-backed staging checks before production approval. Production
   uses `API_URL=<production-origin> npm run deploy:production --workspace frontend`
   and `NEXT_PUBLIC_SITE_URL=https://hellohoneysummer.com`; do not attach the public
   domain until Phase 13 authorizes cutover. A workers.dev deployment is still
   public, and requires explicit production deployment approval.

`preview:staging`/`preview:production` rebuild then run the local Workers preview;
they point to the chosen hosted backend and mutations can affect it. `upload:*`
rebuilds and uploads a version to Cloudflare (not a read-only local action).

The release approval chain is in `RELEASE_RUNBOOK.md`. The workflow extension
deploys staging from the CI-tested SHA after successful backend staging, then runs
read-only storefront/API/admin-entry smoke checks before production approval can
proceed. Its first CI deployment is still to be rehearsed. GitHub staging holds
`CLOUDFLARE_API_TOKEN` as a secret and `CLOUDFLARE_ACCOUNT_ID` as a variable; local
OAuth does not authenticate Actions. The custom domain remains dashboard-managed.
Production is still **backend only**, with no production Worker deploy enabled.
Do not enable independent production GitHub Builds, which would bypass approval.
A future production frontend integration must use matching commands and its own
`API_URL` **behind the same release approval gate**, with scoped credentials.
