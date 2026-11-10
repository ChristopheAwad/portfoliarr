"""Throwaway performance-measurement server: the whole Flask app on :5002
backed by a TEMP database in a fresh temp directory.

Same safety rule as capture_server.py: `db.DB_PATH` is redirected BEFORE
`app` is imported, so the import-time `db.init()` and every later write
land in the throwaway file — the real instance/ ledger is never touched.

Run with the VENV python (Flask lives there):
    .venv/bin/python scripts/perf_server.py

Environment:
    PERF_PORT            listen port (default 5002)
    PERF_STUB_YAHOO_MS   when set to a positive integer, replace every
                         market-data network call with a fixed-latency
                         deterministic fake. This removes Yahoo's network
                         variance so app-level changes (extra calls,
                         parallelism, caching) are what the numbers show.
                         Unset: live Yahoo, the real user experience.

                         The fake patches app.py's imported market
                         functions, NOT market_data.yf, so it bypasses the
                         real process caches. In stub mode the market
                         hit/miss rows are empty by design: use live mode
                         or the unit tests to judge cache behaviour.

The companion driver is scripts/measure_perf.py (SYSTEM python).
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

os.environ.setdefault("TZ", "America/Toronto")

# Redirect FIRST: db._connect() reads DB_PATH at call time, and app.py
# runs db.init() at import — against the already-redirected path.
import db  # noqa: E402

db.DB_PATH = TMP / "perf.db"
db.init()

import app as app_module  # noqa: E402
import perf_stub  # noqa: E402


STUB_MS = int(os.environ.get("PERF_STUB_YAHOO_MS", "0") or "0")
STUB_EMPTY_STOCK = os.environ.get("PERF_STUB_EMPTY_STOCK") == "1"
if STUB_MS > 0:
    perf_stub.install_yahoo_stub(app_module, STUB_MS,
                                 empty_stock=STUB_EMPTY_STOCK)

PORT = int(os.environ.get("PERF_PORT", "5002"))

print("THROWAWAY-DATA:", TMP)
print("PERF-STUB-YAHOO-MS:", STUB_MS)
print("PERF-STUB-EMPTY-STOCK:", STUB_EMPTY_STOCK)

app_module.app.run(debug=False, port=PORT)
