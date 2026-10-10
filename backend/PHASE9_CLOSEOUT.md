# Phase 9 closeout — October 10, 2026

**Status: implementation complete; owner acceptance assumed per user instruction.** This is not a production launch sign-off.

## Final delivered slice

- Gallery-backed photo selection for all six page heroes and three home cards, including alt text, focal points, original-image fallback and admin previews.
- Desktop sidebar, mobile menu, skip link, focus treatment, readable financial/status text and horizontally scrollable tables.
- Read-only account-settings foundation and paginated/filterable administrative POST-outcome history. No secrets/form values are logged. Account changes, permissions, revocable sessions and security-event auditing remain Phase 11.
- Address-verified `.eml` imports with original message date and duplicate protection. Plain text only, 1 MB file / 4,000-character text limits; attachments ignored. This is explicit file import, not automatic mailbox synchronization.
- Printable daily preparation quantities and order breakdowns, restricted to paid, incomplete, date-scheduled work; printing never moves stock.
- Verified external Stripe invoice refund import, including metadata-matched recovery of an uncertain request, plus report-only original-charge/refund auditing. Neither reconciliation path issues money or restocks goods.
- Revised post-refund wedding agreements and manual revised-balance collection. Original payment plans cannot resume after a recorded refund, even following invoice recovery.
- Dry-run-first local inquiry-photo migration, verified private copy before database update/public removal, and rejection of private storage inside the public media tree.
- Reconciliation findings persist on the same event loop as their audit (avoids asyncpg cross-loop failures).

Migration `f41c98d071a2` adds the administrative outcome log and correspondence import identity; applied locally. Earlier wedding-amendment migration `83e31c55ab49` is also applied.

## Stripe test-mode evidence

`uv run python -m app.verify_phase9 --apply` creates only new synthetic customers/quotes and rejects non-`sk_test_` keys. It never touches existing quotes. Test quotes #13/#14 yielded orders #23/#24 after final revised payments, not deposits. Refund import replay made no duplicate journal entry. Quote #15 exercised invoice void/revision and matching unknown-ID attachment; unpaid test invoices were voided. Synthetic paid records remain in the development database and are not real shop revenue.

`uv run python -m app.invoice_refund_audit` subsequently reported that journals agree with supported Stripe payments and saved its report to Needs attention. A discrepancy returns a nonzero exit for monitoring and requires explicit verified refund-ID import, never blind retries.

## Verification and exceptions

Automated suite: **150 passed, 1 skipped** (opt-in Postgres concurrency test). Ruff lint, frontend production build, Alembic schema check and `git diff --check` pass. Desktop/mobile admin smoke checks used an isolated preview database and synthetic operator. The local inquiry-photo audit found no stored inquiry photos to migrate.

Isabella did not perform a recorded acceptance run in this session; acceptance is assumed at the user's direction. The detailed unchecked rehearsal remains in `PHASE9_ACCEPTANCE.md`. Production Stripe webhook delivery, recurring jobs/alerts, Resend, durable public/private R2, remote legacy-media migration/CDN purge and backups are **Phase 12 launch gates**. Final brand assets/font licensing remain Phase 13. Quote #9 (and any other unresolved historical send) remains review-only; this closeout does not authorize a retry.

## Operator commands

From `backend/`:

```sh
uv run python -m app.invoice_refund_audit
uv run python -m app.migrate_inquiry_photos
# After reviewing local-file findings and private storage:
uv run python -m app.migrate_inquiry_photos --apply
# Optional repeatable synthetic Stripe sandbox checks, test keys only:
uv run python -m app.verify_phase9 --apply
```

Schedule and monitor the refund audit alongside existing reconciliation jobs during Phase 12. Never run synthetic verification against the production database.
