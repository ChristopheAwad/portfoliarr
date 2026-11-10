"""Synthetic end-to-end performance measurement for Portfoliarr.

Playwright lives in the SYSTEM python, Flask lives in the project venv:
    /usr/bin/python3 scripts/measure_perf.py [--runs 2] [--stub-ms 150]

The driver binds a free loopback port, starts scripts/perf_server.py on a
throwaway database with that inherited socket, waits for the child's
`PERF-READY <token>` line, completes first-run setup, seeds a small ledger
and watchlist through the REAL API, verifies the counts, then visits every
page. Run 1 is the first measured visit; later runs reuse the 120-600 s TTL
caches. `--cold` restarts the server before each page so every page is
measured with cold process caches.

Live mode (default) measures real Yahoo. --stub-ms N replaces Yahoo with
a fixed N ms latency per call, so app-level changes (extra calls,
parallelism, caching) are comparable without network noise.

HONESTY RULES FOR READING THE REPORT:

- The stub patches app.py's imported market functions, so it bypasses the
  real process caches. Stub runs measure request and render plumbing, not
  cache performance; the `/api/perf` market hit/miss rows stay empty.
- Without --cold, run 1 follows setup, which already warmed some symbols.
  It is the first measured visit, NOT a cold-start measurement.
- Compare like for like: same mode, same runs, same viewport.
"""

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    ("dashboard", "/"),
    ("ledger", "/ledger"),
    ("stock", "/stock/AAPL"),
    ("preferences", "/preferences"),
]

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "perf"
CHART_URLS = {
    "https://cdn.jsdelivr.net/npm/chart.js@4":
        FIXTURE_DIR / "chart.umd.4.6.1.js",
    "https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3":
        FIXTURE_DIR / "chartjs-plugin-annotation.3.1.0.min.js",
}

PERF_ENV_KEYS = (
    "PERF_STUB_YAHOO_MS", "PERF_STUB_EMPTY_STOCK", "PERF_PORT",
    "PERF_LISTEN_FD", "PERF_READY_TOKEN", "PERF_DB_PATH",
)


class PerfServer:
    """One child server on a parent-owned listening socket.

    The token handshake is the identity proof: the parent never connects
    until this exact child prints the random token, so setup and seeding
    cannot hit an unrelated process on a reused port.
    """

    def __init__(self, python, base_env, db_path, stub_ms=0,
                 empty_stock=False, timeout=60.0):
        self.token = secrets.token_hex(16)
        self.db_path = Path(db_path)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(128)
        self.port = self.sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.lines = []
        self.condition = threading.Condition()

        env = {key: value for key, value in base_env.items()
               if key not in PERF_ENV_KEYS}
        env["PERF_LISTEN_FD"] = str(self.sock.fileno())
        env["PERF_READY_TOKEN"] = self.token
        env["PERF_DB_PATH"] = str(self.db_path)
        if stub_ms > 0:
            env["PERF_STUB_YAHOO_MS"] = str(stub_ms)
        if empty_stock:
            env["PERF_STUB_EMPTY_STOCK"] = "1"

        self.proc = subprocess.Popen(
            [str(python), str(ROOT / "scripts" / "perf_server.py")],
            cwd=str(ROOT), env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            pass_fds=(self.sock.fileno(),),
        )
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()
        self._wait_ready(timeout)

    def _read_output(self):
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            with self.condition:
                self.lines.append(line.rstrip("\n"))
                self.condition.notify_all()

    def _wait_ready(self, timeout):
        ready = f"PERF-READY {self.token}"
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                if ready in self.lines:
                    return
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        "perf server exited before ready:\n"
                        + "\n".join(self.lines))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        "perf server did not become ready in "
                        f"{timeout:.0f}s:\n" + "\n".join(self.lines))
                self.condition.wait(min(remaining, 0.25))

    def output(self):
        with self.condition:
            return list(self.lines)

    def stop(self):
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
        finally:
            self.reader.join(timeout=5)
            self.sock.close()


