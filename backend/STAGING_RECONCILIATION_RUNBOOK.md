# Staging scheduled reconciliation

## Scope

The scheduled jobs are staging-only, read/report-only audits. They persist
`ReconciliationRun` summaries and exit nonzero when they find discrepancies or
cannot complete. They do not expire Checkout sessions, release inventory,
process/refund payments, send customer mail, or apply reconciliation repairs.
Never add `--apply` to the scheduled command without separate review and approval.

| Railway service | Command | Schedule (UTC) | Scope |
| --- | --- | --- | --- |
| `honeysummer-staging-reconcile` | `python -m app.reconcile` | Every 15 minutes | Inventory/hold audit and recent Checkout/invoice reconciliation |
| `honeysummer-staging-invoice-refund-audit` | `python -m app.invoice_refund_audit` | Daily at 04:15 | Report-only invoice/refund journal comparison |

The commands use the staging backend's `DATABASE_URL` and `STRIPE_SECRET_KEY` by
Railway references. A generic job failure dispatch uses the backup service's
scoped `GITHUB_ALERT_TOKEN` reference; no findings or payment identifiers are
sent to GitHub. The workflow fails intentionally so normal GitHub Actions
notifications can be delivered to configured repository subscribers. Confirm the
owner actually receives a controlled alert before calling alerting accepted.

## Deployment and acceptance

1. Inspect the staging Railway plan: exactly these two services should be added;
   production must remain unchanged.
2. Configure Railway variable references for the two services: `DATABASE_URL`
   and `STRIPE_SECRET_KEY` from `honeysummer`, plus `GITHUB_ALERT_TOKEN`,
   `GITHUB_REPOSITORY=pstonesudol/honeysummer`, and `GITHUB_ALERT_REF=main` from
   the staging backup service/repository. Keep the token scoped to Actions
   workflow dispatch only.
3. Run **Deploy staging reconciliation workers** from `main`. The workflow uploads
   the reviewed backend source to the two staging-only cron services.
4. Verify one report-only execution of each job, persisted run records, and
   expected zero findings or individually reviewed staging findings. Confirm the
   scheduled executions appear at their expected cadence.
5. Cause a controlled, non-data-changing job failure and verify the GitHub alert
   workflow fails and the repository owner receives a notification. Confirm
   ordinary job failure also remains visible in Railway.
6. Record dated evidence in `backend/PRODUCTION_READINESS.md`. Production
   schedules, credentials, and data remain untouched. No production auto-repair
   or automatic financial action is authorized by this staging rehearsal.

The failed GitHub Actions run emits only the job category. Inspect detailed
findings in Railway logs and the persisted run record through approved staging
operator access; don't copy secrets or customer data into GitHub annotations.
