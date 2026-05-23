# Developer guide

This document explains how **Developer Memory Garden** is built, how data flows through it, and how to work on it safely.

## What this app is

A personal, multi-user reference notebook. The original inspiration was a Word cheat sheet (`Developer_Commands.docx`) organized by technology topic. The web app mirrors that structure but is **not** wired to the Word file at runtime — starter content lives in the database and in `app/seed_data.py`.

Users interact through HTML pages. Most edits (add/rename/delete/reorder) happen via **HTMX** fragment swaps without a full page reload.

---

## Architecture

```
Browser
   │  GET full pages (Jinja2)
   │  POST/PUT/DELETE HTMX partials
   ▼
FastAPI (app/main.py)
   ├── Middleware: SlowAPI rate limit, CSRF, security headers, HTTPS (prod)
   ├── Routes: pages, topics, sections, entries, search, admin
   └── SQLAlchemy → SQLite (default) or DATABASE_URL
```

### Stack

| Layer | Choice |
|-------|--------|
| Web framework | FastAPI + Uvicorn |
| Templates | Jinja2 (`app/templating.py`) |
| ORM | SQLAlchemy 2.x declarative |
| Database | SQLite (file or in-memory in tests) |
| Auth | Signed session cookie (`itsdangerous`) + bcrypt passwords |
| Interactivity | HTMX 2.x (CDN) |
| Drag-and-drop | SortableJS (CDN) + small init in `app/static/app.js` |
| Styling | Plain CSS with custom properties (`app/static/styles.css`) |

There is **no** npm, Vite, or React build step. Custom JavaScript is limited to CSRF header injection, theme toggle, copy-to-clipboard, SortableJS wiring, and a few UX helpers.

### Application factory

`create_app(enable_lifespan=True)` in `app/main.py` builds the FastAPI instance. Production uses `app = create_app(enable_lifespan=True)`.

When `enable_lifespan=False` (tests), startup skips `create_all`, migrations, and bootstrap so pytest can bind an isolated in-memory database via dependency override.

---

## Directory structure

```
app/
  main.py              Entry point, middleware stack, router registration
  database.py          Engine, SessionLocal, get_db(), SQLite column migrations
  models.py            User, Topic, Section, Entry, Invitation, Starter*, AppSettings
  auth.py              Password hashing, session cookies, require_auth / require_admin
  bootstrap.py         Startup: admin from env, starter catalog seed, guest user
  settings.py          Session timeout settings (singleton AppSettings row)
  slug.py              URL slug allocation for topics
  indexing.py          Search queries, alphabetical index, FTS5 shadow table
  csrf.py              CookieFormCSRFMiddleware (form + header token support)
  rate_limit.py        SlowAPI limiter (IP-based; isolated per test client request)
  seed_data.py         Bundled starter topics as Python dicts (generated from docx)
  docx_seed.py         Parser to regenerate seed_data from Developer_Commands.docx
  routes/
    pages.py           Auth, home, topic pages, welcome, account settings
    topics.py          Topic CRUD + reorder (HTMX)
    sections.py        Section CRUD + reorder (HTMX)
    entries.py         Entry CRUD + reorder (HTMX)
    search.py          Search page + nav live search + index page
    admin.py           Admin suite under /admin
  services/
    seed.py            Copy starter catalog into a user's notebook
    guest.py           Guest-visible starter topics
  templates/           Full pages and partials for HTMX swaps
  static/              CSS, app.js, topic.js, icons
tests/                 Pytest; conftest.py sets up in-memory DB + TestClient
scripts/
  backup-notebook.sh   Local + Fly SQLite backups to Dropbox
```

---

## Data model

### User content (per account)

```
User
 └── Topic (user_id, name, slug, display_order)
      └── Section (name nullable = default section, notes, display_order)
           └── Entry (description, command, display_order)
```

**Default section behavior:** Creating a topic also creates one section with `name=NULL`. The UI hides section headings and the section sidebar until the topic has multiple sections or any named section. This lets simple topics (Flask, MongoDB, etc.) look like a flat table.

**Slugs** are unique per user (`UniqueConstraint` on `user_id + slug`).

### Global starter catalog

Separate tables — not tied to a user:

- `StarterTopic` → `StarterSection` → `StarterEntry`

Populated once at startup from `STARTER_DATA` in `app/seed_data.py` if the catalog is empty. Admins edit this catalog at `/admin/starter`. Users copy selected topics into their notebook via `/welcome` or `/seed-topics`.

