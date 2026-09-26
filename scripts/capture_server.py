"""Throwaway capture server: the whole Flask app on :5001 backed by a
TEMP database in a fresh temp directory.

Does NOT touch the dev server or the real ledger: `db.DB_PATH` is
redirected BEFORE `app` is imported, so the import-time `db.init()` and
every later write land in the throwaway file. Zero users exist, so the
server boots in real setup mode — the same starting point the webforms
expect. Run it in the background, run scripts/capture_shots.py against
it, kill it when done:

    source .venv/bin/activate          # app deps live here
    python scripts/capture_server.py & # prints THROWAWAY-DATA: <dir>
    /usr/bin/python3 scripts/capture_shots.py --out /tmp/opencode/shots
    kill <pid>                         # or: pkill -f capture_server
"""

import os
import sys
import tempfile
from pathlib import Path

# Run from anywhere; the repo root is this file's grandparent.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="portfoliarr-shots-"))

os.environ.setdefault("TZ", "America/Toronto")

# Redirect FIRST: db._connect() reads DB_PATH at call time, and app.py
# runs db.init() at import — against the already-redirected path.
import db  # noqa: E402

db.DB_PATH = TMP / "capture.db"
db.init()

import app as app_module  # noqa: E402

print("THROWAWAY-DATA:", TMP)

app_module.app.run(debug=False, port=5001)
