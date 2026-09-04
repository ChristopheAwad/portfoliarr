# Feature: Containerize + auto-publish image to GHCR on main

## What & why

Package the app as a Docker image so it can run on the home server, and have
GitHub Actions rebuild/publish that image to GHCR every time `main` moves.
The server decides WHEN to adopt updates (manual `docker compose pull &&
docker compose up -d`) — CI's job ends at "GHCR always reflects latest main".

**Design decisions (already agreed with user):**

- **No Watchtower / no auto-deploy.** Updates on the server are deliberate.
- **Repo + GHCR package go public** — server pulls anonymously, no registry
  login anywhere. User flips repo visibility via `gh` (with final confirm);
  the package is flipped to Public once, after the first CI push (GHCR
  creates the first pushed package private regardless of repo visibility).
- **Server port 9967** → compose maps `9967:5000`.
- **SQLite never leaves the machine.** `instance/` is already gitignored
  (verified: no `.db` tracked) and will be in `.dockerignore` — test data
  can't reach GitHub or the image. The server DB starts empty (`db.init()`
  creates the schema on first run) and lives in a named Docker volume.
- **Docker is NOT installed on this dev machine** — the first real image
  build happens in CI. Local proof = these meta-tests; runtime proof =
  the first green Actions run.

## Files

| File | Role |
|---|---|
| `Dockerfile` | `python:3.14-slim` (matches the dev venv). Copies code, installs deps, runs **gunicorn** as a **non-root user**. `app.py` is untouched — `if __name__ == "__main__"` keeps the dev server for local dev; gunicorn imports `app:app`. |
| `.dockerignore` | Build context stays code-only: no `instance/`, `*.db`, `.venv/`, `.git`, `tests/`, `__pycache__/`, docs, or CI files. |
| `.github/workflows/docker.yml` | Job 1 **test**: Python 3.14, `pip install -r requirements.txt`, `python -m pytest`. Job 2 **build-and-push**: `needs: test` (a red main never builds), logs into ghcr.io with the built-in `GITHUB_TOKEN` (`permissions: packages: write`), pushes `ghcr.io/christopheawad/portfoliarr:latest` + `:<full-sha>`, GHA layer cache. Also `workflow_dispatch` for manual runs. |
| `docker-compose.yml` | Server stack, app only: published image, `9967:5000`, named volume `portfoliarr-data:/app/instance` (ledger survives every image swap), `TZ=America/Toronto` (`app.py` uses `date.today()` — UTC container would flip "today" hours early), `restart: unless-stopped`. |
| `requirements.txt` | + `gunicorn==23.0.0`. |

**Key choices, for the record:**

- **1 gunicorn worker + 8 threads.** Threads, not processes: the in-memory
  quote cache (`market_data.py`) and SQLite both want a single process, and
  a single-user app doesn't need more.
- **Named volume over `/app/instance`** (not a bind mount): `db.py` builds
  `DB_PATH` from its own file's location → `/app/instance/portfolio.db` in
  the container; Docker copies the image's directory ownership into a named
  volume on first use, so the non-root user keeps write access. Zero code
  changes; the Dockerfile pre-creates and chowns the dir to make that
  inheritance deterministic.
- **Image tags**: `latest` (what compose pulls) + full git SHA (any release
  is reproducible/pinnable forever).

## Test plan (pytest — meta-tests over the config files)

Docker can't run here, so the suite locks the *configuration contract* the
same way `tests/test_routes.py` locks server-rendered HTML: read the files
as text from the repo root, assert presence AND absence (the dangerous
omissions are the real failure paths). No new dependencies (no pyyaml —
plain string checks; GitHub Actions itself parses the workflow YAML and a
malformed one fails visibly in CI).

`tests/test_docker.py`:

1. **Dockerfile**
   - existence is checked by every test via the `_read` helper (loud,
     message-carrying failure if a file is missing)
   - `test_dockerfile_uses_python_314_slim` — `FROM python:3.14-slim`
   - `test_dockerfile_runs_gunicorn_not_dev_server` — CMD is a gunicorn
     exec-form entry binding `0.0.0.0:5000` running `app:app`; **absence**
     guard: no `debug=True` anywhere (the interactive debugger is an RCE
     hole if shipped).
   - `test_dockerfile_runs_as_non_root` — a `USER` directive names a
     non-root user, declared AFTER the install/copy steps.
   - `test_dockerfile_precreates_instance_dir` — `mkdir -p /app/instance`
     + chown before `USER` (deterministic volume ownership).
   - `test_dockerfile_exposes_5000` — `EXPOSE 5000`.
2. **.dockerignore**
   - `test_dockerignore_excludes_sqlite_data` — `instance/` AND `*.db`
     (the never-sync-the-ledger rule, image edition).
   - `test_dockerignore_excludes_dev_files` — `.venv/`, `.git`,
     `__pycache__/`, `tests/`.
3. **requirements.txt** — `test_requirements_includes_gunicorn`.
4. **CI workflow**
   - `test_workflow_triggers_on_push_to_main` — `push:` with
     `branches: [main]` (the "every time we update main" requirement).
   - `test_workflow_runs_tests_before_build` — a pytest step exists AND the
     build job carries `needs: test`.
   - `test_workflow_pushes_to_ghcr` — image path
     `ghcr.io/christopheawad/portfoliarr` (lowercase — GHCR requires it) +
     `packages: write` permission.
   - `test_workflow_tags_latest_and_sha`.
5. **docker-compose.yml**
   - `test_compose_uses_published_image_not_local_build` —
     `image: ghcr.io/...` present; **absence** guard: no `build:` key
     (the server pulls, it never builds).
   - `test_compose_maps_host_port_9967`.
   - `test_compose_mounts_persistent_volume` —
     `portfoliarr-data:/app/instance` + the named volume declared.
   - `test_compose_sets_timezone` — `TZ=America/Toronto`.
   - `test_compose_restarts_on_boot` — `restart: unless-stopped`.

**Honest limit:** these prove the files agree with the contract. They cannot
prove the image builds or serves — that's CI's first green run (and then the
server's first `curl http://localhost:9967/`).

## Implementation steps

1. `tests/test_docker.py` — write first, confirm it FAILS (files absent).
2. `Dockerfile`, `.dockerignore`, `.github/workflows/docker.yml`,
   `docker-compose.yml`, `requirements.txt` + gunicorn.
3. Full `python -m pytest` green (new + all existing).

## Verification & gates

1. Full suite green locally.
2. Commit/push gate (explicit user approval) → watch the Actions run go
   green at github.com/ChristopheAwad/portfoliarr/actions — that IS the
   GUI gate for this feature (no browser UI changed; the "app" we're
   checking is the pipeline).
3. After first push: flip the `portfoliarr` GHCR package to Public (one
   click; optionally "inherit visibility") → flip repo public via `gh`
   (final confirm) → server: copy `docker-compose.yml`, `docker compose
   pull && docker compose up -d`, `curl http://localhost:9967/`.