`StarterTopic.guest_visible` controls which catalog topics appear for the read-only guest account.

### Other tables

| Model | Purpose |
|-------|---------|
| `Invitation` | Single-use registration codes created by admins |
| `AppSettings` | Singleton row (`id=1`) for session absolute/idle timeouts |

### User flags

| Field | Meaning |
|-------|---------|
| `is_admin` | Access to `/admin` |
| `is_guest` | Read-only; sees guest-visible starter topics, not personal topics |
| `is_suspended` | Login denied |
| `session_version` | Increment to invalidate all session cookies (password reset, suspend) |
| `failed_login_count` / `locked_until` | Brute-force lockout after failed logins |

---

## Authentication and sessions

### Session cookie

- Name: `session`
- Signed with `URLSafeSerializer` + `SECRET_KEY`
- Payload: `user_id`, `session_version`, `iat`, `last_activity`
- **Absolute** and **idle** timeouts come from `AppSettings` (defaults: 14 days absolute, 60 minutes idle)
- On each authenticated request, `require_auth` refreshes `last_activity` if the session is still valid

### Dependencies

| Dependency | Use |
|------------|-----|
| `require_auth` | Any logged-in user; redirects to `/login` |
| `require_can_write` | Blocks guest accounts (403) |
| `require_admin` | Admin-only routes |

### Registration flow

1. Admin creates invite at `/admin/invites` → link `/register?code=…`
2. User registers → session created → redirect to `/welcome`
3. User picks starter topics or starts blank → redirect to `/`
4. Later, `/seed-topics` allows importing additional catalog topics

Registration is **invitation-only**. Rate limit: 5/minute on POST `/register`.

### Guest login

POST `/guest-login` logs into the synthetic guest user (created at startup). Guests browse admin-flagged starter topics only.

---

## HTMX patterns

Full pages extend `templates/base.html`, which loads HTMX, SortableJS, and `app.js`.

**Fragment routes** return partial templates (under `templates/partials/`) that HTMX swaps into the DOM. Common patterns:

- `hx-get` + `hx-swap="outerHTML"` for inline edit forms
- `hx-post` / `hx-put` / `hx-delete` for mutations
- `hx-confirm` for delete confirmation
- `HX-Redirect` response header for admin actions that need a full navigation

### CSRF

`CookieFormCSRFMiddleware` sets a `csrftoken` cookie. Mutating requests must send the token via:

- Header `x-csrftoken`, or
- Form field `csrftoken`

`app.js` registers an `htmx:configRequest` listener to attach the header automatically. Pytest's `client` fixture does the same in `tests/conftest.py`.

### SortableJS

Reorder endpoints:

- `PUT /topics/reorder`
- `PUT /sections/reorder`
- `PUT /entries/reorder`

Each expects an ordered list of IDs; initialization lives in `app.js` / `topic.js`.

---

## Search and index

### Search (`/search`)

Tokenizes the query on whitespace; **all** tokens must match (AND) as case-insensitive substrings in `description` or `command`. Scoped to the current user's entries (or guest-visible starter entries for guests). Limited to 50 results.

Nav bar live search uses `GET /search?view=nav` and returns a partial.

### Index (`/index`)

Alphabetical browse grouped by the first letter of each entry's description (non-letters → `#`). Separate query path for guest starter content.

### FTS5 shadow table

`app/indexing.py` maintains an `entries_fts` FTS5 virtual table on write. **Search does not read from FTS** — it uses SQL `ILIKE` so results stay correct even if FTS is stale. FTS exists for possible future use; `fts_rebuild()` runs after bulk seed imports.

---

## Admin suite (`/admin`)

All routes require `require_admin`. Key areas:

| Path | Purpose |
|------|---------|
| `/admin` | User list: suspend, unlock, delete, reset password |
| `/admin/invites` | Create/revoke invitation links |
| `/admin/starter` | Edit global starter catalog (mirror of topic/section/entry CRUD) |
| POST `/admin/settings/session-timeouts` | Configure session absolute/idle minutes |

Admin HTMX responses often use `HX-Redirect` via `_htmx_or_redirect()` in `admin.py`.

Safeguards include: cannot delete the last admin, cannot suspend/delete self in destructive ways without checks.

---

## Database

### Connection

`DATABASE_URL` defaults to `sqlite:///<project_root>/notebook.db`.

