# Staging backup and restore setup — current status

**Staging backup operational; restore rehearsal pending.** The staging-only
Railway cron service, daily schedule, private backup bucket, and 14-day snapshot
retention are configured. Two encrypted snapshots completed successfully. The
isolated restore Postgres service and two empty restore buckets are provisioned;
restore-only credentials, alert-path verification, escrow retrieval, and restore
rehearsal remain outstanding. Production is untouched.

## Proposed design

| Item | Proposed value |
| --- | --- |
| Environment | Railway `staging` only |
| Railway service | `honeysummer-staging-backup`, one short-lived scheduled service |
| Schedule | Daily, 03:30 UTC (`30 3 * * *`) |
| Backup retention | 14 days, R2 lifecycle rule on `snapshots/` |
| R2 destination | Private bucket `honeysummer-staging-backups`, no `r2.dev` or custom domain |
| Backup contents | One PostgreSQL custom dump plus every staging public/private R2 object and metadata |
| Encryption | Client-side AES-256-GCM with a dedicated key; encrypted manifest uploaded last |
| Failure alert | Dispatch `.github/workflows/staging-backup-alert.yml`; failed Actions run notifies subscribed GitHub users |
| Ad-hoc trigger | `.github/workflows/staging-backup-manual.yml` manually triggers the staging Railway cron run from `main` |
| Railway plan | No Pro upgrade expected for the cron service; compute and storage/request usage may still cost money |

The cadence/retention are proposed defaults, not provider configuration. Cost
cannot be estimated accurately until staging database and media sizes are
measured. Fourteen full snapshots require roughly `14 × (database dump + media)`
storage before lifecycle expiry; existing R2 use consumes part of any free
allowance. Railway compute depends on backup runtime.

## Staging service configuration

`.railway/railway.ts` describes a backup service only when the selected
environment is `staging`. It has no public domain or volume, uses the staging
Postgres private network, builds `backup.Dockerfile`, runs
`uv run --no-sync python -m app.backup`, and is configured for `NEVER` restart
plus the daily schedule. It has completed two manual staging runs. Secret values
remain outside IaC and are not read back. Do not consider G2 complete until the
recovery prerequisites below are met.

Fresh read-only Railway plans were inspected after aligning the existing backend
source declaration with its current GitHub type and leaving its default restart
policy unmanaged:

- **Before creation:** staging plan was exactly 1 service add, 0 changes, 0
  destroys; production plan was up to date. The staging service was created from
  that plan; no production resource was changed.
- **Restore resources:** `staging-restore-postgres` with an attached 5 GB volume
  is online in Railway staging. Two separate empty R2 buckets are provisioned
  for public/private restore data; both have `r2.dev` disabled and no custom
  domains.
- **Current production plan:** up to date; no backup or restore service.
- **Current staging plan:** no resources to add/destroy; it reports safe config
  normalization diffs only. Review the plan before any future apply and never
  apply this setup to production.

## Secret and permission inventory

Set these only on the **staging backup service**, using Railway variable
references where applicable. Never copy production values.

| Variable | Source/permission intent | Secret? |
| --- | --- | --- |
| `DATABASE_URL` | Reference staging `Postgres.DATABASE_URL`; private-network access only | Yes |
| `BACKUP_ENCRYPTION_KEY` | New random 32-byte AES key, independent of app key; escrow separately | Yes |
| `R2_ENDPOINT_URL` | Existing staging account endpoint | No |
| `R2_BUCKET` | Existing staging public media bucket identifier | No |
| `R2_PRIVATE_BUCKET` | Existing staging private media bucket identifier | No |
| `BACKUP_SOURCE_R2_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | Separate read/list-only credential for those two staging media buckets | Yes |
| `BACKUP_R2_BUCKET` | Created destination bucket `honeysummer-staging-backups` | No |
| `BACKUP_R2_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | Separate write credential scoped to destination bucket | Yes |
| `GITHUB_ALERT_TOKEN` | Fine-grained token limited to this repo, Actions: write only | Yes |
| `GITHUB_REPOSITORY` / `GITHUB_ALERT_REF` | `pstonesudol/honeysummer` / `main` | No |

The backup writer does not need permission to delete/list destination backups.
Restore should use a separately provisioned, short-lived credential with read
access to the backup bucket and write access only to disposable restore targets.
Do not put secrets in chat, docs, logs, source control, or the status register.

## Recovery acceptance still required

The backup writer and tests cover streaming database encryption, copying
public/private R2 objects, per-object hashes, manifest-last completion, a generic
GitHub failure dispatch, and an isolated-target restore command. The manual
GitHub workflow can trigger the proposed Railway cron service once provisioned.
**This is still not an accepted recovery system.** Complete and review:

1. Review the restore command's explicit `staging-restore` target guard, exact
   typed confirmation, empty-database and empty-bucket checks, and no-overwrite
   behavior. It refuses production and non-restore targets and does not drop data.
2. Configure short-lived restore credentials: read-only on the backup bucket and
   write-only on the two isolated restore buckets. Rehearse there, never over
   active staging.
3. Secure independent escrow and retrieval test for both `BACKUP_ENCRYPTION_KEY`
   and the application's `SECURITY_ENCRYPTION_KEY`. Do not send either value.
4. Cross-check media byte counts/hashes and restore content type/cache metadata;
   verify private restored objects remain private and public restored objects are
   not routed until explicitly approved.
5. Manual trigger test: run **Run staging backup now** from `main` in GitHub
   Actions and verify the cron run plus completed manifest. Two staging runs
   have succeeded; retain the evidence for the rehearsal record.
6. Alert test: trigger a synthetic failure, verify the GitHub Actions run fails,
   and confirm an actual notification reaches the owner. A hard kill, startup
   failure, missing token or GitHub API outage can bypass the direct dispatch.
7. Verify the destination is private, lifecycle expiry is correct, credentials are
   bucket-scoped, and a successful scheduled run exits cleanly. Keep a manifest as
   the required completion marker; partial objects without one are not backups.

## Remaining sequence

1. Add restore-only credentials directly to Railway service
   `honeysummer-staging-restore-runner`: read/list only on
   `honeysummer-staging-backups`, and object read/write only on the two restore
   buckets. Do not reuse the backup writer or application media credentials.
2. Confirm the backup encryption key and application `SECURITY_ENCRYPTION_KEY`
   each have independent secure escrow copies and that recovery operators can
   retrieve them. Never share key material.
3. Merge and validate the manual restore workflow; dispatch it with the completed
   manifest key and exact `RESTORE staging-restore <host>/<database>` confirmation.
   Verify schema/revision state, representative records, four media objects,
   hashes, metadata, and private/public access behavior.
4. Run a controlled synthetic failure and confirm the backup runner dispatches
   the alert workflow and that the owner actually receives the notification.
5. After recording evidence and confirming the restore, clean up the temporary
   restore runner, database/volume, and restore buckets under the approved cleanup
   scope. Keep the encrypted backup bucket and daily schedule.
6. Record dated evidence in `backend/PRODUCTION_READINESS.md`. Production remains
   a separate future approval and policy; nothing here authorizes production setup.
