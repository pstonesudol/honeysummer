# Phase 11 — account security and support

Implemented October 10, 2026. This is local implementation evidence, **not deployed acceptance**. Phase 12 owns HTTPS/proxy, sender-domain/mail delivery, jobs, backups, runtime DB privileges and deployment checks in `PRODUCTION_READINESS.md`.

## Permission matrix

| Capability | Anonymous / guest | Pending / denied florist | Approved florist | Staff | Owner |
| --- | --- | --- | --- | --- | --- |
| Public products/inquiries/guest retail checkout | Yes | Yes | Yes | Yes | Yes |
| Wholesale products/checkout | No | No | Yes, while active | No | No |
| Own contact/profile/password/email/MFA/privacy request | No | Yes, while active | Yes | Own credentials only | Own credentials only |
| Read order details/packing slips/preparation; update fulfillment | No | No | No | Yes | Yes |
| Inventory/catalogue/content/inquiries/quotes/payments/refunds/reports | No | No | No | No | Yes |
| Approve/deny, invite, suspend/reactivate, revoke, roles, privacy decisions/audit | No | No | No | No | Yes |

All account routes enforce roles on the backend. Staff cannot create manual orders, refund, manage accounts, export reports or edit catalogue/content. Their landing page is Orders, not the financial dashboard. Staff do see order prices/contact/fulfillment details necessary for preparation; do not invite people who should not see those records. `is_active` is independent from florist approval. Suspension retains financial history and invalidates existing sessions. Guests do not receive login accounts.

## Operator workflow

1. Visit `/admin/login`; enter your password. An authenticator is **optional** for owners/staff (opt-in): when one is enrolled you must also enter its code or a recovery code, otherwise the password signs you in. Enroll or replace an authenticator from `/admin/security/`; save the ten one-use recovery codes offline. Password recovery **does not remove MFA**.
2. `/admin/account` links to `/admin/security/`: change password, request confirmed email changes, enroll/replace an authenticator, replace recovery codes, revoke all sessions, or reauthenticate. Sensitive admin mutations require password proof within ten minutes (plus an authenticator code when one is enrolled). Password/email changes revoke every session; sign in again.
3. Owners use `/admin/security/access` to review account IDs/roles/activation, approve/deny florist applications with a reason, invite staff, reissue expired inactive-staff invitations, suspend/reactivate or revoke sessions. Florists cannot be promoted into operator accounts; use a separate staff invitation. Role changes revoke sessions. Self-role/access changes are blocked; the last active owner cannot be demoted/suspended.
4. Invites and recovery/email-confirmation links expire after 30 minutes, are single-use and become invalid after security-version changes. Invitation setup activates the account; authenticator enrollment is optional and no longer gates admin access. Existing expired invitations can be reissued by an owner.
5. Florists sign in at `/wholesale`; Account security provides their self-service contact editor and optional MFA. Login accepts authenticator/recovery codes if enabled. The Forgot password link works for wholesale and admin alike.
6. Deletion/export requests enter an owner review queue. Verify identity and record the legal-retention decision. Deletion disables/anonymizes the account profile, but **never deletes order, invoice, payment or audit history**. Reviewed exports provide contact/order summaries; owners must assemble additional retained order/inquiry/correspondence/media records through the existing workspaces when required. Do not call the summary a comprehensive statutory export. Deliver exports through a verified private channel, not a public link.

## Sessions, browser/proxy contract and passwords

- Opaque 256-bit cookies; only SHA-256 digests live in `account_sessions`. Every protected request checks activation, role/approval and security version in Postgres, with no process-local authorization cache. Logout deletes the registry entry. Legacy signed UID cookies are deliberately rejected.
- Admin absolute/idle expiry: 12 hours / 30 minutes. Florist: 14 days / 3 days. IDs rotate at each sign-in; privilege/security changes invalidate old sessions. Cookies have no Domain attribute, use `/`, HttpOnly, SameSite=Lax and Secure outside debug. MFA challenge cookies are HttpOnly/SameSite=Strict and expire in five minutes; challenge versions cannot survive password/security changes.
- Set `PUBLIC_ORIGIN` to the **exact** browser storefront origin (HTTPS outside debug). Security links never trust Host/forwarded Host. Admin form POSTs require that Origin in production, plus CSRF double-submit proof. API mutations require `X-HoneySummer-Request: 1` and reject foreign Origin/cross-site Fetch Metadata. CORS is disabled. Signed Stripe webhooks are exempt; public inquiry forms are not cookie-authenticated mutations and retain their existing contract.
- IP and account throttles are atomic DB upserts in 15-minute windows: sign-in/MFA/reset/account changes 10 attempts; signup/recovery 5; owner access operations 30. Throttling queues an operator alert and never permanently locks an account. Unknown login addresses perform dummy Argon2 verification; recovery and duplicate signup responses are generic.
- With empty `TRUSTED_PROXY_CIDRS`, the app uses the socket peer address, not untrusted `X-Forwarded-For`. An explicitly trusted peer enables bounded, right-to-left XFF traversal to the first untrusted hop, not a user-selected leftmost address; malformed headers fall back to the peer. Trust only verified proxy CIDRs that append/replace the client chain, never all networks. Until the trusted topology/edge controls are accepted, users behind one proxy share the conservative IP limit. **Phase 12 must exercise spoofed-header/direct-origin requests and configure the verified topology; do not blindly trust forwarding headers.**
- New passwords are 12–1024 characters, accept managers/paste, reject a small local common-password blocklist and have no arbitrary rotation. This is not a comprehensive breached-password database or a claim of password-strength certification.

