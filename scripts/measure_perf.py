"""Synthetic end-to-end performance measurement for Portfoliarr.

Playwright lives in the SYSTEM python, Flask lives in the project venv:
    /usr/bin/python3 scripts/measure_perf.py [--runs 2] [--stub-ms 150]

The script starts scripts/perf_server.py with .venv/bin/python on a
throwaway database, completes first-run setup, seeds a small ledger and
watchlist through the REAL API, visits every page (run 1, then --runs-1
repeats that reuse the TTL caches), and writes a baseline report to
docs/perf/ (JSON + Markdown).

Live mode (default) measures real Yahoo. --stub-ms N replaces Yahoo with
a fixed N ms latency per call, so app-level changes (extra calls,
parallelism, caching) are comparable without network noise.

The report's run 1 is the first measured visit; the setup redirect has
already warmed some symbols. Compare like for like: same mode, same runs.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
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


def wait_for_server(base, timeout=40.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/auth/setup", timeout=2):
                return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return False


def seed(page, base):
    """Complete setup and create a small representative dataset."""
    page.goto(f"{base}/auth/setup")
    page.fill("#setup-username", "perfadmin")
    page.fill("#setup-password", "perf-pass-1234")
    page.fill("#setup-confirm", "perf-pass-1234")
    page.click(".auth-form button[type=submit]")
    page.wait_for_url(f"{base}/")
    page.wait_for_load_state("networkidle")
    today = date.today().isoformat()
    page.evaluate(
        """async (today) => {
            const post = (url, body) => fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            }).then((r) => r.status);
            const portfolios = await fetch('/api/portfolios')
                .then((r) => r.json());
            const pid = portfolios[0].id;
            await post('/api/transactions', {ticker: 'AAPL', date: today,
                price: 150, qty: 2, type: 'BUY', portfolio_id: pid});
            await post('/api/transactions', {ticker: 'RY.TO', date: today,
                price: 120, qty: 3, type: 'BUY', portfolio_id: pid});
            await post('/api/watchlist', {symbol: 'MSFT'});
            await post('/api/watchlist', {symbol: 'SHOP.TO'});
        }""", today)


def measure(page, base, page_name, path, run, settle_s):
    started = time.time()
    page.goto(f"{base}{path}", wait_until="load")
    page.wait_for_load_state("networkidle")
    time.sleep(settle_s)
    summary = page.evaluate(
        "window.PortfoliarrPerf ? window.PortfoliarrPerf.summary() : null")
    server = page.evaluate("fetch('/api/perf').then((r) => r.json())")
    return {
        "page": page_name,
        "path": path,
        "run": run,
        "observed_s": round(time.time() - started, 2),
        "summary": summary,
        "server": server,
    }


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
        f"- Run 1 is the first measured visit; later runs reuse the 120–600 s "
        f"TTL caches. Compare like for like.",
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
        for item in fetches[:5]:
            lines.append(
                f"- fetch {item.get('endpoint')}: {fmt_ms(item.get('ms'))} ms "
                f"(server {fmt_ms(item.get('server_ms'))})")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=2,
                        help="runs per page (run 1 is the first visit)")
    parser.add_argument("--stub-ms", type=int, default=0,
                        help="fixed Yahoo latency in ms; 0 = live Yahoo")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--settle", type=float, default=4.0,
                        help="seconds to wait after load for late fetches")
    parser.add_argument("--out", default=None,
                        help="output base path (default docs/perf/baseline-<date>)")
    options = parser.parse_args()

    base = f"http://localhost:{options.port}"
    out_base = Path(options.out) if options.out else (
        ROOT / "docs" / "perf" / f"baseline-{date.today().isoformat()}")
    out_base.parent.mkdir(parents=True, exist_ok=True)

    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        sys.exit(f"venv python not found at {venv_python}")

    env = dict(os.environ)
    env["PERF_PORT"] = str(options.port)
    if options.stub_ms > 0:
        env["PERF_STUB_YAHOO_MS"] = str(options.stub_ms)

    server = subprocess.Popen(
        [str(venv_python), str(ROOT / "scripts" / "perf_server.py")],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": (f"stub {options.stub_ms} ms per Yahoo call"
                 if options.stub_ms > 0 else "live Yahoo"),
        "runs": options.runs,
        "settle_s": options.settle,
        "measurements": [],
        "console_errors": [],
        "server_final": None,
    }

    try:
        if not wait_for_server(base):
            sys.exit("perf server did not start")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280,
                                                    "height": 800})
            page = context.new_page()
            page.on("pageerror", lambda exc: report["console_errors"].append(
                str(exc)))
            page.on("console", lambda msg: report["console_errors"].append(
                msg.text) if msg.type == "error" else None)

            seed(page, base)

            for page_name, path in PAGES:
                for run in range(1, options.runs + 1):
                    row = measure(page, base, page_name, path, run,
                                  options.settle)
                    report["measurements"].append(row)
                    summary = row.get("summary") or {}
                    nav = summary.get("navigation") or {}
                    print(f"{page_name} run {run}: ttfb={fmt_ms(nav.get('ttfb_ms'))} "
                          f"load={fmt_ms(nav.get('load_ms'))} "
                          f"lcp={fmt_ms(summary.get('lcp_ms'))} "
                          f"({row['observed_s']} s observed)")

            report["server_final"] = page.evaluate(
                "fetch('/api/perf').then((r) => r.json())")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    (out_base.with_suffix(".json")).write_text(
        json.dumps(report, indent=2) + "\n")
    markdown = to_markdown(report)
    (out_base.with_suffix(".md")).write_text(markdown + "\n")
    print(f"\nwrote {out_base.with_suffix('.md')}")
    print(f"wrote {out_base.with_suffix('.json')}")


if __name__ == "__main__":
    main()
