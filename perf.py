"""Process-memory performance metrics aggregator.

A PURE data layer (no Flask, no logging, no imports from the app's other
modules). `market_data.py` and `db.py` record durations here at their
cache/network boundaries; the route layer (`app.py`) reads `snapshot()`
to serve `/api/perf` and to emit periodic `event=perf_summary` log lines.

Why in memory: the numbers describe THIS process since it started, and
restart loss is accepted — the same policy as the market-data caches.
The durable history is the log line; this store is for on-demand views.

Every metric key is (name, tags). Keys must stay BOUNDED: operation
names, cache outcomes, endpoint names, page names. Never per-symbol
keys — a 500-ticker portfolio would otherwise create 500 rows.

Percentiles come from the last _RING_SIZE samples per key (a recent
window); `count` is lifetime. All access is under one lock.
"""

import math
import threading
import time
from collections import deque

_RING_SIZE = 256
_lock = threading.Lock()
_metrics = {}
_requests = 0
_started_at = time.monotonic()


def _key(name, tags):
    """Return the stable dict key for a metric name + tag set."""
    return (str(name), tuple(sorted((str(k), str(v)) for k, v in tags.items())))


def _percentile(ordered_samples, fraction):
    """Nearest-rank percentile (same value a p50/p95 dashboard shows)."""
    if not ordered_samples:
        return 0.0
    index = math.ceil(fraction * len(ordered_samples)) - 1
    index = max(0, min(len(ordered_samples) - 1, index))
    return ordered_samples[index]


def record(name, duration_ms, **tags):
    """Record one observation, in milliseconds, under name + tags.

    Never raises for ordinary numeric input — a metrics call must not be
    able to break the code path it measures.
    """
    try:
        duration = float(duration_ms)
    except (TypeError, ValueError):
        return
    if duration < 0 or math.isnan(duration):
        duration = 0.0
    key = _key(name, tags)
    with _lock:
        entry = _metrics.get(key)
        if entry is None:
            entry = {
                "count": 0,
                "total_ms": 0.0,
                "max_ms": 0.0,
                "samples": deque(maxlen=_RING_SIZE),
            }
            _metrics[key] = entry
        entry["count"] += 1
        entry["total_ms"] += duration
        if duration > entry["max_ms"]:
            entry["max_ms"] = duration
        entry["samples"].append(duration)


def request_completed():
    """Count one completed request and return the lifetime total."""
    global _requests
    with _lock:
        _requests += 1
        return _requests


def snapshot():
    """Return every metric as JSON-safe rows plus process totals."""
    with _lock:
        rows = [
            {
                "name": name,
                "tags": dict(tags),
                "count": entry["count"],
                "avg_ms": round(entry["total_ms"] / entry["count"], 1),
                "p50_ms": round(_percentile(sorted(entry["samples"]), 0.50), 1),
                "p95_ms": round(_percentile(sorted(entry["samples"]), 0.95), 1),
                "max_ms": round(entry["max_ms"], 1),
                "total_ms": round(entry["total_ms"], 1),
            }
            for (name, tags), entry in _metrics.items()
        ]
        requests_total = _requests
        uptime_s = time.monotonic() - _started_at
    rows.sort(key=lambda row: (row["name"], sorted(row["tags"].items())))
    return {
        "uptime_s": round(uptime_s, 1),
        "requests_total": requests_total,
        "metrics": rows,
    }


def reset():
    """Clear every metric (test isolation only)."""
    global _requests, _started_at
    with _lock:
        _metrics.clear()
        _requests = 0
        _started_at = time.monotonic()
