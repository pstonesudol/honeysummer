# Staging backup and restore setup — historical review

**Staging restore completed and cleaned up October 16, 2026.** The staging-only
Railway cron service, daily schedule, private backup bucket, and 14-day snapshot
retention remain configured. Encrypted backups and the isolated database/media
restore were verified; the owner retrieved both encryption-key escrow copies and
confirmed they matched the staging values. After explicit approval, the restore
runner, Postgres/volume, restore buckets, and their contents were removed. The
backup bucket and routine staging services remain. Reconciliation-alert inbox
receipt, production recovery acceptance, and other launch checks remain open.
See `PRODUCTION_READINESS.md` for current acceptance status. Production was
untouched.

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
  remain outside IaC and are not read back. The staging rehearsal is recorded
  below; production G2 acceptance remains open.

Provisioning snapshot from before the restore cleanup: fresh read-only Railway
plans were inspected after aligning the existing backend source declaration with
its current GitHub type and leaving its default restart policy unmanaged:

- **Before creation:** staging plan was exactly 1 service add, 0 changes, 0
  destroys; production plan was up to date. The staging service was created from
  that plan; no production resource was changed.
- **Restore resources:** `staging-restore-postgres` with an attached 5 GB volume
  and two separate public/private R2 buckets were provisioned for the rehearsal;
  both buckets had `r2.dev` disabled and no custom domains. All were subsequently
  deleted under owner-approved cleanup.
- **Production plan at that time:** up to date; no backup or restore service.
- **Staging plan at that time:** no resources to add/destroy; it reported safe config
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

## Recovery acceptance outcome

The backup writer and tests cover streaming database encryption, copying
public/private R2 objects, per-object hashes, manifest-last completion, a generic
GitHub failure dispatch, and an isolated-target restore command. The manual
GitHub workflow can trigger the proposed Railway cron service once provisioned.
The planned staging recovery rehearsal was completed October 16, 2026. The
following records the outcome and remaining limitations:

1. The restore command's explicit `staging-restore` target guard, exact
   typed confirmation, empty-database and empty-bucket checks, and no-overwrite
   behavior. It refuses production and non-restore targets and does not drop data.
2. Short-lived credentials scoped to the backup and isolated restore targets were
   used for the rehearsal and removed with the restore resources during approved
   cleanup.
3. Independent escrow retrieval was confirmed for both `BACKUP_ENCRYPTION_KEY`
   and the application's `SECURITY_ENCRYPTION_KEY`. Do not send either value.
4. Media hashes and plaintext lengths were checked; restored objects decoded, and
   private reads used the application's private-media function. The private
   restore bucket had public access disabled.
5. Manual trigger test: **Run staging backup now** from `main` in GitHub
   Actions and verify the cron run plus completed manifest. Two staging runs
   have succeeded; retain the evidence for the rehearsal record.
6. A controlled backup-handler failure dispatched the GitHub alert and the owner
   confirmed email receipt. A hard kill, startup failure, missing token or GitHub
   API outage can bypass the direct dispatch.
7. The destination is private, lifecycle expiry is configured, credentials are
   bucket-scoped, and a successful scheduled run exits cleanly. Keep a manifest as
   the required completion marker; partial objects without one are not backups.

## Future restore procedure

For a future rehearsal, provision fresh isolated targets and short-lived,
restore-only credentials. Confirm independent escrow retrieval of both keys
without sharing key material; run the guarded restore and verify the database,
media and access behavior; record dated evidence; then clean up under explicit
approval. Keep the encrypted backup bucket and daily schedule. Production recovery
requires a separate policy and approval; this staging exercise does not authorize
production setup.
