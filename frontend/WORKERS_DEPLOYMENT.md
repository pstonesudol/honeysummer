# Cloudflare Workers: staging and production

This is local deployment preparation, not deployed acceptance. Cloudflare account
verification/member access is still required. No DNS routes/custom domains are
attached by `wrangler.jsonc`. Do not deploy production or perform public cutover
without separate approval.

| Environment | Worker / self-reference | Backend |
|---|---|---|
| staging | `honey-summer-staging` | `https://honeysummer-staging.up.railway.app` |
| production | `honey-summer` | Must supply the production Railway HTTPS origin |

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

For dashboard GitHub Builds, use repository root `/`, staging build command
`npm run build:staging --workspace frontend` and deploy command
`npm run deploy:staging --workspace frontend` (the latter rebuilds deliberately).
Set `NEXT_PUBLIC_SITE_URL` in the build environment. Production uses the matching
production commands plus its `API_URL`; keep credentials environment-scoped.
Review this setup after account verification; no dashboard build was configured
as part of this local preparation.
