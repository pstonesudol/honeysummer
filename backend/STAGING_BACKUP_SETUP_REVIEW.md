# Staging backup setup — review before provisioning

**Status: proposed only. No Railway/R2 resources, variables, credentials,
schedules, lifecycle rules, or deployments have been created or changed.** Review
this plan before any provider action. Production is explicitly excluded.

## Proposed design

| Item | Proposed value |
| --- | --- |
| Environment | Railway `staging` only |
| Railway service | `honeysummer-staging-backup`, one short-lived scheduled service |
| Schedule | Daily, 03:30 UTC (`30 3 * * *`) |
| Backup retention | 14 days, R2 lifecycle rule on `snapshots/` |
| R2 destination | New private bucket `honeysummer-staging-backups`, no public/custom domain |
| Backup contents | One PostgreSQL custom dump plus every staging public/private R2 object and metadata |
| Encryption | Client-side AES-256-GCM with a dedicated key; encrypted manifest uploaded last |
| Failure alert | Dispatch `.github/workflows/staging-backup-alert.yml`; failed Actions run notifies subscribed GitHub users |
| Railway plan | No Pro upgrade expected for the cron service; compute and storage/request usage may still cost money |

The cadence/retention are proposed defaults, not provider configuration. Cost
cannot be estimated accurately until staging database and media sizes are
measured. Fourteen full snapshots require roughly `14 × (database dump + media)`
storage before lifecycle expiry; existing R2 use consumes part of any free
allowance. Railway compute depends on backup runtime.

## Proposed staging service configuration

`.railway/railway.ts` now describes a backup service only when the selected
environment is `staging`. It has no public domain or volume, uses the staging
Postgres private network, builds `backup.Dockerfile`, runs
`uv run --no-sync python -m app.backup`, and is configured for `NEVER` restart
plus the proposed daily schedule. Variables remain unmanaged; no secrets are in
IaC. Do not apply until the plan is approved and the restore/recovery gaps below
are closed.

Read-only Railway plans were inspected after adding the configuration:

- **Staging:** 1 service to add, 2 service-field changes, 0 destroys. The add is
  `honeysummer-staging-backup`. The other changes are on existing `honeysummer`:
  source type `github → empty`, and restart policy `null → ON_FAILURE`.
- **Production:** 0 services to add, 2 service-field changes, 0 destroys. The
  same two existing-backend changes appear; **the backup service is absent**.
- **Nothing was applied.** Do not accept either whole-project plan as-is. Review
  the existing backend drift independently so backup provisioning cannot bundle
  unrelated changes. Re-run fresh staging and production plans immediately before
  any future apply.

## Secret and permission inventory

Set these only on the proposed **staging backup service**, using Railway variable
references where applicable. Never copy production values.

| Variable | Source/permission intent | Secret? |
| --- | --- | --- |
| `DATABASE_URL` | Reference staging `Postgres.DATABASE_URL`; private-network access only | Yes |
| `BACKUP_ENCRYPTION_KEY` | New random 32-byte AES key, independent of app key; escrow separately | Yes |
| `R2_ENDPOINT_URL` | Existing staging account endpoint | No |
| `R2_BUCKET` | Existing staging public media bucket identifier | No |
| `R2_PRIVATE_BUCKET` | Existing staging private media bucket identifier | No |
| `BACKUP_SOURCE_R2_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | Separate read/list-only credential for those two staging media buckets | Yes |
| `BACKUP_R2_BUCKET` | New destination bucket identifier | No |
| `BACKUP_R2_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | Separate write credential scoped to destination bucket | Yes |
| `GITHUB_ALERT_TOKEN` | Fine-grained token limited to this repo, Actions: write only | Yes |
| `GITHUB_REPOSITORY` / `GITHUB_ALERT_REF` | `pstonesudol/honeysummer` / `main` | No |

The backup writer does not need permission to delete/list destination backups.
Restore should use a separately provisioned, short-lived credential with read
access to the backup bucket and write access only to disposable restore targets.
Do not put secrets in chat, docs, logs, source control, or the status register.

## Recovery requirements before enablement

The backup writer and encryption tests now cover streaming database encryption,
copying public/private R2 objects, per-object hashes, manifest-last completion,
and a generic GitHub failure dispatch. **This is still not an accepted recovery
system.** Before enabling the schedule, complete and review:

1. An executable download/manifest verification/decrypt/`pg_restore` procedure
   that refuses production targets and does not drop existing data.
2. A separate isolated Postgres target and isolated public/private restore buckets
   with no customer-facing routes; rehearse there, never over active staging.
3. Secure independent escrow and retrieval test for both `BACKUP_ENCRYPTION_KEY`
   and the application's `SECURITY_ENCRYPTION_KEY`. Do not send either value.
4. Cross-check media byte counts/hashes and restore content type/cache metadata;
   verify private restored objects remain private and public restored objects are
   not routed until explicitly approved.
5. Alert test: trigger a synthetic failure, verify the GitHub Actions run fails,
   and confirm an actual notification reaches the owner. A hard kill, startup
   failure, missing token or GitHub API outage can bypass the direct dispatch.
6. Verify the destination is private, lifecycle expiry is correct, credentials are
   bucket-scoped, and a successful scheduled run exits cleanly. Keep a manifest as
   the required completion marker; partial objects without one are not backups.

## Provisioning sequence after review

1. Resolve the two unrelated Railway backend drift items and get a clean,
   reviewed staging plan that adds only the staging backup service. Verify the
   production plan adds no backup service.
2. Confirm expected R2/Railway usage charges from actual dataset size and account
   usage; create the private staging bucket and lifecycle rule only after approval.
3. Create scoped source/destination R2 credentials, escrow the dedicated backup
   key outside Railway, then add secrets to the staging backup service.
4. Add the GitHub alert token as a Railway staging secret; do not expose it in
   chat. Confirm repository Actions notifications are enabled for the owner.
5. Apply only the approved staging resource plan. Inspect the resulting service
   and secret **names only**, run one controlled staging backup, then test failure
   alert and isolated database/media/key restoration.
6. Record evidence in `backend/PRODUCTION_READINESS.md`. Production remains a
   separate future approval and policy; nothing here authorizes production setup.
