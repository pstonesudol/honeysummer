# Phase 12 staging validation — October 14, 2026 UTC

**Current status index:** [`../STATUS.md`](../STATUS.md). This is a dated partial
acceptance log, not a separate status tracker, Phase 12 completion or launch
approval. Operator: assistant, using owner-authorized staging browser and
read-only provider checks.
No production mutations. No credentials, cookie values or private image contents
are retained here. Local tests are distinguished from deployed observations.

## Release context

- PR #22: wedding upload helper changed to 50 MiB; release run
  https://github.com/pstonesudol/honeysummer/actions/runs/38497130423 deployed
  staging at `58373b4cd95f9ac35c7dbf69e39029b145700991`. Live helper text checked.
- PR #23: mobile inquiry layout fixed; live 390px recheck showed one-column
  controls (~272px), an 18px square consent checkbox and in-bounds navigation.
  Earlier snapshot `missingAccessibleName` flags were not confirmed defects:
  PR's independent Chromium accessible-name checks passed. Physical-device and
  screen-reader acceptance is still open.
- PR #24: public-image optimization fixed; PR #25 supplies upload previews.
  Latest staging backend observed successful deployment
  `ccacdc4a-8953-4457-9e75-86bedd7b87c0` (created 02:34:33 UTC). Railway deployment
  metadata does not expose a git SHA; PR merge plus owner-reported staging rollout
  and observed behavior provide evidence, not exact source attestation.

## Observed results

