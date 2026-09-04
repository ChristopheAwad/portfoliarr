# Dockerfile — production image for the portfolio tracker
# ========================================================
# The dev machine runs `python app.py` (Flask's dev server + interactive
# debugger — fine on localhost, dangerous if exposed). The image instead
# runs GUNICORN, a production WSGI server, which imports the very same
# Flask object from app.py (`app:app` = "module app, variable app").
# app.py needs no changes: its `if __name__ == "__main__"` guard keeps the
# dev server for local development only, because gunicorn imports the
# module without ever "running it as main".

FROM python:3.14-slim

# PYTHONDONTWRITEBYTECODE: no .pyc files (immutable image, smaller).
# PYTHONUNBUFFERED: print/log calls stream to `docker logs` immediately
#   instead of sitting in a buffer.
# PIP_DISABLE_PIP_VERSION_CHECK: one less network round-trip at install.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy ONLY requirements first, then install. Docker layers are cached:
# as long as requirements.txt is unchanged, rebuilds skip the (slow,
# pandas/numpy-heavy) pip install and only re-run the COPY of the code.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Now the app code itself. .dockerignore is the bouncer here: it keeps
# instance/ (the SQLite ledger!), .venv/, .git/, tests/ and friends out of
# the build context, so `COPY . .` is safe — and future new modules are
# picked up automatically without editing this file.
COPY . .

# Run as a non-root user (a root process in a container makes any escape
# more damaging). Two setup jobs need root, done before switching:
#   1. useradd --create-home: a real HOME for the yfinance cache/cookies.
#   2. mkdir /app/instance + chown: docker-compose mounts a NAMED VOLUME
#      over this directory; on first use Docker seeds the volume's
#      ownership from the image's directory — but only if the directory
#      exists. Pre-creating it owned by appuser makes that inheritance
#      deterministic, so SQLite can write its ledger file on day one.
RUN useradd --create-home appuser \
    && mkdir -p /app/instance \
    && chown -R appuser:appuser /app /home/appuser
USER appuser

# Document the listening port (compose maps host 9967 -> this).
EXPOSE 5000

# ONE worker + threads, not many workers: the in-memory quote cache in
# market_data.py (TTL 120s) and SQLite both want a single process, and a
# single-user app scales plenty on threads. Binding 0.0.0.0 (not
# 127.0.0.1) is what makes the port reachable outside the container.
# Exec-form (JSON array) so signals like SIGTERM from `docker stop` reach
# gunicorn directly instead of via a shell.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "app:app"]
