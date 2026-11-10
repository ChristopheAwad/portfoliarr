"""Throwaway performance-measurement server on an inherited socket.

The companion driver `scripts/measure_perf.py` binds a free loopback
port, passes the listening socket to this child, and waits for the child
to print `PERF-READY <token>`. That handshake makes it impossible to seed
or mutate a different process that happens to own the port: the parent
never connects before the token matches.

Safety rules, same spirit as capture_server.py:

- `db.DB_PATH` is redirected BEFORE `app` is imported, so the import-time
  `db.init()` and every later write land in a throwaway file. The real
  `instance/` ledger is never touched.
- `PERF_DB_PATH` may point at a database the parent already seeded, so a
  cold run can restart this process while keeping the same disposable
  data and session secret.
- Without `PERF_LISTEN_FD` the child falls back to Flask's development
  server on `PERF_PORT` (useful for manual runs).

Run with the VENV python (Flask lives there):
    .venv/bin/python scripts/perf_server.py

Environment:
    PERF_LISTEN_FD       inherited listening socket FD (driver mode)
    PERF_PORT            fallback dev-server port (default 5002)
    PERF_DB_PATH         disposable database path (default: new temp dir)
    PERF_READY_TOKEN     token printed once the server can accept requests
    PERF_STUB_YAHOO_MS   positive integer: replace market calls with a
                         fixed-latency deterministic fake. This patches
                         app.py's imported functions, NOT market_data.yf,
                         so real process caches are bypassed. Stub-mode
                         cache rows are empty by design.
"""

import os
import sys
import tempfile
from pathlib import Path

# Run from anywhere; the repo root is this file's grandparent, and this
# file's own directory makes `import perf_stub` work under `-m` too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TMP = Path(tempfile.mkdtemp(prefix="portfoliarr-perf-"))
DB_PATH = Path(os.environ.get("PERF_DB_PATH") or (TMP / "perf.db"))

os.environ.setdefault("TZ", "America/Toronto")

# Redirect FIRST: db._connect() reads DB_PATH at call time, and app.py
# runs db.init() at import — against the already-redirected path.
import db  # noqa: E402

db.DB_PATH = DB_PATH
db.init()

import app as app_module  # noqa: E402
import perf_stub  # noqa: E402


STUB_MS = int(os.environ.get("PERF_STUB_YAHOO_MS", "0") or "0")
STUB_EMPTY_STOCK = os.environ.get("PERF_STUB_EMPTY_STOCK") == "1"
if STUB_MS > 0:
    perf_stub.install_yahoo_stub(app_module, STUB_MS,
                                 empty_stock=STUB_EMPTY_STOCK)

TOKEN = os.environ.get("PERF_READY_TOKEN", "")
LISTEN_FD = os.environ.get("PERF_LISTEN_FD")

print("THROWAWAY-DATA:", TMP, flush=True)
print("PERF-DB:", DB_PATH, flush=True)
print("PERF-STUB-YAHOO-MS:", STUB_MS, flush=True)
print("PERF-STUB-EMPTY-STOCK:", STUB_EMPTY_STOCK, flush=True)

if LISTEN_FD:
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app_module.app,
                         threaded=True, fd=int(LISTEN_FD))
    print(f"PERF-READY {TOKEN}", flush=True)
    server.serve_forever()
else:
    PORT = int(os.environ.get("PERF_PORT", "5002"))
    print(f"PERF-READY {TOKEN}", flush=True)
    app_module.app.run(debug=False, port=PORT)
