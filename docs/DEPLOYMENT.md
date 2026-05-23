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

Open `https://developer-memory-garden.fly.dev/login` (or your app hostname). The health check in `fly.toml` hits `GET /`, which redirects unauthenticated users to login — that is expected.

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

Set `ALLOWED_HOSTS` to include the hostname you are using in the browser.

### Health check failing

Check logs: `fly logs`. Common causes: missing secrets, volume not mounted, or app not listening on `8080`.

### SSH / backup fails

Confirm the app is running (`fly status`), you are logged in (`fly auth whoami`), and the app name matches `fly.toml`.

---

## Production hardening (automatic)

When `APP_ENV=production`, the app enables:

- HTTPS redirect and HSTS
- Security headers (CSP, `X-Frame-Options`, etc.)
- OpenAPI docs disabled (`/docs`, `/redoc`)
- Session secret enforcement

See [DEVELOPMENT.md](DEVELOPMENT.md) for application architecture and security notes for developers.
