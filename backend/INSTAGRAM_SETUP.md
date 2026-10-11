# Instagram gallery setup

The storefront shows the account's **six most recent Instagram posts**: a strip on the
home page and a card on the contact page. Posts link out to
`https://www.instagram.com/hellohoneysummer/`.

The feed is read server-side from the **Instagram API with Instagram Login**
(`graph.instagram.com`). It is off until an access token is configured, and the pages fall
back to a plain profile link in the meantime, so the site never looks broken.

This guide covers getting a token, wiring it up, and keeping it alive. It is written for one
account that you own and manage, which is the simplest and most common case.

## Official documentation (source of truth)

Meta documents this end to end; this guide is the site-specific wrapper around it. Verify
against these if anything looks different:

| Topic | Link |
| --- | --- |
| Instagram Platform overview | <https://developers.facebook.com/docs/instagram-platform/overview> |
| Create an Instagram app (incl. selecting the Business app type) | <https://developers.facebook.com/docs/instagram-platform/create-an-instagram-app> |
| Get started with Instagram Login (get a token, `/me`, media) | <https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/get-started> |
| Business Login for Instagram (login flow, exchange to long-lived) | <https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login> |
| Access Token reference (`/access_token`) | <https://developers.facebook.com/docs/instagram-platform/reference/access_token> |
| Refresh Access Token reference | <https://developers.facebook.com/docs/instagram-platform/reference/refresh_access_token> |
| Instagram Media reference (fields) | <https://developers.facebook.com/docs/instagram-platform/reference/instagram-media> |
| Graph API versions & changelog | <https://developers.facebook.com/docs/graph-api/changelog/versions/> |
| Full product index (LLM-friendly) | <https://developers.facebook.com/documentation/instagram-platform/llms.txt> |

---

## 1. What you need

- The `@hellohoneysummer` Instagram account set to a **Professional** account type
  (Business or Creator). Personal accounts cannot use the API.
- A **Meta developer account** and an app: <https://developers.facebook.com/apps>.
- The app secret (for the one-time short-lived → long-lived exchange, if you go that route).
- ~10 minutes, then a recurring ~1-minute refresh every 30–45 days.

The token has these properties:

| Property | Value |
| --- | --- |
| Type | Instagram User access token (long-lived) |
| Lifetime | 60 days, refreshes to another 60 days |
| Permission | `instagram_business_basic` |
| Host | `https://graph.instagram.com` |

---

## 2. Get a long-lived token (App Dashboard — recommended)

For an app that only reads your own account, you do **not** need to build a login flow. Generate
the token from the dashboard:

1. **Make the account Professional.** In the Instagram app: *Settings and privacy → Account type
   and tools → Switch to Professional account*, then pick Business or Creator.
2. **Create the app.** At <https://developers.facebook.com/apps> → *Create app*. Choose the
   app type that lets you add Instagram (for example, a Business-type app), then add the
   **Instagram** product and open **Business login for Instagram**.
3. **Configure business login.** Under *Instagram → API setup with Instagram business login*,
   add/link the `@hellohoneysummer` account and note the **Instagram app ID** and **Instagram
   app secret**.
4. **Generate the token.** Next to the linked account, click **Generate token**, sign in to
   Instagram, and approve. Copy the token.
5. **Check it.** Confirm the token and account with:

   ```bash
   curl -s "https://graph.instagram.com/v26.0/me?fields=user_id,username&access_token=<TOKEN>"
   # {"user_id":"1784...","username":"hellohoneysummer","id":"1784..."}
   ```

   A successful response proves the token works. An error here means the token or account setup
   is wrong — fix it before continuing.

> Dashboard tokens are **long-lived** (60 days). Tokens obtained through a full OAuth login
> flow are short-lived (1 hour) and must be exchanged for a long-lived one; see section 6.

---

## 3. Configure the backend

Add the token to the backend environment (never the frontend, never committed):

```bash
# backend/.env
INSTAGRAM_ACCESS_TOKEN=<TOKEN>
# Optional: pin the Graph API version. Defaults to v26.0.
INSTAGRAM_API_VERSION=v26.0
```

Then restart the API service so the setting is picked up (for local Docker:
`docker compose restart api`, or restart your `uv run sanic ...` process).

---

## 4. Verify

1. **API:**

   ```bash
   curl -s http://localhost:8000/api/instagram/ | head -c 400
   # {"posts":[{"id":"...","image":"https://...","permalink":"https://www.instagram.com/p/...","caption":"...","media_type":"IMAGE"}, ...]}
   ```

   `{"posts":[]}` means no token, an invalid token, or a failed fetch — check the backend logs
   for `Unable to load the Instagram feed`.

