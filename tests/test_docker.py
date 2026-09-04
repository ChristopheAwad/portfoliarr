# tests/test_docker.py
# =====================
# Meta-tests for the container/CI configuration files (Dockerfile,
# .dockerignore, .github/workflows/docker.yml, docker-compose.yml).
#
# WHY "META" TESTS?  Docker is not installed on the dev machine, so we
# can't build or run the image here. What we CAN prove locally is that the
# config files agree with the CONTRACTS we designed — the same trick
# test_routes.py uses for server-rendered HTML: read the artifact as text
# and assert on it. The dangerous failure modes are OMISSIONS (the dev
# server's debugger shipped to prod, the SQLite ledger baked into an
# image, a broken main building anyway), so every important rule is
# asserted in BOTH directions: the right thing present, the wrong thing
# absent.
#
# WHAT THESE TESTS CANNOT PROVE: that the image actually builds or serves.
# That's the first green GitHub Actions run (the workflow itself is the
# runtime test), and later the server's first curl.
#
# WHY STRING CHECKS, NOT A YAML PARSER: pyyaml isn't in requirements.txt
# and the prod image shouldn't ship it just for tests. GitHub Actions
# parses the workflow YAML itself — a malformed one fails loudly in CI.
# Indentation-sensitive asserts below are anchored on exact lines, which
# doubles as a basic syntax check.

import re
from pathlib import Path

# Repo root = parent of tests/. Files are read fresh per test-module import;
# these are static config files, not code under test, so module-level reads
# keep each test a one-line assertion with a clear message.
ROOT = Path(__file__).resolve().parent.parent

# GHCR requires lowercase image paths. The repo is ChristopheAwad/portfoliarr,
# so the image is ghcr.io/christopheawad/portfoliarr.
IMAGE = "ghcr.io/christopheawad/portfoliarr"


def _read(filename: str) -> str:
    """Read a config file from the repo root, failing loudly if missing.

    FileNotFoundError would surface as an error rather than a tidy
    assertion failure, so check first and assert with a message that says
    what to create.
    """
    path = ROOT / filename
    assert path.exists(), f"{filename} is missing — create it at the repo root"
    return path.read_text()


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------

def test_dockerfile_uses_python_314_slim():
    """Pin the base to python:3.14-slim — the version the dev venv runs.

    A bare `python:latest` would silently bump Python versions on rebuild,
    and non-slim images carry ~200MB of build tooling this app never uses.
    """
    dockerfile = _read("Dockerfile")
    assert "FROM python:3.14-slim" in dockerfile, (
        "Dockerfile must pin FROM python:3.14-slim"
    )


def test_dockerfile_runs_gunicorn_not_dev_server():
    """The container's CMD must be gunicorn, never app.py's dev server.

    `python app.py` starts Flask's dev server with debug=True — its
    interactive debugger lets anyone who can reach the port execute
    arbitrary code. Gunicorn (the production WSGI server) imports the same
    `app` object from app.py via `app:app`; the __main__ guard keeps the
    dev server available for local dev only.
    """
    dockerfile = _read("Dockerfile")
    assert "CMD" in dockerfile, "Dockerfile has no CMD"
    # exec-form JSON array (["gunicorn", ...]) — the shell-free form that
    # lets signals (SIGTERM on `docker stop`) reach gunicorn directly.
    assert 'CMD ["gunicorn"' in dockerfile, (
        "CMD must be exec-form gunicorn, not `python app.py`"
    )
    assert '"app:app"' in dockerfile, "gunicorn must load the app as app:app"
    assert '"0.0.0.0:5000"' in dockerfile, (
        "gunicorn must bind 0.0.0.0:5000 — 127.0.0.1 would only be "
        "reachable inside the container"
    )
    # The absence guard that matters most: no debug flag may ship.
    assert "debug=True" not in dockerfile, (
        "debug=True must never appear in the image — RCE via debugger"
    )