| Area / register IDs | Result | Evidence and limits |
| --- | --- | --- |
| Upload helper / B1 | Pass, targeted | Live wedding form says 50 MiB. |
| Mobile regression / B1, B7 | Pass, targeted | Live 390px bounds corrected after #23; full accessibility/device checks remain open. |
| Optimized public upload / A2, E1 | Pass, targeted | Owner selected 15,118,440-byte high-resolution JPEG. Replacement stored as `gallery/2026/10/26688f1f806645d6aaa946290ae0d5b9.webp`; downloaded bytes verify WebP, 312,388 bytes, 1600×2400. ~97.93% byte reduction, below 2 MiB and 2400px caps. Test Gallery item remains inactive. |
| R2 cache / E1 | Pass, targeted | Public GET 200, `image/webp`, one-year public immutable cache; first curl GET MISS and second HIT. HEAD returned DYNAMIC and was not used to assess GET cache. Python urllib requests can be blocked by Cloudflare; curl GET succeeded. |
| Backend upload-size rejection / A2, E1 | Pass, targeted | Owner-selected fixture displayed 50.00 MB (rounded; browser does not expose exact file bytes). Saving returned `Choose an image no larger than 50 MiB.` Railway POST `/admin/gallery/new` returned 400 at 02:56:51 UTC with no upstream error; admin still showed exactly one existing inactive WebP item, no new row. Rejection corresponds to backend size validation, not proxy rejection. |
| Worker request-size rejection / A2 | Pass, targeted | Owner-selected fixture displayed 60.00 MB (rounded). Saving returned exact Worker error `Upload request exceeds the 60 MiB limit.` No additional Gallery POST appeared in the sampled Railway logs; admin still showed one existing inactive WebP item. Browser driver does not expose network status; expected Worker implementation status is 413, not independently captured in browser. |
| Malformed image validation / E1 | Pass, targeted | Fresh-form submission with required alt text rejected the 25-byte JPEG-signature fixture: `Upload a valid, complete PNG, JPEG, WebP or GIF image (not an SVG).` Preview independently warned it could not display image. Missing alt text was also rejected in preceding attempt. Earlier stale-CSRF response was inconclusive; fresh retry reached image validation. |
| Private-photo read / A2, E1, E2 | Pass, targeted | Existing test inquiry photo renders through signed-in admin at 2667×4000 before and after subsequent deployments. Application-session expiry redirected same route to admin login while outer Access remained active; fresh admin login restored read. Raw-byte equality, exact private-key absence from public storage and recovery remain open. |
| New private upload after optimization / B1, E1 | Pass, targeted | Wedding submission with owner-selected ~0.15 MB valid photo created exactly one new labeled test inquiry (#5); thank-you page reached and signed-in admin `/admin/inquiries/5/photo` rendered 800×800. Farm/customer email outcomes reported accepted, not delivered (reserved `.invalid` recipient cannot establish delivery). Raw-byte equality, exact private-key absence from public storage, newly uploaded-photo anonymous denial and recovery remain open. |
| Inactive Gallery visibility / B1 | Pass, targeted | Storefront `/api/gallery/` returned `[]` while admin had one inactive test item. |
| Direct-origin boundaries / A2, F2 | Pass, targeted | Railway health 200; catalogue, admin login, private photo, public media and packing slip 403. Wrong synthetic origin secret and forged forwarding identity did not bypass gate. |
| Unsigned Stripe webhook / C1 | Pass, negative probe | Direct staging webhook rejected unsigned `{}` POST with 400. Does not prove signed delivery/retry/ledger behavior. |
| Invalid reset/email-change/invite / F4 | Pass, negative probes | Bogus tokens submitted through live forms rejected as invalid/expired/already used. No account update or security mail triggered by these branches. Real expiry/replay and successful recovery remain open. |
| Unsupported token kind / F4 | Pass, negative probe | `kind=admin` rejected as invalid link. |
| Forged payment return / B5 | Pass, targeted | Nonexistent synthetic checkout UUID returned `Checkout not found`. A forged `checkout=success` storefront URL did not display verified payment or clear a one-item $5 retail cart after reload. Test cart item removed afterward; no checkout initiated or stock reserved. |
| Reporting / D6 | Pass, targeted | Seven paid orders sum to $75; separate $500 unpaid invoice excluded from paid sales. October 14 filter correctly returns no paid orders. Order #10 has five $5 units, $25 total; packing slip matches. No payment/refund/stock/fulfillment changes. |
| Queues / C4, E3, E4 | Healthy snapshot only | Admin reported no queued security mail, failed inquiry mail, unsent confirmations or uncertain refunds. Provider acceptance is not inbox delivery. |
| Inventory / C2 | Healthy snapshot only | Two retail listings have nonnegative stock and zero reservations; not a contention test. No wholesale listings available in inspected inventory. |
| Resource headroom / A1 | Observation only | One-hour staging sample: memory current 0.324 GB, peak 0.557 GB, 8 GB limit. Not concurrent-upload stress acceptance. |
| Logs / G1 | Healthy snapshot only | Recent 501-entry HTTP sample reported all 200 and no upstream errors; not representative alert/escalation acceptance. |
| Environment isolation / A1 | Partial | Six R2 variable names present in staging, absent in production; values hidden. Both environments online. No production changes. Other provider credential isolation remains open. |

## Open gates / negative or blocked results

- Scheduled reconciliation absent: Railway services have no cron; latest persisted
  manual report shown October 12 with zero findings. C3/C4 remain open.
- No Railway project alert webhooks: G1/C4 escalation coverage remains open;
  this does not exclude monitoring outside Railway.
- Staging Postgres PITR status: `enabled=false`, `bucketWired=false`. Automated
  backup policy and isolated restore/media/key recovery not accepted (G2).
- Direct automated 60 MiB rejection probe blocked by Cloudflare (403/error 1010)
  before Worker; inconclusive. Subsequent browser backend 50 MiB and Worker
  60 MiB oversize rejections passed; local declared/chunked limit tests passed. Near-limit
  concurrent-upload behavior remains open.
- Old full-size JPEG still exists as a legacy public object. Replacing Gallery
  reference does not delete objects/caches or migrate listing/order snapshots.
  Original retention decision for new public uploads: no master archive; owner
  must retain professional originals independently.
- A separate no-photo test inquiry (#4) was created; deletion returned generic
  form error and row remained. Do not silently repeat deletion or delete user
  inquiry #3. Cleanup/error diagnosis remains open.
- Signed Stripe retries/replay/refunds, wholesale/shared-stock cases, valid-token
  expiry/recovery, broader role/security tests and operational sign-off remain open.

## Next queue

- Live upload-limit rehearsal prepared two padded, non-sensitive JPEG fixtures
  outside the repository: 50 MiB + 1 byte and 60 MiB + 1 byte. Owner reauthenticated
  and selected a 50.00 MB displayed fixture; backend rejected it correctly (above).
  Owner subsequently selected the 60.00 MB displayed fixture; Worker rejected it
  with the expected limit message. Neither created a new Gallery row.
- Next live E1 check: malformed JPEG (valid initial signature but undecodable
  contents) fixture prepared outside repository. Owner must attach
  `honeysummer-corrupt-image.jpg`. Owner selected it; preview warned it could
  not render. Submission returned `Invalid CSRF token`, before image validation.
  Thus malformed-image backend check is inconclusive; no image-validation pass
  is claimed. The new-Gallery page will be freshly loaded and owner must select
  the fixture again. Other admin-tab navigation may have rotated the CSRF cookie;
  causal attribution is not yet proven. Do not treat this as a confirmed defect.
  Fresh retry subsequently passed malformed-image rejection after filling required
  alt text; no successful save occurred. Gallery list remained exactly one
  existing inactive WebP item afterward.
- Post-optimization private-upload regression: wedding form prefilled with
  clearly labeled test identity and reserved `.invalid` recipient. Owner selected
  a non-sensitive valid ~0.15 MB image. Submission succeeded; #5 and admin photo
  retrieval verified (above). One additional test inquiry now remains in staging;
  do not delete it without reviewing correspondence dependencies/cleanup scope.

Continue safe deployed negative checks and record results here. Provider-changing,
destructive restore, paid-resource and production operations require separately
approved procedures. A browser-selected file is needed for new upload tests;
the available browser driver cannot attach local files automatically.