def seed(page, base, ledger_rows=0):
    """Complete setup and create a small representative dataset.

    `ledger_rows` seeds a synthetic ledger through the REAL import API so a
    large-ledger measurement never touches the live portfolio: the perf
    server runs on a throwaway database.
    """
    page.goto(f"{base}/auth/setup")
    page.fill("#setup-username", "perfadmin")
    page.fill("#setup-password", "perf-pass-1234")
    page.fill("#setup-confirm", "perf-pass-1234")
    page.click(".auth-form button[type=submit]")
    page.wait_for_url(f"{base}/")
    page.wait_for_load_state("networkidle")
    today = date.today().isoformat()
    statuses = page.evaluate(
        """async (today) => {
            const post = (url, body) => fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            }).then((r) => r.status);
            const portfolios = await fetch('/api/portfolios')
                .then((r) => r.json());
            const pid = portfolios[0].id;
            return [
                await post('/api/transactions', {ticker: 'AAPL', date: today,
                    price: 150, qty: 2, type: 'BUY', portfolio_id: pid}),
                await post('/api/transactions', {ticker: 'RY.TO', date: today,
                    price: 120, qty: 3, type: 'BUY', portfolio_id: pid}),
                await post('/api/watchlist', {symbol: 'MSFT'}),
                await post('/api/watchlist', {symbol: 'SHOP.TO'}),
            ];
        }""", today)
    if statuses != [201, 201, 201, 201]:
        raise RuntimeError(f"seed requests failed: {statuses}")
    if ledger_rows > 0:
        lines = []
        for index in range(ledger_rows):
            day = date.fromordinal(date.today().toordinal() - index % 300)
            lines.append(
                f"SYN{index % 8}\t{day:%d %b %Y}\t{100 + index % 50}\t1")
        result = page.evaluate(
            """async (text) => fetch('/api/transactions/import/commit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text}),
            }).then(async (r) => ({status: r.status, body: await r.json()}))""",
            "\n".join(lines))
        if result["status"] != 200:
            raise RuntimeError(
                f"synthetic ledger import failed: HTTP {result['status']}")
        failed = result["body"].get("failed") or []
        if failed:
            raise RuntimeError(
                f"synthetic ledger import failed on {len(failed)} row(s): "
                f"{failed[0]}")


def verify_seed(db_path, ledger_rows):
    """Read the throwaway database and prove what was actually stored.

    The import route answers 200 even when rows fail, so the HTTP status
    alone is not evidence. Counts are checked directly, read-only.
    """
    expected_rows = 2 + ledger_rows
    expected_tickers = 10 if ledger_rows else 2
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows, tickers = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT ticker) FROM transactions"
        ).fetchone()
    if (rows, tickers) != (expected_rows, expected_tickers):
        raise RuntimeError(
            "seed verification failed: expected "
            f"{expected_rows} transactions across {expected_tickers} "
            f"tickers, found {rows} across {tickers}")


def fulfill_external(route, missing_chart=False):
    """Serve deterministic bytes for CDN requests in an offline run."""
    url = route.request.url
    if missing_chart and url in CHART_URLS:
        route.fulfill(status=200, headers={
            "content-type": "application/javascript"}, body="")
        return
    asset = CHART_URLS.get(url)
    if asset is not None and asset.exists():
        route.fulfill(status=200, headers={
            "content-type": "application/javascript"},
            body=asset.read_bytes())
        return
    # Fonts and anything else: inert. A stylesheet needs a CSS MIME type or
    # the browser logs an error even for an empty body.
    content_type = ("text/css" if url.endswith(".css")
                    or "fonts.googleapis.com" in url else "text/plain")
    route.fulfill(status=200, headers={"content-type": content_type},
                  body="")