def test_dockerfile_runs_as_non_root():
    """The app must run as a non-root user.

    Containers running as root make container escapes more damaging and
    can't write to root-owned volumes safely. The USER directive must come
    AFTER the install/copy/chown steps (anything after it runs as that
    user, so the setup work needs root first).
    """
    dockerfile = _read("Dockerfile")
    user_lines = [
        line for line in dockerfile.splitlines()
        if line.startswith("USER")
    ]
    assert user_lines, "Dockerfile never switches to a non-root USER"
    last_user = user_lines[-1].split()
    assert len(last_user) >= 2 and last_user[1] not in ("root", "0"), (
        "final USER must be a non-root user"
    )
    # The last USER wins at runtime — make sure nothing resets it to root.
    assert dockerfile.rstrip().splitlines()[-1].startswith("CMD"), (
        "CMD must be the last instruction so the final USER stays in effect"
    )


def test_dockerfile_precreates_instance_dir():
    """/app/instance must exist and be owned by the app user BEFORE USER.

    WHY: docker-compose mounts a named volume over /app/instance. On first
    use Docker seeds the volume's ownership from the image's directory —
    but only if the directory actually exists in the image. Pre-creating
    it (and chowning to the app user) makes that inheritance
    deterministic; skipping it means SQLite can't write its ledger file.
    """
    dockerfile = _read("Dockerfile")
    assert "mkdir -p /app/instance" in dockerfile, (
        "Dockerfile must pre-create /app/instance for the volume to inherit "
        "correct ownership"
    )
    assert "chown" in dockerfile, (
        "instance dir must be chowned to the non-root user"
    )


def test_dockerfile_exposes_5000():
    """EXPOSE 5000 documents the container's listening port."""
    dockerfile = _read("Dockerfile")
    assert "EXPOSE 5000" in dockerfile


# ---------------------------------------------------------------------------
# .dockerignore — the build context must be code only
# ---------------------------------------------------------------------------

def test_dockerignore_excludes_sqlite_data():
    """The transaction ledger must never be baked into an image.

    `instance/` holds the dev SQLite DB with real transactions. Images get
    pushed to a PUBLIC registry — a baked-in DB would leak the ledger. The
    server's DB starts empty (db.init() creates the schema) and lives in a
    Docker volume, never in an image layer.
    """
    dockerignore = _read(".dockerignore")
    assert "instance/" in dockerignore, ".dockerignore must exclude instance/"
    assert "*.db" in dockerignore, ".dockerignore must exclude *.db"


def test_dockerignore_excludes_dev_files():
    """Dev-only baggage must stay out of the build context.

    .venv/ is hundreds of MB of the WRONG platform's packages (Linux image,
    local venv), .git/ bloats the context and leaks history, tests/ and
    __pycache__/ are useless at runtime.
    """
    dockerignore = _read(".dockerignore")
    for entry in (".venv/", "venv/", ".git", "__pycache__/", "tests/"):
        assert entry in dockerignore, f".dockerignore must exclude {entry}"


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------

def test_requirements_includes_gunicorn():
    """gunicorn must be a pinned dependency — the image's CMD needs it.

    Pinned like every other line in this file (==), so the image builds
    reproducibly instead of drifting with each rebuild.
    """
    requirements = _read("requirements.txt")
    lines = [line.strip() for line in requirements.splitlines() if line.strip()]
    gunicorn_lines = [line for line in lines if line.startswith("gunicorn")]
    assert gunicorn_lines, "requirements.txt must include gunicorn"
    assert "==" in gunicorn_lines[0], (
        "gunicorn must be version-pinned (gunicorn==X.Y.Z)"
    )


# ---------------------------------------------------------------------------
# CI workflow (.github/workflows/docker.yml)
# ---------------------------------------------------------------------------

def test_workflow_triggers_on_push_to_main():
    """The image must rebuild every time main moves — that's the feature.

    workflow_dispatch is also allowed (manual runs), but a push filter on
    main is the contract.
    """
    workflow = _read(".github/workflows/docker.yml")
    assert "push:" in workflow, "workflow must have a push trigger"
    assert "branches:" in workflow and "main" in workflow, (
        "push trigger must be filtered to the main branch"
    )


