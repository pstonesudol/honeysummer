# Staging backup and recovery

## Scope and status

This runbook describes the selected **logical backup** approach. Railway's
scheduled-service (cron) feature is expected to work without upgrading the
workspace; scheduled compute and R2 storage/requests can still incur usage costs.
The staging cron service has been created, but it is offline with no deployment;
no backup has run. No R2 bucket, credential, encryption key, lifecycle rule, or
production configuration has been created or changed.

The backup command is `python -m app.backup`. It streams a PostgreSQL custom dump
through AES-256-GCM encryption and copies every object in the staging public and
private R2 buckets through the same encryption into a separate private backup
bucket. An encrypted manifest is uploaded last; only a snapshot with that
manifest is considered complete. `backend/backup.Dockerfile` provides PostgreSQL
18's client tools, matching the current staging database major version. The
backup key is not the application's `SECURITY_ENCRYPTION_KEY`.

**Current staging state:** `honeysummer-staging-backup` is provisioned in Railway
staging with a 03:30 UTC daily cron schedule and no public domain or volume. It has
no deployment and is offline. Its non-secret settings and staging Postgres/media
references are configured, but required encryption/R2/GitHub secrets are not.
The dedicated backup bucket and its 14-day lifecycle policy have not been
created. GitHub Actions is the selected failure-alert destination. The backup
bucket must be private and separate from both media buckets.

The job does not automatically escrow the backup key or application encryption
key. `python -m app.restore_backup <manifest-key>` is a guarded restore tool; it
requires a separately isolated `staging-restore` PostgreSQL target and empty,
separate public/private restore buckets, then demands an exact typed target
confirmation. The operator must store both keys independently in approved secure
escrow. An isolated restore rehearsal remains required before G2 can pass.

## Proposed staging configuration

- Service: `honeysummer-staging-backup`; no public domain or volume.
- Source: `/backend`, Dockerfile `backup.Dockerfile`, command
  `uv run --no-sync python -m app.backup`.
- Database: staging-only `DATABASE_URL` reference to staging Postgres over
  Railway's private network; never a copied production URL.
- Schedule: configured as `30 3 * * *` UTC; restart policy `NEVER`. The service
  has no deployment yet, so it has not run.
- Storage: private bucket `honeysummer-staging-backups` is planned, not yet
  created; 14-day lifecycle expiry is also pending. No public custom domain. The
  manifest is the completion marker; orphaned partial snapshots are harmless and
  lifecycle-expired.
- Environment guard: `.railway/railway.ts` includes the service only when the
  selected environment is `staging`; production plans must not contain it.
- Alert: caught backup errors dispatch the deliberately failing
  `.github/workflows/staging-backup-alert.yml` workflow. GitHub only notifies
  users who have appropriate Actions/repository notifications enabled.
- Ad-hoc run: after the scheduled service is provisioned, the manual GitHub
  workflow **Run staging backup now** on `main` uploads the reviewed `backend/`
  image to that service, waits for the exact deployment to succeed in the staging
  environment, then calls `railway cron run`. It uses the protected GitHub
  `staging` environment and requires its `RAILWAY_TOKEN` secret plus
  `RAILWAY_PROJECT_ID` variable. It triggers the same backup runner immediately;
  it does not create a separate backup implementation or allow a production
  target.

### Credentials and permissions

