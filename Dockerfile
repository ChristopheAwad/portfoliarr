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

# gosu: the entrypoint's "drop privileges" tool. The container BOOTS as
# root for one job (repair the data volume's ownership — see
# docker-entrypoint.sh), then gosu execs the app as `appuser`. Kept in its
# own layer BEFORE the code copy, so code changes never re-run apt.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

# Now the app code itself. .dockerignore is the bouncer here: it keeps
# instance/ (the SQLite ledger!), .venv/, .git/, tests/ and friends out of
# the build context, so `COPY . .` is safe — and future new modules are
# picked up automatically without editing this file.
COPY . .

# The app runs as `appuser`, NOT root (a root server process makes any
# container escape far more damaging). useradd --create-home gives a real
# HOME for the yfinance cache/cookies; mkdir pre-creates the SQLite data
# dir inside the image.
#
# WHY THE CONTAINER STILL BOOTS AS ROOT: docker-compose mounts a NAMED
# VOLUME over /app/instance, and the volume's ownership is NOT reliably
# inherited from the image's directory — rootless Docker, the containerd
# image store, and NAS docker UIs are known to hand back a ROOT-owned
# mount, which crash-looped the very first deployment (SQLite couldn't
# create its file). The ENTRYPOINT below boots as root just long enough
# to chown the volume, then execs the CMD as appuser. Root never serves a
# request. (Same pattern as the official postgres/redis images.)
RUN useradd --create-home appuser \
    && mkdir -p /app/instance \
    && chown -R appuser:appuser /app /home/appuser

# The boot sequence: entrypoint (repair + drop privileges) -> CMD.
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Document the listening port (compose maps host 9967 -> this).
EXPOSE 5000

# ONE worker + threads, not many workers: the in-memory quote cache in
# market_data.py (TTL 120s) and SQLite both want a single process, and a
# single-user app scales plenty on threads. Binding 0.0.0.0 (not
# 127.0.0.1) is what makes the port reachable outside the container.
# Exec-form (JSON array) so signals like SIGTERM from `docker stop` reach
# gunicorn directly instead of via a shell.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "app:app"]