def test_workflow_runs_tests_before_build():
    """The build job must be gated on a green test job.

    The whole point of publishing on main is that main is trustworthy — so
    the full pytest suite runs first, and the build job declares
    `needs: test` so GitHub Actions skips it entirely when tests fail.
    A red main must NEVER produce an image that lands on the server.
    """
    workflow = _read(".github/workflows/docker.yml")
    assert "python -m pytest" in workflow, (
        "test job must run the full suite"
    )
    needs_lines = [line for line in workflow.splitlines() if "needs:" in line]
    assert any("test" in line for line in needs_lines), (
        "build job must declare needs: test"
    )


def test_workflow_pushes_to_ghcr():
    """The image lands on ghcr.io/christopheawad/portfoliarr.

    Two contracts in one: the right registry path (lowercase — GHCR
    rejects mixed case), and `packages: write` so the built-in GITHUB_TOKEN
    is allowed to push (that's why no registry secrets are needed at all).
    """
    workflow = _read(".github/workflows/docker.yml")
    assert IMAGE in workflow, f"workflow must push to {IMAGE}"
    assert "packages: write" in workflow, (
        "workflow needs packages: write permission to push to GHCR"
    )


def test_workflow_tags_latest_and_sha():
    """Every push tags :latest (what the server pulls) and :<sha>.

    latest = convenient moving pointer; the SHA tag = an immutable record
    of exactly what a given server was running at any point in time.
    """
    workflow = _read(".github/workflows/docker.yml")
    assert f"{IMAGE}:latest" in workflow, "missing :latest tag"
    assert "github.sha" in workflow, "missing the git-SHA tag"


# ---------------------------------------------------------------------------
# docker-compose.yml — the server stack
# ---------------------------------------------------------------------------

def test_compose_uses_published_image_not_local_build():
    """The server pulls the published image; it never builds locally.

    A `build:` key would make `docker compose up` compile code checked out
    on the server — bypassing CI's test gate entirely. The image key is
    the whole deal.
    """
    compose = _read("docker-compose.yml")
    assert f"image: {IMAGE}" in compose, (
        "compose must reference the published GHCR image"
    )
    assert "build:" not in compose, (
        "compose must not build locally — that would skip the CI test gate"
    )


def test_compose_maps_host_port_9967():
    """The app is reachable on the server at http://<server>:9967."""
    compose = _read("docker-compose.yml")
    assert '"9967:5000"' in compose, "compose must map 9967:5000"


def test_compose_mounts_persistent_volume():
    """The SQLite ledger must survive every image update.

    A container's filesystem is thrown away when its image is replaced —
    without a volume, every `docker compose up` after an update would wipe
    the transactions. The named volume `portfoliarr-data` is mounted over
    /app/instance (where db.py puts portfolio.db) and must also be
    DECLARED as a top-level volume so Docker creates it.
    """
    compose = _read("docker-compose.yml")
    assert "portfoliarr-data:/app/instance" in compose, (
        "compose must mount portfoliarr-data over /app/instance"
    )
    # The mount line alone would satisfy a substring check, so require the
    # actual top-level declaration: a line that is exactly
    # `  portfoliarr-data:` (two-space indent under the top-level
    # `volumes:` key, no dash). Without it Docker never creates the volume.
    assert re.search(r"(?m)^  portfoliarr-data:\s*$", compose), (
        "the named volume must be declared under the top-level volumes: key"
    )


def test_compose_sets_timezone():
    """The container must run in the user's timezone, not UTC.

    app.py uses date.today() (e.g. labelling today's chart bar). A UTC
    container flips "today" several hours early/late relative to
    America/Toronto — the TZ env var fixes every date/time call at once.
    """
    compose = _read("docker-compose.yml")
    assert "TZ" in compose and "America/Toronto" in compose, (
        "compose must set TZ=America/Toronto"
    )


def test_compose_restarts_on_boot():
    """The container must come back after a server reboot or a crash —
    `restart: unless-stopped`, which also stays stopped if the USER
    deliberately stopped it (unlike `always`)."""
    compose = _read("docker-compose.yml")
    assert "restart: unless-stopped" in compose
