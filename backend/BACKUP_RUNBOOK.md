# Staging backup and recovery

## Scope and status

This runbook describes the selected **logical backup** approach. Railway's
scheduled-service (cron) feature is expected to work without upgrading the
workspace; scheduled compute and R2 storage/requests can still incur usage costs.
No Railway or R2 resources, credentials, schedules, billing settings, or
production configuration have been changed.

The backup command is `python -m app.backup`. It streams a PostgreSQL custom dump
through AES-256-GCM encryption and copies every object in the staging public and
private R2 buckets through the same encryption into a separate private backup
bucket. An encrypted manifest is uploaded last; only a snapshot with that
manifest is considered complete. `backend/backup.Dockerfile` provides PostgreSQL
18's client tools, matching the current staging database major version. The
backup key is not the application's `SECURITY_ENCRYPTION_KEY`.

**Proposed, not applied:** a staging-only Railway service in `.railway/railway.ts`,
daily at 03:30 UTC, with 14-day R2 lifecycle retention. GitHub Actions is the
selected failure-alert destination. No staging bucket/service, credentials, key,
lifecycle rule, schedule, alert, or restore has been configured. The backup bucket
must be dedicated and private, separate from both media buckets.

The job does not automatically escrow the backup key or application encryption
key, and there is not yet a restore command. The operator must store both keys
independently in approved secure escrow. Restore tooling and an isolated restore
rehearsal remain required before G2 can pass.

## Proposed staging configuration

- Service: `honeysummer-staging-backup`; no public domain or volume.
- Source: `/backend`, Dockerfile `backup.Dockerfile`, command
  `uv run --no-sync python -m app.backup`.
- Database: staging-only `DATABASE_URL` reference to staging Postgres over
  Railway's private network; never a copied production URL.
- Schedule: `30 3 * * *` UTC; restart policy `NEVER` so one failure produces one
  recorded failure and the next attempt is the following day.
- Storage: proposed private bucket `honeysummer-staging-backups`, lifecycle
  expiry after 14 days. No public custom domain. The manifest is the completion
  marker; orphaned partial snapshots are harmless and lifecycle-expired.
- Environment guard: `.railway/railway.ts` includes the service only when the
  selected environment is `staging`; production plans must not contain it.
- Alert: caught backup errors dispatch the deliberately failing
  `.github/workflows/staging-backup-alert.yml` workflow. GitHub only notifies
  users who have appropriate Actions/repository notifications enabled.

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

## Recovery procedure (not yet automated)

1. Select a snapshot by its encrypted manifest key. Verify each listed backup
   object exists and its ciphertext checksum matches its stored metadata.
2. Download into a restricted, disposable workspace outside the repository.
   Decrypt/authenticate the manifest first; missing or invalid manifest means the
   snapshot is incomplete.
3. Decrypt and authenticate the database archive and media objects. Verify the
   restored media sizes and SHA-256 hashes against the manifest. Never use
   unauthenticated/partial plaintext.
4. Restore with `pg_restore --exit-on-error --no-owner --no-acl` into a new,
   isolated, empty PostgreSQL database. Never point restore at working staging or
   production.
5. Restore public/private objects into separate isolated buckets. The private
   bucket must have no public domain; keep the restored public bucket unrouted
   until keys, bytes, content types, caching and access boundaries are verified.
   Never overwrite the source buckets during rehearsal.
6. Verify schema/revision state, representative synthetic records and application
   reads with a disposable app configuration. Verify escrow/retrieval of both
   the backup key and application encryption key independently.
7. Securely remove plaintext and disposable resources under an approved cleanup
   procedure. Record snapshot ID, target, checks, result, operator and cleanup;
   never record credentials, key material or private-photo contents.

This rehearsal requires an executable restore tool or reviewed manual commands,
isolated Postgres and public/private buckets, and explicit cleanup approval. G2
remains open until database, media, key recovery and failure alerts are rehearsed.
Production needs its own separately approved policy and recovery evidence; staging
does not prove production recoverability.
