#!/bin/sh
# docker-entrypoint.sh — boot as root, repair, drop privileges, serve.
# =====================================================================
# WHY ROOT AT ALL? The SQLite ledger lives in a Docker volume mounted at
# /app/instance. Named volumes do NOT reliably inherit ownership from the
# image's directory: rootless Docker, the containerd image store, and NAS
# docker UIs are known to hand the mount back ROOT-owned. The app runs as
# `appuser` (uid 1000) and could not create portfolio.db there — the
# crash-loop this script exists to prevent.
#
# So root gets exactly two jobs, then immediate handoff (the same pattern
# the official postgres/redis images use):
#   1. chown the data directory — idempotent and cheap, the ledger is tiny
#   2. fix HOME — gosu inherits root's environment, and yfinance caches
#      cookies/quotes under $HOME, which would otherwise point at /root
#   3. `exec gosu appuser "$@"` — REPLACE this root shell with the CMD
#      (gunicorn) running as appuser. Root never serves a request; PID 1
#      becomes the unprivileged server, so `docker stop` signals reach it.
set -e

chown -R appuser:appuser /app/instance
export HOME=/home/appuser

exec gosu appuser "$@"