def wait_for_page_ready(page, page_name, require_chart):
    """Wait for the page's own evidence that useful content painted."""
    if page_name == "dashboard":
        page.wait_for_function(
            "window.PortfoliarrPerf && window.PortfoliarrPerf.summary()"
            ".marks['dashboard:summary']", timeout=30000)
        if require_chart:
            page.wait_for_function(
                "typeof Chart !== 'undefined' && "
                "!!Chart.getChart(document.getElementById('portfolioChart'))",
                timeout=30000)
    elif page_name == "stock":
        page.wait_for_function(
            "window.PortfoliarrPerf && window.PortfoliarrPerf.summary()"
            ".marks['stock:quote']", timeout=30000)
        if require_chart:
            page.wait_for_function(
                "typeof Chart !== 'undefined' && "
                "!!Chart.getChart(document.getElementById('stockChart'))",
                timeout=30000)
    elif page_name == "ledger":
        page.wait_for_function(
            "window.PortfoliarrPerf && window.PortfoliarrPerf.summary()"
            ".marks['ledger:rows']", timeout=30000)


def measure(page, base, page_name, path, run, settle_s, require_chart):
    started = time.time()
    page.goto(f"{base}{path}", wait_until="load")
    wait_for_page_ready(page, page_name, require_chart)
    page.wait_for_load_state("networkidle")
    time.sleep(settle_s)
    ledger_expand_ms = None
    ledger_second_expand_ms = None
    if page_name == "ledger":
        groups = page.locator("#ledger-body .ledger-group")
        if groups.count() > 0:
            ledger_expand_ms = _expand_group(page, 0)
        if groups.count() > 1:
            ledger_second_expand_ms = _expand_group(page, 1)
    summary = page.evaluate(
        "window.PortfoliarrPerf ? window.PortfoliarrPerf.summary() : null")
    chart_state = page.evaluate(
        """() => ({
            chart_loaded: typeof Chart !== 'undefined',
            portfolio_chart: typeof Chart !== 'undefined' &&
                !!Chart.getChart(document.getElementById('portfolioChart')),
            stock_chart: typeof Chart !== 'undefined' &&
                !!Chart.getChart(document.getElementById('stockChart')),
        })""")
    server = page.evaluate("fetch('/api/perf').then((r) => r.json())")
    return {
        "page": page_name,
        "path": path,
        "run": run,
        "observed_s": round(time.time() - started, 2),
        "ledger_expand_ms": ledger_expand_ms,
        "ledger_second_expand_ms": ledger_second_expand_ms,
        "chart": chart_state,
        "summary": summary,
        "server": server,
    }


def _expand_group(page, group_index):
    """Click one group row and time the detail rows becoming visible."""
    before = page.evaluate(
        "document.querySelectorAll('#ledger-body tr.tx-detail:not([hidden])')"
        ".length")
    started = time.perf_counter()
    page.evaluate(
        """(index) => {
            const row = document.querySelectorAll(
                '#ledger-body .ledger-group')[index];
            row.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        }""", group_index)
    page.wait_for_function(
        """(expected) => document.querySelectorAll(
            '#ledger-body tr.tx-detail:not([hidden])').length > expected""",
        arg=before, timeout=10000)
    return round((time.perf_counter() - started) * 1000, 1)


def fmt_ms(value):
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:.0f}"


