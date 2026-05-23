# Developer Memory Garden

A multi-user web notebook for developer commands and notes. Each account gets a personal cheat sheet organized as **topics → sections → entries** (description + command pairs), with search, drag-and-drop reordering, and one-click copy.

The app is server-rendered (FastAPI + Jinja2) with HTMX for in-page updates. There is no JavaScript build step.

**Production:** [developer-memory-garden on Fly.io](https://developer-memory-garden.fly.dev) (when deployed).

## Features

- Per-user notebooks with topic pages and two-column command tables
- Closed registration via admin-issued invitation links
- Optional starter content copied from a global catalog (seeded from the original `Developer_Commands.docx`)
- Full-text search and an alphabetical command index
- Read-only **guest** browsing of admin-selected starter topics
- Admin suite: users, invites, session timeouts, starter catalog editing
- Light/dark theme, CSRF protection, rate-limited auth endpoints

## Requirements

- Python **3.14+**
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick start (local development)

```bash
cd developerNotebook
uv sync
cp .env.example .env   # optional — see Environment variables below
uv run uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

On first startup the app creates SQLite tables, applies lightweight column migrations, seeds the global starter catalog (if empty), and optionally creates a bootstrap admin from environment variables.

### First admin account

Set both variables before starting the server (or add them to `.env`):

```bash
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD='your-strong-password-here'
```

Restart the app. Log in at `/login`, then open `/admin` to create invitation links for new users.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite:///…/notebook.db` | SQLAlchemy database URL |
| `SECRET_KEY` | insecure dev default | Signs session cookies; **required** when `APP_ENV=production` |
| `APP_ENV` | `dev` | Set to `production` to enable HSTS, stricter headers, and hide OpenAPI docs |
| `SECURE_COOKIES` | off | Set to `true` when serving over HTTPS |
| `ALLOWED_HOSTS` | (none) | Comma-separated hostnames for `TrustedHostMiddleware` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | (none) | Bootstrap or promote an admin on startup |
| `GUEST_USERNAME` | `__guest__` | Username for the read-only guest account |
| `LOG_LEVEL` | `INFO` | Python logging level |

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for architecture, routes, testing, and how to extend the app.  
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Fly.io deployment and secrets setup.

## Running tests

```bash
uv run pytest
```

Tests use an in-memory SQLite database and inject a stable `SECRET_KEY` automatically.

## Deployment

Production runs on [Fly.io](https://fly.io) with a persistent SQLite volume. See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for first-time setup, `fly secrets set` commands, routine deploys, backups, and troubleshooting.

## Project layout

```
app/
  main.py           FastAPI app factory, middleware, lifespan
  models.py         SQLAlchemy models
  routes/           Page and HTMX fragment handlers
  templates/        Jinja2 HTML (pages + partials)
  static/           CSS and small JS helpers (CSRF, SortableJS, theme)
  services/         Seed import, guest visibility
tests/              Pytest suite
scripts/            Local/Fly SQLite backup script
docs/               Developer documentation
```

## License

Private project — no license file is included.
