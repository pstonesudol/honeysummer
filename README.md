# Honey Summer

Website and commerce platform for Honey Summer, a seasonal flower farm and floral studio in Mountain Top, Pennsylvania.

## Applications

- `frontend/` — Next.js 16, React 19, TypeScript 6, and Tailwind CSS 4
- `backend/` — Python 3.14, Django 6.1, and Django REST Framework

## Local development

### One-command Docker setup

With OrbStack or Docker Desktop running, start PostgreSQL, Django, and Next.js together from the repository root:

```bash
docker compose up --build
```

The first startup builds both application images, waits for PostgreSQL, and runs Django migrations automatically. Open [http://localhost:3000](http://localhost:3000); the Dockerized API is available at [http://localhost:8001](http://localhost:8001). Source changes are mounted into both application containers. Set `BACKEND_PORT` before starting Compose if you prefer another host port; container-to-container traffic always uses port 8000.

Stop the stack with `Ctrl+C`, followed by `docker compose down`. Database data remains in the `honeysummer_postgres_data` Docker volume. Use `docker compose down --volumes` only when you intentionally want to erase local data.

> Next.js recommends running `npm run dev` directly on macOS for the fastest file watching. The Compose workflow prioritizes one-command convenience; the separate-process workflow below remains available when maximum Fast Refresh performance matters.

### Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

The site runs at [http://localhost:3000](http://localhost:3000). Requests under `/api/` are proxied to Django in development.

### Backend

Install [uv](https://docs.astral.sh/uv/getting-started/installation/); it will provision the pinned Python 3.14 runtime and project environment. Postgres is recommended for local development.

```bash
cd backend
cp .env.example .env
uv sync --locked
uv run python manage.py migrate
uv run python manage.py runserver
```

The API runs at [http://localhost:8000](http://localhost:8000), with a health check at `/api/health/` and admin at `/admin/`.

### Content and inquiries

The marketing pages read live content from the API and post inquiries back to it:

- `GET /api/announcement/` — the current active banner announcement (or `null`)
- `GET /api/gallery/` — active wedding portfolio images, in sort order
- `POST /api/inquiries/` — creates an inquiry and emails both the farm and the sender

Announcements, gallery images, and inquiries are all managed from the Django admin. Set `RESEND_API_KEY` (see `backend/.env.example`) to send mail through Resend; without it, messages print to the console for local development. Uploaded photos are stored under `backend/media/` in development and served at `/media/`. Move to Cloudflare R2 before launch so uploads survive deploys.


## Deployment

- Frontend: Cloudflare Workers through the OpenNext adapter, preserving the same-origin API proxy and server-side auth support.
- Backend and Postgres: Railway. Set the Railway service root directory to `/backend`; `backend/railway.json` supplies build, start, and health-check commands.

Environment variables are documented in each app's `.env.example` file. Production secrets must not be committed.

Backend dependencies are declared in `backend/pyproject.toml` and reproducibly locked in `backend/uv.lock`. Use `uv add <package>` and `uv remove <package>` rather than editing a requirements file.

### Cloudflare deployment

Cloudflare Pages only supports a static Next.js export, while this application's session-auth architecture needs server-side rewrites and wholesale route checks. The frontend therefore uses Cloudflare Workers with OpenNext.

From the repository root, use `npm run preview` to test the Workers build locally and `npm run deploy` after authenticating Wrangler. Set `DJANGO_API_URL` in the Cloudflare build environment to the public Railway backend URL.

## Brand assets

Fraunces and Geist are loaded through `next/font`. The client-supplied logo lockup lives in `frontend/public/brand/`: `honey-summer-logo.png` (full color, for light backgrounds) and `honey-summer-logo-light.png` (cream wordmark, for the dark footer). Both are transparent PNGs derived from the client artwork.

The Blastine script font is still worth licensing for handwritten accents and section flourishes; the header and footer wordmark now come from the logo image rather than a font. Placeholder flower artwork should be replaced with client photography.

The implemented color, typography, icon, layout, and accessibility conventions are documented in `frontend/DESIGN_SYSTEM.md`.