For Fly.io with a mounted volume:

```
DATABASE_URL=sqlite:////data/notebook.db
```

### Schema management

There is **no Alembic**. Schema evolves via:

1. `Base.metadata.create_all()` on startup
2. `apply_sqlite_user_column_migrations()` — manual `ALTER TABLE` for legacy SQLite files when new columns were added to `User` or `StarterTopic`

When adding columns to existing models, update **both** the ORM model and `apply_sqlite_user_column_migrations()` so existing deployments upgrade cleanly.

### Startup tasks (`app/bootstrap.py`)

Run inside the FastAPI lifespan, in order:

1. `ensure_app_settings()` — singleton settings row
2. `bootstrap_admin_from_env()` — optional admin from `ADMIN_*`
3. `seed_starter_catalog_if_empty()` — load `STARTER_DATA` if catalog empty
4. `ensure_starter_topic_slugs()` — backfill missing slugs
5. `bootstrap_guest_user()` — create guest account if missing

---

## Frontend conventions

- **Templates:** Jinja2 with `{% include %}` for partials; `user` is passed to most pages for nav
- **CSS:** Custom properties in `:root` for theming; `[data-theme="dark"]` overrides in `styles.css`
- **Theme:** `theme-init.js` runs before paint to avoid flash; preference stored in `localStorage`
- **Icons:** SVG sprites under `app/static/icons/light/` (and dark variants where used)

When adding a new interactive control, prefer HTMX attributes in templates over new JavaScript unless SortableJS or clipboard behavior requires it.

---

## Regenerating starter data from Word

If `Developer_Commands.docx` changes:

```bash
uv run python -c "from app.docx_seed import docx_to_starter_data; print(docx_to_starter_data())"
```

Review output and update `app/seed_data.py`. The docx is **not** read at runtime in production — only during regeneration. Existing deployments keep their DB catalog until an admin edits `/admin/starter` or the catalog is re-seeded on a fresh database.

---

## Testing

```bash
uv run pytest              # all tests
uv run pytest tests/test_auth.py -k login
```

### Fixtures (`tests/conftest.py`)

| Fixture | Provides |
|---------|----------|
| `test_db` | Fresh in-memory SQLite session |
| `client` | `TestClient` with CSRF header injection |
| `register_invite` | Valid invitation row |
| `authenticated_client` | Registered test user with session |
| `starter_catalog` | Populated global starter tables |
| `seeded_client` | Authenticated user with imported starter topics |

Tests set `SECRET_KEY`, `SECURE_COOKIES=false`, and `APP_ENV=dev` automatically.

When adding POST/PUT/DELETE routes, ensure tests send the CSRF token (follow existing client fixture pattern).

---

## Deployment and operations

Fly.io deployment, secrets, backups, and troubleshooting are documented in **[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## Security checklist for changes

- Mutating routes must go through CSRF middleware (safe methods: GET, HEAD, OPTIONS only)
- Use `require_can_write` for any route that modifies user notebook content
- Scope queries by `user_id` (or guest starter paths) — never trust client-supplied IDs alone
- Hash passwords with `hash_password()`; validate with `validate_password()`
- Rate-limit sensitive auth endpoints (see `@limiter.limit` on login/register)
- Never commit `.env`, `*.db`, or secrets
- In production, `SECRET_KEY` must be set or the app refuses to start

---

## Common tasks

### Add a new page route

1. Add handler in `app/routes/pages.py` (or appropriate router)
2. Create template under `app/templates/`
3. Use `Depends(require_auth)` or stricter dependency
4. Add test in `tests/test_pages.py` or a focused test module

### Add an HTMX mutation

1. Add route in `topics.py`, `sections.py`, or `entries.py`
2. Return a `TemplateResponse` with the appropriate partial
3. Update the calling template's `hx-*` attributes
4. Update FTS on entry changes via `fts_insert` / `fts_update` / `fts_delete` in `indexing.py`
5. Add pytest coverage mirroring sibling routes

### Change session policy defaults

Edit constants in `app/settings.py` and/or expose via admin UI (already wired to `AppSettings`).

---

## Related material

Design history and feature plans live under `_archive/design/` and `cursor_chats/` — useful context but not authoritative; **the code and this document supersede those plans** where they diverge.

The app has grown beyond the original design doc: invitation-only registration, admin suite, guest mode, search/index, session timeouts, and account management were added after the initial spec.
