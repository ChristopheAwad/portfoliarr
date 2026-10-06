// ---------------------------------------------------------------------------
// perf.js — performance measurement shared by every page.
//
// Loaded by base.html BEFORE common.js, so the fetch wrapper and the page
// scripts can use the globals defined here. Two jobs:
//   1. COLLECT: navigation phases (TTFB/DOM/load), largest contentful
//      paint, one timing per fetch (wall time + the server's Server-Timing
//      "app" duration), and render-complete marks page scripts drop with
//      perfMark().
//   2. REPORT: an opt-in on-page overlay (?perf=1 or localStorage
//      "perfDebug" === "true") and ONE navigator.sendBeacon per page view
//      to POST /api/perf/client, which the server logs and aggregates.
//
// Nothing here polls, and no query strings, symbols, or financial data
// leave the page: endpoints are normalized to templates like
// /api/stock/:symbol before they are stored or sent.
// ---------------------------------------------------------------------------
(function () {
    // Dynamic URL segments → one bounded template each. The server caps
    // and validates these too (it never trusts a beacon).
    const PATH_TEMPLATES = [
        [/^\/api\/stock\/[^/]+$/, "/api/stock/:symbol"],
        [/^\/api\/quote\/[^/]+$/, "/api/quote/:symbol"],
        [/^\/api\/transactions\/\d+$/, "/api/transactions/:id"],
        [/^\/api\/widget\/tokens\/\d+$/, "/api/widget/tokens/:id"],
    ];

    function normalizePath(path) {
        let clean = String(path || "");
        try {
            if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(clean)) {
                clean = new URL(clean).pathname;
            }
        } catch { /* not a parseable URL — keep the string */ }
        const cut = clean.search(/[?#]/);
        if (cut !== -1) clean = clean.slice(0, cut);
        for (const [pattern, template] of PATH_TEMPLATES) {
            if (pattern.test(clean)) return template;
        }
        return clean;
    }

    function pageName(pathname) {
        if (pathname === "/") return "dashboard";
        if (pathname.startsWith("/ledger")) return "ledger";
        if (pathname.startsWith("/stock/")) return "stock";
        if (pathname.startsWith("/preferences")) return "preferences";
        return "other";
    }

    const state = {
        page: pageName(window.location.pathname),
        navigation: {},
        lcp_ms: null,
        marks: {},
        fetches: [],
        sent: false,
    };

    // Page scripts call this unconditionally; common.js also defines a
    // no-op fallback in case this file ever fails to load.
    window.perfMark = function (name) {
        if (!(name in state.marks)) state.marks[name] = performance.now();
        paintOverlay();
    };

    // Navigation phases. The setTimeout matters: INSIDE the load handler
    // loadEventEnd is still 0 (the browser stamps it after the event
    // returns), so the numbers are only final on the next task.
    function captureNavigation() {
        try {
            const entry = performance.getEntriesByType("navigation")[0];
            if (entry) {
                const phases = {
                    ttfb_ms: entry.responseStart - entry.startTime,
                    dom_ms: entry.domContentLoadedEventEnd - entry.startTime,
                    load_ms: entry.loadEventEnd - entry.startTime,
                };
                for (const key of Object.keys(phases)) {
                    const value = phases[key];
                    if (Number.isFinite(value) && value >= 0) {
                        state.navigation[key] = value;
                    }
                }
            }
        } catch { /* timing API unavailable — phases stay empty */ }
        paintOverlay();
    }
    window.addEventListener("load", () => {
        setTimeout(captureNavigation, 0);
    });

    // Largest contentful paint — the closest thing to "when did the page
    // look done". Wrapped: some WebView builds lack this entry type.
    try {
        const observer = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                state.lcp_ms = entry.startTime;
            }
            paintOverlay();
        });
        observer.observe(
            { type: "largest-contentful-paint", buffered: true });
    } catch { /* unsupported — LCP stays null */ }

    const SERVER_TIMING_RE = /(?:^|,)\s*app;dur=(\d+(?:\.\d+)?)/;

    function recordFetch(url, startedAt, response) {
        try {
            const wall = performance.now() - startedAt;
            if (!Number.isFinite(wall) || wall < 0) return;
            let serverMs = null;
            try {
                const header = response.headers.get("Server-Timing");
                const match = header && header.match(SERVER_TIMING_RE);
                if (match) serverMs = Number(match[1]);
            } catch { /* header access failed — skip server time */ }
            let bytes = null;
            try {
                const length = response.headers.get("Content-Length");
                if (length !== null) bytes = Number(length);
            } catch { /* header access failed — skip bytes */ }
            let rawUrl = window.location.pathname;
            if (typeof url === "string") rawUrl = url;
            else if (url && url.url) rawUrl = url.url;
            state.fetches.push({
                endpoint: normalizePath(rawUrl),
                ms: Math.round(wall * 10) / 10,
                server_ms: serverMs,
                bytes,
                status: response.status,
            });
            if (state.fetches.length > 40) state.fetches.shift();
            paintOverlay();
        } catch { /* measurement must never break a fetch */ }
    }

    function summary() {
        return {
            page: state.page,
            navigation: { ...state.navigation },
            lcp_ms: state.lcp_ms,
            marks: { ...state.marks },
            fetches: state.fetches.map((item) => ({ ...item })),
        };
    }

    function beaconPayload() {
        const payload = { page: state.page, ...state.navigation };
        if (state.lcp_ms !== null) payload.lcp_ms = state.lcp_ms;
        payload.fetches = state.fetches.map((item) => ({
            endpoint: item.endpoint,
            ms: item.ms,
            server_ms: item.server_ms,
            bytes: item.bytes,
            status: item.status,
        }));
        return payload;
    }

    function sendBeacon() {
        if (state.sent) return;
        state.sent = true;
        try {
            const blob = new Blob([JSON.stringify(beaconPayload())],
                { type: "application/json" });
            navigator.sendBeacon("/api/perf/client", blob);
        } catch { /* reporting is best-effort */ }
    }

    window.addEventListener("pagehide", sendBeacon);
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") sendBeacon();
    });
    // A tab that is never hidden must still report: one late send per view.
    window.addEventListener("load", () => {
        setTimeout(sendBeacon, 15000);
    });

    // --- Opt-in overlay ------------------------------------------------
    const overlayRequested = (() => {
        try {
            if (localStorage.getItem("perfDebug") === "true") return true;
            return new URLSearchParams(window.location.search).get("perf")
                === "1";
        } catch { return false; }
    })();

    let overlayBody = null;

    function paintOverlay() {
        if (!overlayRequested) return;
        if (!overlayBody) {
            const panel = document.createElement("div");
            panel.id = "perf-overlay";
            const heading = document.createElement("strong");
            heading.textContent = "perf";
            const copy = document.createElement("button");
            copy.type = "button";
            copy.textContent = "Copy";
            copy.addEventListener("click", () => {
                if (navigator.clipboard) {
                    navigator.clipboard.writeText(
                        JSON.stringify(summary(), null, 2));
                }
            });
            overlayBody = document.createElement("pre");
            panel.append(heading, copy, overlayBody);
            document.body.appendChild(panel);
        }
        const nav = state.navigation;
        const lines = [
            `page ${state.page}  ttfb ${fmt(nav.ttfb_ms)}  ` +
            `dom ${fmt(nav.dom_ms)}  load ${fmt(nav.load_ms)}  ` +
            `lcp ${fmt(state.lcp_ms)}`,
        ];
        for (const name of Object.keys(state.marks)) {
            lines.push(`mark ${name} ${state.marks[name].toFixed(0)}ms`);
        }
        const slowest = [...state.fetches].sort((a, b) => b.ms - a.ms);
        for (const item of slowest) {
            lines.push(`fetch ${item.ms.toFixed(0)}ms ` +
                `srv ${fmt(item.server_ms)} ${item.endpoint}`);
        }
        overlayBody.textContent = lines.join("\n");
    }

    function fmt(value) {
        return Number.isFinite(value) ? `${value.toFixed(0)}ms` : "-";
    }

    window.PortfoliarrPerf = {
        mark: window.perfMark,
        normalizePath,
        recordFetch,
        summary,
        beaconPayload,
    };
})();