2. **Pages:** load `/` and `/contact`. The feed is cached ~15 minutes, so allow that long after a
   change (or restart the API to clear the in-memory cache immediately).

---

## 5. Keep it alive (refresh every 30–45 days)

A long-lived token must be refreshed **before it expires**; a token that has gone 60 days without
a refresh can no longer be refreshed and you must redo section 2.

Refresh conditions:

- The token is at least **24 hours old**.
- The token is **not expired**.
- The account still grants `instagram_business_basic`.

```bash
curl -s "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=<CURRENT_TOKEN>"
# {"access_token":"<NEW_TOKEN>","token_type":"bearer","expires_in":5183944}
```

Then replace `INSTAGRAM_ACCESS_TOKEN` in `backend/.env` with the new value and restart the API.

Notes:

- Refreshing returns a **new** token, but the old one also stays valid with its expiry extended,
  so a short overlap is harmless.
- Once a day is enough (refreshing more often does nothing extra). A monthly or twice-monthly
  reminder/scheduled job around day 45 is a safe cadence.
- Store the token as a secret (a secret manager or your host's env settings). If it leaks,
  regenerate it in the App Dashboard.

---

## 6. Optional: the full token exchange (login flow / multiple accounts)

Only needed if you implement Business Login for Instagram or manage several accounts. The flow is:

| Step | Endpoint |
| --- | --- |
| Authorize (get a code) | `https://www.instagram.com/oauth/authorize` |
| Code → short-lived token (1 hour) | `https://api.instagram.com/oauth/access_token` |
| Short-lived → long-lived (60 days) | `https://graph.instagram.com/access_token` |
| Refresh long-lived | `https://graph.instagram.com/refresh_access_token` |

The short-lived → long-lived exchange needs the **app secret**, so it must run **server-side
only** — never in the browser or a shipped app binary:

```bash
curl -s "https://graph.instagram.com/access_token\
?grant_type=ig_exchange_token\
&client_secret=<INSTAGRAM_APP_SECRET>\
&access_token=<SHORT_LIVED_TOKEN>"
```

---

## 7. Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `/api/instagram/` returns `{"posts":[]}` and logs `Unable to load the Instagram feed` | Token missing/expired/invalid, or the account is not Professional. Recheck with the `/me` call in section 2. |
| Error code `190` / `OAuthAccessTokenException` | Token expired or revoked. Get a fresh token (section 2). |
| Error code `200` / permission error | Missing `instagram_business_basic`, or the account is not linked to the app. Fix the app/account setup. |
| `Unsupported get request` / version error | `INSTAGRAM_API_VERSION` points at a retired version. See the supported list below and update it. |
| Error code `100` after changing the requested fields | Instagram Login may refuse `caption` / `media_product_type` (Meta marks them "Facebook Login only"). Remove fields one at a time; the code already treats captions as optional. |
| Folder shows pink/blank squares | The Instagram CDN images did not load (network/CSP), or posts have no `media_url`. Check the browser console. |
| Gallery updates slowly | Expected: 15-minute cache. Restart the API to clear it now. |
| Token stopped working after ~60 days | It was not refreshed in time. Redo section 2 and set a refresh reminder. |

Supported Graph API versions (as of late 2026): **v26.0** (latest), v25.0, v24.0, v23.0.
v22.0 and older are retired. See the Meta changelog for dates:
<https://developers.facebook.com/docs/graph-api/changelog/versions/>.

---

## 8. Security notes

- The access token is a **secret**. Keep it in the backend environment only. The frontend never
  receives it — it only receives post image URLs and permalinks from `/api/instagram/`.
- Never put the token or app secret in client-side code, a public repository, or a URL you share.
- The backend only accepts posts whose permalink starts with `https://www.instagram.com/`, and it
  never stores media URLs (they are signed, expiring CDN links).

---

## 9. Where the code lives

| File | Role |
| --- | --- |
| `backend/app/instagram.py` | Fetches, normalizes, and caches the feed; degrades to empty on failure. |
| `backend/app/routes/content.py` | `GET /api/instagram/` public endpoint. |
| `backend/app/settings.py` | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_API_VERSION`. |
| `backend/tests/test_instagram.py` | Normalization, no-token, and failure-degradation tests. |
| `frontend/src/components/instagram-gallery.tsx` | The `card` (contact) and `strip` (home) renderers. |
| `frontend/src/lib/api.ts` | `getInstagramPosts()` (15-minute revalidation). |