| Name | Purpose | Minimum intended access |
| --- | --- | --- |
| `DATABASE_URL` | Staging database source | Staging Postgres only, private network |
| `BACKUP_ENCRYPTION_KEY` | Client-side encryption/decryption | Secret; independent recovery copy in owner-controlled escrow |
| `R2_ENDPOINT_URL` | S3-compatible endpoint | Staging account endpoint |
| `R2_BUCKET`, `R2_PRIVATE_BUCKET` | Public and private media source names | Staging buckets only |
| `BACKUP_SOURCE_R2_ACCESS_KEY_ID`, `BACKUP_SOURCE_R2_SECRET_ACCESS_KEY` | Read media objects | List/read only on the two staging media buckets |
| `BACKUP_R2_BUCKET` | Backup destination name | Dedicated private bucket only |
| `BACKUP_R2_ACCESS_KEY_ID`, `BACKUP_R2_SECRET_ACCESS_KEY` | Write snapshots | Write-only to backup bucket where supported; no delete/list needed by the writer |
| `GITHUB_ALERT_TOKEN` | Dispatch alert workflow | Fine-grained token limited to this repo, Actions: write |
| `GITHUB_REPOSITORY`, `GITHUB_ALERT_REF` | Alert target | Nonsecret; `pstonesudol/honeysummer`, `main` |

Do not reuse the backend's R2 keys for the backup job. Restore access should be a
separate, short-lived credential that can read the backup bucket and write only to
temporary restore buckets. No secret values belong in Git, issue comments, this
runbook, or chat.

## Alert limitations

The job exits nonzero on database dump, media list/read, encryption, or upload
errors. For caught errors, it sends only a generic failure signal to GitHub; it
does not send exception text, object names, customer data, or credentials. A hard
kill, startup failure, missing/invalid token, or GitHub API outage can prevent the
dispatch. Before calling alerting accepted, test a simulated failure and confirm
receipt through the owner's GitHub notification settings. Railway's own failure
history is a secondary diagnostic, not proof of notification.

## Recovery procedure (tool implemented; rehearsal not yet completed)

1. Select a snapshot by its encrypted manifest key. Configure restore-only
   credentials and target settings as described below, then run
   `uv run --no-sync python -m app.restore_backup '<manifest-key>'` from a
   restricted operator environment.
2. Confirm the displayed exact target phrase (`RESTORE staging-restore
   <host>/<database>`) before continuing. The tool requires an empty isolated
   PostgreSQL database and empty separate media buckets, checks object ciphertext
   hashes, authenticates the manifest and all files, and verifies media plaintext
   lengths and hashes before writing anything.
3. The tool runs `pg_restore --list`, then `pg_restore --exit-on-error --no-owner
   --no-acl`; it restores public/private objects into separate isolated buckets
   while preserving content type, cache control and metadata. The private bucket
   must have no public domain. Never restore into working staging, production,
   or source buckets.
4. Verify schema/revision state, representative synthetic records and app reads
   using a disposable app configuration. Verify escrow/retrieval of both the
   backup key and application encryption key independently.
5. Securely remove plaintext and disposable resources under an approved cleanup
   procedure. Record snapshot ID, target, checks, result, operator and cleanup;
   never record credentials, key material or private-photo contents.

Restore-only environment variables:

- `RESTORE_TARGET_ENVIRONMENT=staging-restore`
- `RESTORE_DATABASE_URL`: isolated Postgres URL whose host identifies the restore
  target (contains `restore`, not `production`).
- `RESTORE_PUBLIC_BUCKET`, `RESTORE_PRIVATE_BUCKET`: distinct empty buckets whose
  names identify them as restore targets and differ from source/backup buckets.
- `RESTORE_BACKUP_R2_ACCESS_KEY_ID`, `RESTORE_BACKUP_R2_SECRET_ACCESS_KEY`:
  read-only access to the backup bucket.
- `RESTORE_R2_ACCESS_KEY_ID`, `RESTORE_R2_SECRET_ACCESS_KEY`: write-only access
  to the two isolated restore buckets; never source or production buckets.
- Existing `R2_ENDPOINT_URL`, `BACKUP_R2_BUCKET`, and escrowed
  `BACKUP_ENCRYPTION_KEY` are also required.

This rehearsal requires isolated Postgres and public/private buckets, and explicit
cleanup approval. G2 remains open until database, media, key recovery and failure
alerts are rehearsed.
Production needs its own separately approved policy and recovery evidence; staging
does not prove production recoverability.
