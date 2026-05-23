# Deployment (Fly.io)

Developer Memory Garden deploys as a Docker container on [Fly.io](https://fly.io) with a persistent volume for the SQLite database.

| Item | Value |
|------|-------|
| Fly app name | `developer-memory-garden` |
| Region | `sjc` (see `fly.toml`) |
| Internal port | `8080` |
| Volume name | `notebook_data` |
| Volume mount | `/data` |
| Database file | `/data/notebook.db` |
| Public URL | `https://developer-memory-garden.fly.dev` |

Configuration files: `Dockerfile`, `fly.toml`.

### How the container runs

The image installs dependencies at **build time** with `uv sync` (see `Dockerfile`). At runtime it starts uvicorn from the project virtualenv (`.venv/bin/uvicorn`), not `uv run`. That avoids `uv` trying to write a cache under the system user’s home directory (`/nonexistent`), which crashes the container on Fly.

The app runs as non-root user `appuser`. Fly mounts the volume at `/data` with uid/gid matching that user.

Fly’s HTTP health check calls `GET /health`, which returns **200** and bypasses `TrustedHostMiddleware` so internal probes (which use hosts like `127.0.0.1:8080`) do not fail. HTTPS is enforced at the Fly edge (`force_https = true` in `fly.toml`), not in the app — the container sees plain HTTP from Fly’s proxy, so an in-app HTTPS redirect would loop. User traffic still uses `ALLOWED_HOSTS` when that secret is set.

---

## Prerequisites

1. A [Fly.io account](https://fly.io/app/sign-up)
2. The [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/) installed (`fly version`)
3. Logged in: `fly auth login`

---

## First-time setup

Skip steps you have already completed (for example, if the app and volume already exist).

### 1. Create the app (new projects only)

From the project root:

```bash
fly launch --no-deploy
```

If the app name `developer-memory-garden` is taken, choose another name and update `app = "…"` in `fly.toml` everywhere it is referenced (including backup scripts).

`fly launch` may offer to copy settings from `fly.toml` — accept the existing config when prompted.

### 2. Create the persistent volume

The database must live on a Fly volume so it survives redeploys:

```bash
fly volumes create notebook_data --region sjc --size 1
```

`fly.toml` already declares this mount:

```toml
[mounts]
  source = "notebook_data"
  destination = "/data"
```

Each machine needs its own volume in the same region. For a single-machine app (current config), one volume is enough.

### 3. Set secrets

Secrets are environment variables stored encrypted by Fly. Setting or changing a secret triggers an automatic redeploy.

#### Generate a session signing key

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Save the output somewhere safe. It becomes `SECRET_KEY`.

#### Required secrets

Set these **before** the first successful production boot (or the app will crash on startup because `APP_ENV=production` requires `SECRET_KEY`):

```bash
fly secrets set \
  SECRET_KEY='paste-your-generated-key-here' \
  DATABASE_URL='sqlite:////data/notebook.db' \
  SECURE_COOKIES='true'
```

| Secret | Why |
|--------|-----|
| `SECRET_KEY` | Signs session and CSRF cookies. **Mandatory** in production. |
| `DATABASE_URL` | Points SQLite at the mounted volume (`//data` = absolute path `/data`). |
| `SECURE_COOKIES` | Sets the `Secure` flag on cookies. Fly terminates HTTPS at the edge. |

Note the four slashes in `sqlite:////data/notebook.db`: SQLAlchemy expects an absolute filesystem path on the volume.

#### Bootstrap admin (first login)

Set both together so startup creates or promotes an admin account:

```bash
fly secrets set \
  ADMIN_USERNAME='your-admin-name' \
  ADMIN_PASSWORD='your-strong-password-here'
```

Password rules (enforced at bootstrap): at least 8 characters, not in the common-password list.

After deploy, log in at `/login`, then open `/admin` to create invitation links for other users.

If the username already exists, that account is **promoted** to admin without changing its password.

#### Host allowlist (recommended)

Restrict which `Host` headers the app accepts:

```bash
fly secrets set ALLOWED_HOSTS='developer-memory-garden.fly.dev'
```

Add custom domains comma-separated:

```bash
fly secrets set ALLOWED_HOSTS='developer-memory-garden.fly.dev,notebook.example.com'
```

If `ALLOWED_HOSTS` is unset, all hosts are allowed (works but is less strict).

#### Optional secrets

```bash
# Read-only guest account username (default: __guest__)
fly secrets set GUEST_USERNAME='guest'

# Logging (default: INFO)
fly secrets set LOG_LEVEL='INFO'
```

### 4. Deploy

```bash
fly deploy
```

Watch logs during first boot:

```bash
fly logs
```

You should see database initialization and optional bootstrap messages (`Bootstrap admin user created`, starter catalog seed, guest account).

### 5. Verify

```bash
fly status
fly checks list
```

Open `https://developer-memory-garden.fly.dev/login` (or your app hostname).

In logs you should see uvicorn listening on port `8080` and messages such as `Database tables ensured`. `fly checks list` should show `servicecheck-00-http-8080` passing against `/health`.

---

## Managing secrets later

### List secret names (not values)

```bash
fly secrets list
```

### Update one or more secrets

```bash
fly secrets set SECRET_KEY='new-key-here'
```

**Warning:** Changing `SECRET_KEY` invalidates every existing session cookie immediately. Users must log in again.

### Rotate admin password

Either:

- Use **Admin → reset password** in `/admin` for an existing user, or
- Set new `ADMIN_PASSWORD` only helps for **new** bootstrap users; for an existing admin, change the password through the app or admin UI.

### Remove a secret

```bash
fly secrets unset SOME_VAR
```

---

## Routine deploys

After code changes:

```bash
fly deploy
```

Fly builds the image from `Dockerfile`, rolls out the new release, and keeps the volume attached. User data in SQLite is preserved.

To follow the rollout:

```bash
fly logs
```

---

## Environment: secrets vs `fly.toml`

| Variable | Where to set | Notes |
|----------|--------------|-------|
| `APP_ENV` | `fly.toml` `[env]` | Already `production`. Do not override unless you know why. |
| `SECRET_KEY` | **Secret** | Never commit to git. |
| `DATABASE_URL` | **Secret** | Must use `/data` path on Fly. |
| `SECURE_COOKIES` | **Secret** | `true` for production. |
| `ALLOWED_HOSTS` | **Secret** | Recommended. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | **Secret** | Bootstrap only; optional after admin exists. |
| `GUEST_USERNAME` | Secret (optional) | Default `__guest__`. |
| `LOG_LEVEL` | Secret (optional) | Default `INFO`. |

Non-secret config (machine size, health checks, volume mount) belongs in `fly.toml`.

---

## Custom domain (optional)

```bash
fly certs add notebook.example.com
```

Add the hostname to `ALLOWED_HOSTS`:

```bash
fly secrets set ALLOWED_HOSTS='developer-memory-garden.fly.dev,notebook.example.com'
```

Follow Fly’s DNS instructions from `fly certs show notebook.example.com`.

---

## Backups

Production SQLite lives only on the Fly volume. Back it up regularly.

### Automated script (local machine)

`scripts/backup-notebook.sh` copies:

- Local dev DB → `Dropbox/_backups/dev/`
- Fly production DB via SSH → `Dropbox/_backups/prod/`

Requires `fly` CLI authenticated and `sqlite3` installed. See the script header for launchd scheduling on macOS.

### Manual backup via Fly SSH

```bash
fly ssh console -a developer-memory-garden -C "sqlite3 /data/notebook.db \".backup '/tmp/notebook-backup.db'\""
fly ssh sftp get /tmp/notebook-backup.db ./notebook-$(date +%Y%m%d).db -a developer-memory-garden
```

Verify integrity locally:

```bash
sqlite3 notebook-YYYYMMDD.db "PRAGMA integrity_check;"
```

### Restore (destructive)

Restoring overwrites production data. Stop traffic or scale to one machine, copy the file onto the volume, and restart. Test restores on a staging app first if possible.

---

## Troubleshooting

### App crashes on startup: `SECRET_KEY must be set`

`APP_ENV=production` is set in `fly.toml`. Set `SECRET_KEY` via `fly secrets set` (see above).

### Empty notebook after deploy

`DATABASE_URL` probably points at the container filesystem instead of the volume. It must be:

```
sqlite:////data/notebook.db
```

### 400 Bad Request / invalid host

Set `ALLOWED_HOSTS` to include the hostname you are using in the browser (hostname only — no `https://` or port). This does not affect `GET /health`, which Fly uses for health checks.

Example:

```bash
fly secrets set ALLOWED_HOSTS='developer-memory-garden.fly.dev'
```

### App crashes on startup: `Failed to initialize cache at /nonexistent/.cache/uv`

The container was started with `uv run` while running as the system user `appuser`, whose home directory is `/nonexistent`. `uv` cannot create its cache there and exits immediately (code 2), often after `machine has reached its max restart count of 10`.

The current `Dockerfile` runs `/app/.venv/bin/uvicorn` directly instead. Redeploy after pulling that change:

```bash
fly deploy
```

### Health check failing

Check logs: `fly logs`. The check path is `GET /health` in `fly.toml` (not `/`).

| Log pattern | Likely cause |
|-------------|----------------|
| `SECRET_KEY must be set` | Missing `SECRET_KEY` secret |
| `Failed to initialize cache at /nonexistent/.cache/uv` | Old image still using `uv run`; redeploy with current `Dockerfile` |
| `unable to open database file` | Volume missing or wrong `DATABASE_URL` |
| Continuous `GET /` **400** `Invalid host header` | Browser traffic blocked by `ALLOWED_HOSTS`; fix the secret (see above). Health checks should use `/health`. |
| Uvicorn starts, `/health` not **200** | Redeploy with current app code and `fly.toml` |
| `Main child exited` with no app logs | Process crash before bind; see rows above |

If the machine never stays running, `fly checks list` may show **“the machine hasn’t started”** — fix startup first (secrets, volume, Dockerfile), not the check path.

If first boot is slow on a small VM, increase `grace_period` under `[[http_service.checks]]` in `fly.toml`.

### Browser: `ERR_TOO_MANY_REDIRECTS`

Fly already redirects HTTP to HTTPS (`force_https` in `fly.toml`). Do **not** add Starlette `HTTPSRedirectMiddleware` in the app on Fly — the proxy connects over HTTP internally, so the app would redirect to HTTPS on every request and the browser would loop forever. Production uses HSTS response headers only; TLS termination stays at the edge.

### SSH / backup fails

Confirm the app is running (`fly status`), you are logged in (`fly auth whoami`), and the app name matches `fly.toml`.

---

## Production hardening (automatic)

When `APP_ENV=production`, the app enables:

- HSTS (HTTPS is enforced by Fly’s edge, not an in-app redirect)
- Security headers (CSP, `X-Frame-Options`, etc.)
- OpenAPI docs disabled (`/docs`, `/redoc`)
- Session secret enforcement

See [DEVELOPMENT.md](DEVELOPMENT.md) for application architecture and security notes for developers.