def to_markdown(report):
    lines = [
        f"# Portfoliarr performance baseline — "
        f"{report['generated_at'][:10]}",
        "",
        f"- Mode: **{report['mode']}**",
        f"- Runs per page: {report['runs']}",
        f"- Settle after load: {report['settle_s']} s",
        f"- Viewport: {report.get('viewport', '1280x800')}",
        f"- Synthetic ledger rows: {report.get('ledger_rows', 0)}",
        f"- Empty stock degrade mode: {report.get('empty_stock', False)}",
        f"- Offline test assets: {report.get('offline_assets', False)}",
        f"- Charts required: {report.get('chart_required', False)}",
        f"- Cold server per page: {report.get('cold', False)}",
    ]
    if not report.get("cold"):
        lines.append(
            "- Run 1 is the first measured visit after setup, NOT a cold "
            "start. Later runs reuse the 120-600 s TTL caches. Compare like "
            "for like.")
    if report.get("stub_ms"):
        lines.append(
            "- Stub mode replaces app.py's imported market functions, so it "
            "bypasses the real market caches. The market cache table below is "
            "not a cache measurement; use live mode or unit tests for that.")
    lines += [
        "",
        "## Page loads (browser navigation timing)",
        "",
        "| page | run | ttfb ms | dom ms | load ms | lcp ms | "
        "observed s | fetches |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["measurements"]:
        summary = row.get("summary") or {}
        nav = summary.get("navigation") or {}
        fetches = summary.get("fetches") or []
        lines.append(
            f"| {row['page']} | {row['run']} | "
            f"{fmt_ms(nav.get('ttfb_ms'))} | {fmt_ms(nav.get('dom_ms'))} | "
            f"{fmt_ms(nav.get('load_ms'))} | {fmt_ms(summary.get('lcp_ms'))} | "
            f"{row['observed_s']} | {len(fetches)} |"
        )

    lines += [
        "",
        "## Render marks and slowest fetches",
        "",
    ]
    for row in report["measurements"]:
        summary = row.get("summary") or {}
        marks = summary.get("marks") or {}
        fetches = sorted(summary.get("fetches") or [],
                         key=lambda item: item.get("ms", 0), reverse=True)
        lines.append(f"### {row['page']} run {row['run']}")
        mark_text = "  ".join(
            f"{name}={value:.0f} ms" for name, value in sorted(
                marks.items(), key=lambda item: item[1]))
        lines.append(f"- marks: {mark_text or '-'}")
        chart = row.get("chart") or {}
        lines.append(
            f"- chart loaded={chart.get('chart_loaded')} "
            f"portfolio={chart.get('portfolio_chart')} "
            f"stock={chart.get('stock_chart')}")
        if row.get("ledger_expand_ms") is not None:
            lines.append(
                f"- ledger first group expansion: "
                f"{fmt_ms(row['ledger_expand_ms'])} ms")
        if row.get("ledger_second_expand_ms") is not None:
            lines.append(
                f"- ledger second group expansion: "
                f"{fmt_ms(row['ledger_second_expand_ms'])} ms")
        for item in fetches[:5]:
            lines.append(
                f"- fetch {item.get('endpoint')}: {fmt_ms(item.get('ms'))} ms "
                f"(server {fmt_ms(item.get('server_ms'))})")
        lines.append("")

    page_errors = report.get("page_errors") or []
    console_errors = report.get("console_errors") or []
    lines += [
        "## Browser page and console errors",
        "",
    ]
    if page_errors:
        lines.append("Uncaught page errors:")
        for message in page_errors:
            lines.append(f"- {message}")
    else:
        lines.append("- No uncaught page errors on the measured pages.")
    if console_errors:
        lines.append("Console errors:")
        for message in console_errors:
            lines.append(f"- {message}")
    else:
        lines.append("- No console errors recorded.")
    lines.append("")

    lines += [
        "## Server endpoints (p95, process lifetime)",
        "",
        "| endpoint | calls | p50 ms | p95 ms | max ms |",
        "|---|---|---|---|---|",
    ]
    server = report.get("server_final") or {}
    http_rows = [row for row in server.get("metrics", [])
                 if row["name"].startswith("http.")]
    http_rows.sort(key=lambda row: row["p95_ms"], reverse=True)
    for row in http_rows:
        lines.append(
            f"| {row['name'][len('http.'):]} | {row['count']} | "
            f"{row['p50_ms']} | {row['p95_ms']} | {row['max_ms']} |")

    lines += [
        "",
        "## Market cache (process lifetime)",
        "",
        "| operation | hit | miss | wait | hit rate | miss p95 ms |",
        "|---|---|---|---|---|---|",
    ]
    for name in ("market.get_quote", "market.get_history", "market.get_name",
                 "market.get_profile", "market.get_financials",
                 "market.get_events", "market.get_volume_leaders"):
        rows = [row for row in server.get("metrics", [])
                if row["name"] == name]
        if not rows:
            continue
        counts = {"hit": 0, "miss": 0, "wait": 0}
        miss_p95 = 0.0
        for row in rows:
            outcome = row["tags"].get("cache")
            if outcome in counts:
                counts[outcome] += row["count"]
            if outcome == "miss":
                miss_p95 = row["p95_ms"]
        calls = sum(counts.values())
        rate = f"{counts['hit'] / calls * 100:.0f}%" if calls else "-"
        lines.append(
            f"| {name} | {counts['hit']} | {counts['miss']} | "
            f"{counts['wait']} | {rate} | {miss_p95} |")

    lines.append("")
    return "\n".join(lines)


def viewport_size(value):
    """argparse type: WIDTHxHEIGHT, with a message a user can act on."""
    parts = value.lower().split("x")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError("viewport must look like 1280x800")
    width, height = (int(part) for part in parts)
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(
            "viewport width and height must be greater than zero")
    return width, height


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=2,
                        help="runs per page (run 1 is the first visit)")
    parser.add_argument("--stub-ms", type=int, default=0,
                        help="fixed Yahoo latency in ms; 0 = live Yahoo")
    parser.add_argument("--port", type=int, default=0,
                        help="accepted for compatibility; the driver binds "
                             "its own free loopback port")
    parser.add_argument("--settle", type=float, default=4.0,
                        help="seconds to wait after load for late fetches")
    parser.add_argument("--out", default=None,
                        help="output base path (default docs/perf/baseline-<date>)")
    parser.add_argument("--viewport", type=viewport_size, default=(1280, 800),
                        metavar="WIDTHxHEIGHT",
                        help="browser viewport (default 1280x800)")
    parser.add_argument("--ledger-rows", type=int, default=0,
                        help="extra synthetic ledger rows seeded through the "
                             "real import API (0 keeps the small dataset)")
    parser.add_argument("--allow-console-errors", action="store_true",
                        help="exit 0 even when the browser logged an error")
    parser.add_argument("--offline-assets", action="store_true",
                        help="serve pinned local Chart.js files for the CDN "
                             "URLs and inert responses for other https")
    parser.add_argument("--missing-chart", action="store_true",
                        help="like --offline-assets but the chart library "
                             "returns an empty body, to measure degradation")
    parser.add_argument("--cold", action="store_true",
                        help="restart the server before each page so process "
                             "caches are cold for every measured page")
    parser.add_argument("--python", default=None,
                        help="interpreter that runs perf_server.py (default: "
                             "PERF_PYTHON, then .venv/bin/python, then this "
                             "interpreter)")
    parser.add_argument("--empty-stock", action="store_true",
                        help="make financials/events return the normal 404s "
                             "so the stock page's degrade path is measured")
    options = parser.parse_args()
    if options.empty_stock and options.stub_ms <= 0:
        parser.error("--empty-stock requires --stub-ms N (live mode has no stub)")
    if options.missing_chart:
        options.offline_assets = True
    if not options.offline_assets and not CHART_URLS[
            "https://cdn.jsdelivr.net/npm/chart.js@4"].exists():
        parser.error("pinned test assets are missing; run with "
                     "--offline-assets only after restoring tests/fixtures/perf")

    width, height = options.viewport
    viewport_label = f"{width}x{height}"
    out_base = Path(options.out) if options.out else (
        ROOT / "docs" / "perf" / f"baseline-{date.today().isoformat()}")
    out_base.parent.mkdir(parents=True, exist_ok=True)

    # Reuse the main checkout's venv in a worktree. The driver itself runs
    # under the SYSTEM python (Playwright lives there), so sys.executable is
    # only a last resort: callers can name the Flask interpreter explicitly.
    venv_python = Path(
        options.python
        or os.environ.get("PERF_PYTHON", str(ROOT / ".venv" / "bin" / "python")))
    if not venv_python.exists():
        venv_python = Path(sys.executable)
        print(f"warning: no venv python at the default path; using "
              f"{venv_python} for perf_server.py", file=sys.stderr)

    run_dir = Path(tempfile.mkdtemp(prefix="portfoliarr-perf-run-"))
    db_path = run_dir / "perf.db"
    env = dict(os.environ)
    env["TMPDIR"] = str(run_dir)

    require_chart = options.offline_assets and not options.missing_chart
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": (f"stub {options.stub_ms} ms per Yahoo call"
                 if options.stub_ms > 0 else "live Yahoo"),
        "stub_ms": options.stub_ms,
        "runs": options.runs,
        "settle_s": options.settle,
        "viewport": viewport_label,
        "ledger_rows": options.ledger_rows,
        "empty_stock": options.empty_stock,
        "offline_assets": options.offline_assets,
        "missing_chart": options.missing_chart,
        "chart_required": require_chart,
        "cold": options.cold,
        "measurements": [],
        "console_errors": [],
        "page_errors": [],
        "server_final": None,
    }

    def start_server():
        return PerfServer(venv_python, env, db_path,
                          stub_ms=options.stub_ms,
                          empty_stock=options.empty_stock)

    server = None
    try:
        server = start_server()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": width,
                                                    "height": height})
            if options.offline_assets:
                # Playwright's glob handling does not match a bare
                # "https://**" pattern here, so match the scheme with a
                # regex and decide per request.
                context.route(
                    re.compile(r"^https://"),
                    lambda route: fulfill_external(
                        route, missing_chart=options.missing_chart))
            page = context.new_page()
            page.on("pageerror", lambda exc: report["page_errors"].append(
                str(exc)))
            page.on("console", lambda msg: report["console_errors"].append(
                msg.text) if msg.type == "error" else None)

            seed(page, server.base, options.ledger_rows)
            verify_seed(db_path, options.ledger_rows)

            for page_name, path in PAGES:
                if options.cold:
                    # A fresh process clears every market cache while the
                    # seeded disposable database and session survive.
                    server.stop()
                    server = start_server()
                for run in range(1, options.runs + 1):
                    row = measure(page, server.base, page_name, path, run,
                                  options.settle, require_chart)
                    report["measurements"].append(row)
                    summary = row.get("summary") or {}
                    nav = summary.get("navigation") or {}
                    print(f"{page_name} run {run}: ttfb={fmt_ms(nav.get('ttfb_ms'))} "
                          f"load={fmt_ms(nav.get('load_ms'))} "
                          f"lcp={fmt_ms(summary.get('lcp_ms'))} "
                          f"({row['observed_s']} s observed)")
                    chart = row.get("chart") or {}
                    print(f"  chart loaded={chart.get('chart_loaded')} "
                          f"portfolio={chart.get('portfolio_chart')} "
                          f"stock={chart.get('stock_chart')}")
                    if row.get("ledger_expand_ms") is not None:
                        print(f"  ledger first expansion: "
                              f"{fmt_ms(row['ledger_expand_ms'])} ms")
                    if row.get("ledger_second_expand_ms") is not None:
                        print(f"  ledger second expansion: "
                              f"{fmt_ms(row['ledger_second_expand_ms'])} ms")

            report["server_final"] = page.evaluate(
                "fetch('/api/perf').then((r) => r.json())")
            browser.close()
    finally:
        if server is not None:
            server.stop()
        shutil.rmtree(run_dir, ignore_errors=True)

    (out_base.with_suffix(".json")).write_text(
        json.dumps(report, indent=2) + "\n")
    markdown = to_markdown(report)
    (out_base.with_suffix(".md")).write_text(markdown + "\n")
    print(f"\nwrote {out_base.with_suffix('.md')}")
    print(f"wrote {out_base.with_suffix('.json')}")
    if report["page_errors"]:
        print(f"\n{len(report['page_errors'])} uncaught page error(s):",
              file=sys.stderr)
        for message in report["page_errors"]:
            print(f"  {message}", file=sys.stderr)
        sys.exit(1)
    if report["console_errors"]:
        print(f"\n{len(report['console_errors'])} console error(s) recorded:",
              file=sys.stderr)
        for message in report["console_errors"]:
            print(f"  {message}", file=sys.stderr)
        if not options.allow_console_errors:
            sys.exit(1)


if __name__ == "__main__":
    main()
