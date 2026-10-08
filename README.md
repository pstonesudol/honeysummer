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

The API runs at [http://localhost:8000](http://localhost:8000), with a health check at `/api/health/` and the admin at `/admin/`. Run the test suite with `uv run pytest`.

### Content and inquiries

The marketing pages read live content from the API and post inquiries back to it:

- `GET /api/announcement/` — the current active banner announcement (or `null`)
- `GET /api/gallery/` — active wedding portfolio images, in sort order
- `POST /api/inquiries/` — creates an inquiry and emails both the farm and the sender
- `GET /api/retail/flowers/` — public list of retail offerings (`channel=retail|both`) with live availability
- `POST /api/retail/checkout/` — guest retail checkout: holds stock, creates an order, and starts Stripe Checkout

Announcements, gallery images, flower listings, florist accounts, inquiries, and orders are all managed from the admin at `/admin` — create the first operator account with `uv run python -m app.seed`. Set `RESEND_API_KEY` (see `backend/.env.example`) to send mail through Resend; without it, messages print to the console for local development. Uploaded photos are stored under `backend/media/` in development and served at `/media/`. Move to Cloudflare R2 before launch so uploads survive deploys.

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
