"""Small, installation-local store. The Flask boundary validates all events."""

from contextlib import closing
import re
import sqlite3
import time


TIMEOUT = 0.025  # seconds; measurements can be dropped when storage is busy
SETTING = "local_telemetry_generation"
GENERATION = re.compile(r"[0-9a-f]{32}")
MAX_ROWS = 20_000
WEEK_MINUTES = 7 * 24 * 60
RETENTION_MINUTES = 30 * 24 * 60
SLOW_MS = 2000
PAGE_SECTIONS = {
    "dashboard": {"dashboard_summary", "dashboard_chart"},
    "ledger": {"ledger_rows"},
}
OUTCOMES = ("ready", "empty", "failed", "unfinished")
ACTIONS = ("save_create", "save_edit", "import_preview", "import_commit")


def is_generation(value):
    return isinstance(value, str) and GENERATION.fullmatch(value) is not None


def parse_batch(body):
    """Return (generation, events) or None. Reject the whole invalid batch."""
    if not isinstance(body, dict) or set(body) != {
            "generation", "page", "viewport", "sections"}:
        return None
    generation = body["generation"]
    page, viewport, sections = body["page"], body["viewport"], body["sections"]
    if (not is_generation(generation) or not isinstance(page, str)
            or page not in PAGE_SECTIONS or viewport not in ("narrow", "wide")
            or not isinstance(sections, list) or len(sections) != len(PAGE_SECTIONS[page])):
        return None
    remaining = PAGE_SECTIONS[page].copy()
    events = []
    for section in sections:
        if not isinstance(section, dict):
            return None
        metric, outcome = section.get("metric"), section.get("outcome")
        if (not isinstance(metric, str) or metric not in remaining
                or outcome not in OUTCOMES
                or (outcome == "empty" and metric == "dashboard_summary")):
            return None
        keys = {"metric", "outcome"}
        duration = None
        if outcome == "ready":
            keys.add("duration_ms")
            duration = section.get("duration_ms")
            if type(duration) is not int or not 0 <= duration <= 30_000:
                return None
        if set(section) != keys:
            return None
        remaining.remove(metric)
        events.append((metric, outcome, None, duration, viewport))
    return generation, events


def current_minute():
    return int(time.time() // 60)


def record(path, events):
    minute = current_minute()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=TIMEOUT)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, minute INTEGER NOT NULL, metric TEXT NOT NULL,
            outcome TEXT NOT NULL, reason TEXT, duration_ms INTEGER, viewport TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS events_minute ON events(minute, id)")
        conn.executemany(
            "INSERT INTO events(minute,metric,outcome,reason,duration_ms,viewport)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ((minute, *event) for event in events))
        conn.execute("DELETE FROM events WHERE minute < ?",
                     (minute - RETENTION_MINUTES + 1,))
        # Look up the oldest row we want to keep in the index. Below the
        # cap the subquery returns no row, so the delete matches nothing.
        conn.execute("""DELETE FROM events WHERE (minute, id) < (
            SELECT minute, id FROM events ORDER BY minute DESC, id DESC
            LIMIT 1 OFFSET ?
        )""", (MAX_ROWS - 1,))


def report(path):
    end = current_minute()
    start = end - WEEK_MINUTES + 1
    sections = {metric: dict.fromkeys((*OUTCOMES, "slow"), 0)
                for metrics in PAGE_SECTIONS.values() for metric in sorted(metrics)}
    actions = {metric: {"total": 0, "outcomes": {}} for metric in ACTIONS}
    data = dict(window_start=start, window_end=end, first_event_minute=None,
                sections=sections, actions=actions, recent_slow_chart=[])
    try:
        path.stat()
    except FileNotFoundError:
        return data
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True,
                                 timeout=TIMEOUT)) as conn:
        conn.execute("BEGIN")  # one snapshot across the report's queries
        data["first_event_minute"] = conn.execute(
            "SELECT MIN(minute) FROM events WHERE minute BETWEEN ? AND ?",
            (start, end)).fetchone()[0]
        for metric, outcome, reason, count, slow in conn.execute("""
            SELECT metric, outcome, reason, COUNT(*),
                   SUM(CASE WHEN duration_ms > ? THEN 1 ELSE 0 END)
            FROM events WHERE minute BETWEEN ? AND ?
            GROUP BY metric, outcome, reason
        """, (SLOW_MS, start, end)):
            if metric in sections:
                sections[metric][outcome] += count
                sections[metric]["slow"] += slow
            elif metric in actions:
                actions[metric]["total"] += count
                actions[metric]["outcomes"].setdefault(outcome, {})[reason or "none"] = count
        data["recent_slow_chart"] = [
            dict(minute=minute, duration_ms=duration, viewport=viewport)
            for minute, duration, viewport in conn.execute("""
                SELECT minute, duration_ms, viewport FROM events
                WHERE minute BETWEEN ? AND ? AND metric = 'dashboard_chart'
                      AND outcome = 'ready' AND duration_ms > ?
                ORDER BY minute DESC, id DESC LIMIT 5
            """, (start, end, SLOW_MS))]
    return data