## Mail and scheduled maintenance

Generate and persist `SECURITY_ENCRYPTION_KEY` (Fernet); back it up separately from Postgres. It encrypts TOTP enrollment/secrets and queued mail containing challenge links. Only challenge/recovery-code hashes are stored in the auth tables. Losing this key breaks MFA and pending mail; do not regenerate it at deploy. Rotate deliberately by re-encrypting retained values under a maintenance procedure, never by replacing the environment value alone.

Security changes commit outbox messages in the same transaction. Messages carry branded HTML and plain text, safe absolute links, clear expiry/next steps and a support address. Production requires Resend; no provider key leaves messages queued instead of falsely succeeding. Debug may log console mail including synthetic links: never run debug with real accounts or ship those logs to production monitoring.

Run an independent minute-interval job:

```sh
uv run python -m app.security_maintenance          # report only
uv run python -m app.security_maintenance --apply  # retry mail and prune expired operational state
```

`app.reconcile --apply` also retries security mail. The security job clears expired challenge-mail bodies without sending them, prunes expired sessions/challenges and 24-hour-old throttle rows, and removes accepted mail metadata after 30 days. Failed/expired mail remains visible in the owner workspace and returns a nonzero job status. Re-request recovery or reinvite after expiry; do not keep retrying an expired link. Owner audit filters show failed sign-ins, rate limits, privilege changes and recovery events. Access-change alerts are queued to the acting owner; repeated attempts alert the configured farm address. Provider acceptance is not inbox delivery. Row locks and Resend idempotency keys reduce duplicates; a crash after provider acceptance can still duplicate after the provider's idempotency retention window. Security events have no ordinary edit/delete UI.

## Recovery and incident procedure

1. Prefer an unused MFA recovery code. Reauthenticate, replace recovery codes and store the new set offline.
2. Lost florist/staff authenticators: verify identity out-of-band using previously recorded contacts; a recently authenticated owner may `reset_mfa` with the verification reason, which revokes sessions. Staff can sign in with their password afterwards and reenroll an authenticator when ready. Never approve recovery solely because someone knows an email or order number.
3. Last-owner break-glass requires trusted hosting/shell access, verified identity and a recorded reason:

   ```sh
   uv run python -m app.owner_recovery --email owner@example.com --reason 'Identity verified via established offline contact; incident reference …'
   ```

   This prompts for exact-email confirmation and a new password (not command-line arguments), only recovers an **existing owner**, revokes sessions, clears old MFA/codes and records `owner_break_glass`. Next sign-in requires a fresh authenticator. Notify the owner and investigate access to the hosting account. This is not a remote password-only MFA bypass.
4. Suspected compromise: suspend or revoke target sessions, preserve audit/financial records, review hosting access, reset credentials/recovery codes, check pending invitations/email changes, then reactivate only after identity review. Notify affected contacts via verified channels. Password reset does not auto-unsuspend an account.

## Migration, retention and review

Migration `e6f3f90ba613` adds security state, backfills existing operators as owners and preserves active state, florist approval and financial records. Take a backup, deploy code/schema together in a maintenance window, migrate, then optionally have owners enroll MFA. Downgrading removes the security registry and is **not a security-safe rollback to legacy cookies**; keep the application offline until a corrected security release is deployed.

Use separate migration/runtime DB credentials. At production activation, revoke UPDATE/DELETE on `security_events` from the application role (allow INSERT/SELECT), including sequence rights for inserts. Protect host logs/backups and restrict the access workspace to owners. Audit reasons must contain identity/decision references, not passwords, tokens or excess customer data. Retain audit evidence under an owner-approved policy (suggested one year pending legal review); financial records follow accountant/legal requirements. Do not automatically erase financial/audit history. Review outstanding/expired mail and completed privacy-export snapshots for minimization; delete/anonymize those only through an approved retention procedure.

Local design review covers copied/legacy cookies, privilege escalation, token races/replay, MFA replay, post-reset challenge/session races, CSRF/Origin/CORS, enumeration, public/private data boundaries and outbox failures. Tests exercise opt-in operator MFA (password-only when none is enrolled, authenticator required once enrolled); existing operations fixtures sign operators in directly rather than bypassing auth. This is an implementation-team review, not an independent penetration test. Deployed proxy/browser/assistive-tech/provider delivery, runtime DB privileges, monitoring and operator rehearsal remain explicitly unchecked in Phase 12.
