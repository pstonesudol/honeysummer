# Honey Summer

Website and commerce platform for Honey Summer, a seasonal flower farm and floral studio in Mountain Top, Pennsylvania.

## Applications

- `frontend/` — Next.js 16, React 19, TypeScript 6, and Tailwind CSS 4
- `backend/` — Python 3.14, Sanic, SQLAlchemy (async), Alembic, and Pydantic

## Local development

### One-command Docker setup

With OrbStack or Docker Desktop running, start PostgreSQL, the API, and Next.js together from the repository root:

```bash
docker compose up --build
```

The first startup builds both application images, waits for PostgreSQL, and runs Alembic migrations automatically. Open [http://localhost:3000](http://localhost:3000); the Dockerized API is available at [http://localhost:8001](http://localhost:8001). Source changes are mounted into both application containers. Set `BACKEND_PORT` before starting Compose if you prefer another host port; container-to-container traffic always uses port 8000.

Stop the stack with `Ctrl+C`, followed by `docker compose down`. Database data remains in the `honeysummer_postgres_data` Docker volume. Use `docker compose down --volumes` only when you intentionally want to erase local data.

> Next.js recommends running `npm run dev` directly on macOS for the fastest file watching. The Compose workflow prioritizes one-command convenience; the separate-process workflow below remains available when maximum Fast Refresh performance matters.

### Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

The site runs at [http://localhost:3000](http://localhost:3000). Requests under `/api/` and `/media/` are proxied to the API in development.

### Backend

Install [uv](https://docs.astral.sh/uv/getting-started/installation/); it will provision the pinned Python 3.14 runtime and project environment. Postgres is recommended for local development.

```bash
cd backend
cp .env.example .env
uv sync --locked
uv run alembic upgrade head
uv run python -m app.seed --email you@example.com --password 'change-me-in-production'
uv run sanic app.server:app --dev
```

The API runs at [http://localhost:8000](http://localhost:8000), with a health check at `/api/health/` and the admin at `/admin/`. Run the test suite with `uv run pytest`. Lint and format the Python code with `uv run ruff check` and `uv run ruff format` (configuration lives in `backend/pyproject.toml`). `uv run ruff check` is the validation gate; `uv run ruff format --check` verifies formatting without rewriting files.

### Pre-commit hooks

A repo-wide [pre-commit](https://pre-commit.com) config (`.pre-commit-config.yaml`) runs the backend's `ruff check --fix` and `ruff format` on staged Python files and the frontend workspace's `eslint` on staged JS/TS files. Install it once:

```bash
uv tool install pre-commit   # one-time; adds pre-commit to your PATH tools
pre-commit install
```

After that the hooks run automatically on `git commit`. Run them against everything with `pre-commit run --all-files`. The hooks use the project's own toolchain (`uv run ruff …` and the frontend workspace's `eslint`), so versions always match the checked-in config.

GitHub Actions (`.github/workflows/ci.yml`) runs the same gates on every push and pull request: `uv lock --check`, `ruff check`, `ruff format --check`, and `uv run pytest` (including the opt-in Postgres concurrency tests against a service database), plus `eslint` for the frontend.

### Content and inquiries

The marketing pages read live content from the API and post inquiries back to it:

- `GET /api/announcement/` — the current active banner announcement (or `null`)
- `GET /api/gallery/` — active wedding portfolio images, in sort order
- `POST /api/inquiries/` — creates a bouquet, wedding, or contact inquiry and emails both the farm and the sender
- `POST /api/auth/signup/` — creates a pending wholesale account with applicant/business details for admin approval; wholesale questions use the Contact form instead
- `GET /api/retail/flowers/` — public list of retail offerings (`channel=retail|both`) with live availability
- `POST /api/retail/checkout/` — guest retail checkout: holds stock, creates an order, and starts Stripe Checkout

Announcements, gallery images, flower listings, florist accounts, inquiries, and orders are all managed from the admin at `/admin` — create the first operator account with `uv run python -m app.seed`. Set `RESEND_API_KEY` (see `backend/.env.example`) to send mail through Resend; without it, messages print to the console for local development. Uploaded photos are stored under `backend/media/` in development and served at `/media/`. Move to Cloudflare R2 before launch so uploads survive deploys.

### Delivery fees

Each flower listing has an optional **delivery fee** (default $0) and a frequency set in `/admin/flowers`: **once per listing** (regardless of quantity), **per unit** (multiplied by quantity), or **once per order**. When multiple once-per-order fees appear in one cart, only the highest is charged; fees in the other two modes are added. Pickup has no delivery fee. This applies equally to retail and wholesale orders and replaces the former flat `RETAIL_DELIVERY_FEE` setting. Both storefronts estimate the fee before checkout; the backend recalculates it from the listings during stock reservation and saves the total on the order. Stripe receives one separate Delivery line item for the total, which is also included in confirmation emails. Set `CHECKOUT_SUCCESS_URL` to the public wholesale page URL before launch; its base URL is used in wholesale approval emails.

### Inventory operations

Use the inventory history and adjustment form on each listing in `/admin/flowers`
instead of overwriting available quantity. Set up the independent scheduled
reconciliation job before accepting live orders. See
[`backend/INVENTORY_RUNBOOK.md`](backend/INVENTORY_RUNBOOK.md) for reservation,
payment/refund, manual market sales, job commands, and incident procedures.
For Stripe Dashboard Tap to Pay setup and the in-person sale workflow, see
[`IN_PERSON_SALES.md`](IN_PERSON_SALES.md). Dashboard payments do not create
website orders; record listed items in the admin inventory journal separately.

## Deployment

- Frontend: Cloudflare Workers through the OpenNext adapter, preserving the same-origin API proxy and server-side auth support.
- Backend and Postgres: Railway. Set the Railway service root directory to `/backend`; `backend/railway.json` supplies build, start (Alembic then Sanic), and health-check commands.

Environment variables are documented in each app's `.env.example` file. Production secrets must not be committed.

Backend dependencies are declared in `backend/pyproject.toml` and reproducibly locked in `backend/uv.lock`. Use `uv add <package>` and `uv remove <package>` rather than editing a requirements file. Schema changes are managed with Alembic (`uv run alembic revision --autogenerate -m "…"`).

### Cloudflare deployment

Cloudflare Pages only supports a static Next.js export, while this application's session-auth architecture needs server-side rewrites and wholesale route checks. The frontend therefore uses Cloudflare Workers with OpenNext.

From the repository root, use `npm run preview` to test the Workers build locally and `npm run deploy` after authenticating Wrangler. Set `API_URL` in the Cloudflare build environment to the public Railway backend URL.

## Brand assets

Gaian and South Coast are self-hosted through `next/font/local` (`frontend/src/app/fonts/`), and Geist is loaded through `next/font`. The client-supplied logo lockup lives in `frontend/public/brand/`: `honey-summer-logo.png` (full color, for light backgrounds) and `honey-summer-logo-light.png` (cream wordmark, for the dark footer). Both are transparent PNGs derived from the client artwork.

South Coast supplies the headings and section titles; Gaian supplies body copy and the `<em>` emphasis inside headings. Both currently carry a desktop-only license, so the webfont binaries are git-ignored and a webfont license must be purchased before they are committed or deployed — see `frontend/src/app/fonts/README.md`. The header and footer wordmark continue to come from the logo image rather than a font. Site photography lives in `frontend/public/images/photography/` as web-sized JPEGs (up to 1800px). The full-resolution supplied originals are retained locally in the git-ignored `frontend/source-photos/` directory; back them up separately, since they are not committed or deployed. The homepage has a meadow splash, photographed shopping pathways, and an editorial floral feature; About features Isabella and a cutting-garden portrait; Order Flowers shows a flower bucket; Weddings & Events shows an arrangement and a seasonal gallery; Wholesale shows hand-tied stems; Contact shows a walk through the garden. The Weddings gallery continues to prefer admin-uploaded portfolio images whenever available.

The implemented color, typography, icon, layout, and accessibility conventions are documented in `frontend/DESIGN_SYSTEM.md`.

## Bouquet proposals

Owner-led bouquet inquiry proposals and Stripe invoices: see [`backend/BOUQUET_PROPOSALS.md`](backend/BOUQUET_PROPOSALS.md).
