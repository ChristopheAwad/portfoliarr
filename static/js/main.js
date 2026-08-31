// Frontend logic for the live indices bar, the live watchlist, AND the
// transaction ledger.
//
// Talks to the Flask backend over HTTP only (fetch -> JSON -> DOM).
// Knows nothing about yfinance, Flask, or Python.

// How often to re-fetch quotes, in milliseconds. Matches the backend's
// design: the 120s TTL means at most every other poll touches Yahoo.
const REFRESH_MS = 60000;

// Chips managed by JS = those carrying a data-symbol attribute.
// Chips without one (the static placeholders) are invisible to this code.
function managedChips() {
    return document.querySelectorAll(".chip[data-symbol]");
}

// Set every managed chip to a placeholder:
// "…" while waiting for data, "—" when the backend is unreachable.
function setChipState(text) {
    managedChips().forEach((chip) => {
        chip.querySelector(".index-price").textContent = text;
        chip.querySelector(".index-change").textContent = "";
    });
}

// The browser's built-in human formatting engine:
// 7711.759765625 -> "7,711.76". This is why the backend sends raw floats.
function formatPrice(value) {
    return new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(value);
}

// Fill one chip from one quote object (a parsed piece of the JSON list).
function updateChip(quote) {
    // Find the chip by its data-symbol hook — by meaning, not position.
    const chip = document.querySelector(`.chip[data-symbol="${quote.symbol}"]`);
    if (!chip) return; // backend knows a symbol our HTML doesn't show yet

    const priceEl = chip.querySelector(".index-price");
    const changeEl = chip.querySelector(".index-change");

    const positive = quote.change >= 0;
    const sign = positive ? "+" : "";

    // textContent (never innerHTML): writes plain text, immune to HTML
    // injection. innerHTML would interpret strings as markup.
    // Every price carries its native currency code ("USD", "CAD", ...) —
    // per the brief: native currency display, no FX conversion.
    priceEl.textContent = `${formatPrice(quote.price)} ${quote.currency}`;
    changeEl.textContent =
        `${sign}${formatPrice(quote.change)} (${sign}${quote.change_pct.toFixed(2)}%)`;

    // One call each: set green (pos) or red (neg), replacing the other.
    changeEl.classList.toggle("pos", positive);
    changeEl.classList.toggle("neg", !positive);
}

// One refresh cycle: HTTP GET -> check status -> parse JSON -> paint DOM.
async function refreshIndices() {
    try {
        const response = await fetch("/api/indices");
        // fetch does NOT throw on 4xx/5xx — only on network failure.
        // A 503 arrives as a "successful" fetch with ok === false.
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const quotes = await response.json(); // raw bytes -> JS objects
        for (const quote of quotes) updateChip(quote);

        // Gap-fill: the backend returns successes only, so any managed chip
        // whose symbol did NOT arrive just failed while its siblings lived.
        // Set = O(1) membership test for "did this symbol answer?".
        const answered = new Set(quotes.map((q) => q.symbol));
        managedChips().forEach((chip) => {
            if (!answered.has(chip.dataset.symbol)) {
                chip.querySelector(".index-price").textContent = "—";
                chip.querySelector(".index-change").textContent = "";
            }
        });
    } catch (err) {
        console.error("indices refresh failed:", err);
        setChipState("—");
    }
}

// Boot sequence moved to the bottom of the file — every function above must
// be defined before it runs.

// ---------------------------------------------------------------------------
// WATCHLIST — same refresh rhythm as the indices bar, but the rows are
// dynamic. The chips are fixed HTML the backend merely fills; watchlist rows
// exist only because the backend's symbol list says so, so JS builds (and
// rebuilds) the <li> elements itself every cycle.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
const watchlistEl = document.querySelector(".watchlist");
const addTickerBtn = document.querySelector("#add-ticker-btn");

// Replace the list's contents with one message row (used for the empty
// watchlist and for "the backend is unreachable" states).
function setWatchlistMessage(text) {
    // textContent = "" wipes all children in one assignment — the simple
    // way to clear a container before rebuilding it.
    watchlistEl.textContent = "";
    const row = document.createElement("li");
    row.className = "empty-state";
    row.textContent = text;
    watchlistEl.append(row);
}

// Rebuild the list: one <li class="watchlist-item"> per stored symbol, each
// carrying a data-symbol hook (same "find by meaning, not position" contract
// as the chips) and starting blank until a quote fills it in.
function renderWatchlistRows(symbols) {
    // Empty watchlist is a normal state, not an error — say so nicely.
    if (symbols.length === 0) {
        setWatchlistMessage("Nothing here yet — click + Add");
        return;
    }

    watchlistEl.textContent = "";
    for (const symbol of symbols) {
        // document.createElement builds real DOM nodes; textContent writes
        // plain text. Both together are immune to HTML injection — never
        // assemble rows with innerHTML from backend strings.
        const row = document.createElement("li");
        row.className = "watchlist-item";
        row.dataset.symbol = symbol; // the row's identity hook

        // Left side: the ticker and (when available) its company name.
        const left = document.createElement("div");
        const tickerEl = document.createElement("strong");
        tickerEl.textContent = symbol;
        const nameEl = document.createElement("div");
        nameEl.className = "sub-text";
        nameEl.textContent = "…"; // filled in when the quote arrives
        left.append(tickerEl, nameEl);

        // Right side: live price and the day's percentage change.
        const right = document.createElement("div");
        right.className = "text-right";
        const priceEl = document.createElement("div");
        priceEl.className = "watch-price";
        priceEl.textContent = "…";
        const changeEl = document.createElement("span");
        changeEl.className = "change-tag";
        right.append(priceEl, changeEl);

        // The × button. It gets rebuilt with the rows every cycle, so we
        // never attach a click listener to it directly — one delegated
        // listener on the parent <ul> handles clicks for all rows forever.
        const removeBtn = document.createElement("button");
        removeBtn.className = "remove-btn";
        removeBtn.textContent = "×";
        removeBtn.title = `Remove ${symbol}`;
        removeBtn.dataset.symbol = symbol;

        row.append(left, right, removeBtn);
        watchlistEl.append(row);
    }
}

// Fill one row from one quote dict (a parsed piece of the JSON "quotes" list).
function updateWatchRow(quote) {
    const row = document.querySelector(
        `.watchlist-item[data-symbol="${quote.symbol}"]`
    );
    if (!row) return; // row was removed between cycles; harmless

    const nameEl = row.querySelector(".sub-text");
    const priceEl = row.querySelector(".watch-price");
    const changeEl = row.querySelector(".change-tag");

    // Native currency per security (same rule as the chips): "182.52 USD".
    // change_pct arrives as a float like 1.3012 — the backend never
    // pre-formats; display decisions stay here.
    priceEl.textContent = `${formatPrice(quote.price)} ${quote.currency}`;

    const positive = quote.change_pct >= 0;
    const sign = positive ? "+" : "";
    changeEl.textContent = `${sign}${quote.change_pct.toFixed(2)}%`;
    changeEl.classList.toggle("pos", positive);
    changeEl.classList.toggle("neg", !positive);

    // A failed name fetch came back as null — show the ticker alone.
    nameEl.textContent = quote.name || "";
}

// Mark every current row unavailable ("—"): used when a cycle could not
// reach the backend at all, or (gap-fill) when a specific symbol's quote
// didn't arrive while its siblings' did.
function markWatchlistUnavailable() {
    watchlistEl.querySelectorAll(".watchlist-item").forEach((row) => {
        row.querySelector(".watch-price").textContent = "—";
        row.querySelector(".sub-text").textContent = "";
        const changeEl = row.querySelector(".change-tag");
        changeEl.textContent = "";
        changeEl.classList.remove("pos", "neg");
    });
}

// One watchlist refresh cycle: GET -> rebuild rows -> fill quotes -> gap-fill.
async function refreshWatchlist() {
    try {
        const response = await fetch("/api/watchlist");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        // One response, two payloads: "symbols" = which rows exist (source
        // of truth), "quotes" = successes only for this cycle.
        const payload = await response.json();

        renderWatchlistRows(payload.symbols);
        for (const quote of payload.quotes) updateWatchRow(quote);

        // Gap-fill, same Set-membership test as the indices bar: any stored
        // symbol whose quote didn't answer just failed while its siblings
        // lived.
        const answered = new Set(payload.quotes.map((q) => q.symbol));
        watchlistEl.querySelectorAll(".watchlist-item").forEach((row) => {
            if (!answered.has(row.dataset.symbol)) {
                row.querySelector(".watch-price").textContent = "—";
                row.querySelector(".sub-text").textContent = "";
                const changeEl = row.querySelector(".change-tag");
                changeEl.textContent = "";
                changeEl.classList.remove("pos", "neg");
            }
        });
    } catch (err) {
        console.error("watchlist refresh failed:", err);
        // If we have rows from an earlier successful cycle, degrade them to
        // "—" like the chips do. If we never got rows at all, we can't know
        // the symbol list — show a message instead.
        if (watchlistEl.querySelector(".watchlist-item")) {
            markWatchlistUnavailable();
        } else {
            setWatchlistMessage("Watchlist unavailable");
        }
    }
}

// + Add: ask for a ticker, POST it, let the next refresh pull the truth.
// The backend validates the ticker is real (404) and rejects duplicates
// (409) — the frontend just relays its error messages.
addTickerBtn.addEventListener("click", async () => {
    // prompt() returns null when the user cancels — abort quietly.
    const input = prompt(
        "Ticker symbol to watch (e.g. AAPL, SHOP.TO, BTC-USD):"
    );
    if (input === null) return;
    const symbol = input.trim().toUpperCase();
    if (!symbol) return;

    try {
        const response = await fetch("/api/watchlist", {
            method: "POST",
            // Without this header Flask would not know the body is JSON.
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol }),
        });
        if (!response.ok) {
            // The backend's error JSON is more useful than a generic
            // message — relay it. .catch(() => null) guards against a
            // response that isn't parseable JSON.
            const data = await response.json().catch(() => null);
            alert(data?.error || `Could not add ${symbol} (HTTP ${response.status})`);
            return;
        }
        // 201 Created: a refresh pulls the stored list (and the new row's
        // live quote — adding it warmed the backend's price cache).
        refreshWatchlist();
    } catch (err) {
        console.error("add ticker failed:", err);
        alert("Could not reach the server — is it running?");
    }
});

// Remove: ONE delegated listener on the parent <ul>. Click events bubble up
// from whatever was actually clicked (here, a × button that gets rebuilt
// every cycle), and closest() walks back up the tree to find the button we
// care about. Attaching listeners to the buttons themselves would die with
// every rebuild — delegation survives it.
watchlistEl.addEventListener("click", async (event) => {
    const removeBtn = event.target.closest(".remove-btn");
    if (!removeBtn) return; // click landed somewhere else in the list

    const symbol = removeBtn.dataset.symbol;
    // encodeURIComponent: symbols can contain URL-hostile characters
    // ("^GSPC", "BTC-USD") — encode the PATH, never the whole URL.
    try {
        const response = await fetch(
            `/api/watchlist/${encodeURIComponent(symbol)}`,
            { method: "DELETE" }
        );
        // 204 (gone) is success; 404 means it was already gone elsewhere —
        // refreshing either way shows the stored truth.
        if (!response.ok && response.status !== 404) {
            throw new Error(`HTTP ${response.status}`);
        }
        refreshWatchlist();
    } catch (err) {
        console.error("remove ticker failed:", err);
        alert("Could not reach the server — is it running?");
    }
});

// ---------------------------------------------------------------------------
// TRANSACTION LEDGER — the list of BUY/SELL events, plus the form that logs
// new ones. Same philosophy as the watchlist: the HTML ships an EMPTY
// <tbody>, and this code rebuilds the rows from /api/transactions every
// cycle. The backend returns each row's immutable facts PLUS live math
// (price_now, value, total_gain/pct, day_gain/pct — raw floats: its job is
// numbers, ours is formatting), so all this section does is place text and
// colours.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
const txForm = document.querySelector("#tx-form");
const txErrorEl = document.querySelector(".tx-error");
const ledgerBody = document.querySelector("#ledger-body");
const txDateInput = txForm.elements.date;

// Local "today" as YYYY-MM-DD — the date input's default value.
// Why not new Date().toISOString().slice(0, 10)? toISOString() is UTC: in
// the evening in a negative-UTC timezone (or morning in a positive-UTC one)
// it returns a DIFFERENT day than the user's clock says. Building the
// string from the LOCAL getters avoids that off-by-one-day surprise.
function todayLocalISO() {
    const now = new Date();
    // padStart forces two digits: "2026-8-5" would fail fromisoformat
    // server-side; "2026-08-05" is the ISO form it demands.
    const pad = (n) => String(n).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

// Grouped-thousands formatter with a flexible decimal cap. Unlike
// formatPrice (fixed at 2), maxDigits lets the qty column show fractional
// amounts ("0.0050" BTC) without trailing-zero spam on whole numbers.
function formatNumber(value, maxDigits = 2) {
    return new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: maxDigits,
    }).format(value);
}

// Signed money text: 12.3 -> "+12.30 CAD", -7.1 -> "-7.10 CAD".
// Gains are signed in the DATA; the sign character is presentation,
// so it belongs here (same rule as the chips' "+" prefix).
function formatSigned(value, currency) {
    const sign = value >= 0 ? "+" : "";
    return `${sign}${formatNumber(value)} ${currency}`;
}

// Replace the tbody's contents with one full-width message row (empty
// ledger, backend unreachable). Same wipe-and-rebuild trick as the
// watchlist's setWatchlistMessage.
function setLedgerMessage(text) {
    ledgerBody.textContent = "";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 10; // one cell spanning the whole table (must match the
                       // <th> count — 10 columns)
    cell.className = "empty-state";
    cell.textContent = text;
    row.append(cell);
    ledgerBody.append(row);
}

// Rebuild the tbody: one <tr> per transaction. Facts are always present;
// live cells (value/gain) exist only when the backend could quote that
// ticker — otherwise they gap-fill to "—".
function renderLedger(transactions) {
    if (transactions.length === 0) {
        setLedgerMessage("No transactions yet — log your first above.");
        return;
    }

    // Wipe last cycle's rows, then build fresh ones. createElement +
    // textContent only: assembled strings (innerHTML) would let any
    // backend-originated text execute as markup.
    ledgerBody.textContent = "";

    for (const tx of transactions) {
        const row = document.createElement("tr");

        // --- Facts (from the DB, always present) ---
        const dateCell = document.createElement("td");
        dateCell.textContent = tx.transaction_date;

        const typeCell = document.createElement("td");
        const badge = document.createElement("span");
        badge.className =
            `tx-badge ${tx.transaction_type === "BUY" ? "buy" : "sell"}`;
        badge.textContent = tx.transaction_type;
        typeCell.append(badge);

        const tickerCell = document.createElement("td");
        tickerCell.textContent = tx.ticker;

        const qtyCell = document.createElement("td");
        qtyCell.className = "num";
        qtyCell.textContent = formatNumber(tx.qty, 4);

        // Native currency per security — the stored code travels with the
        // facts (no FX conversion, per the brief).
        const priceCell = document.createElement("td");
        priceCell.className = "num";
        priceCell.textContent = `${formatNumber(tx.price)} ${tx.currency}`;

        // --- Live cells (present only when decorated) ---
        const hasLive = tx.price_now !== undefined;

        const valueCell = document.createElement("td");
        valueCell.className = "num ledger-live";
        const gainCell = document.createElement("td");
        gainCell.className = "num ledger-live";
        const gainPctCell = document.createElement("td");
        gainPctCell.className = "num ledger-live";
        const dayGainCell = document.createElement("td");
        dayGainCell.className = "num ledger-live";
        const dayPctCell = document.createElement("td");
        dayPctCell.className = "num ledger-live";

        if (hasLive) {
            valueCell.textContent = `${formatNumber(tx.value)} ${tx.currency}`;

            // Total gain/pct: the position's whole lifetime since purchase.
            gainCell.textContent = formatSigned(tx.total_gain, tx.currency);
            gainPctCell.textContent =
                `${tx.total_gain_pct >= 0 ? "+" : ""}${tx.total_gain_pct.toFixed(2)}%`;

            // Day gain/pct: TODAY's move only. The % is the ticker's daily
            // move itself — the same for any position size.
            dayGainCell.textContent = formatSigned(tx.day_gain, tx.currency);
            dayPctCell.textContent =
                `${tx.day_gain_pct >= 0 ? "+" : ""}${tx.day_gain_pct.toFixed(2)}%`;

            // Green for gains, red for losses — the shared pos/neg classes.
            // Each pair colours independently: a position can be up overall
            // (green Total) while today is red (neg Day).
            for (const [cell, value] of [
                [gainCell, tx.total_gain],
                [gainPctCell, tx.total_gain_pct],
                [dayGainCell, tx.day_gain],
                [dayPctCell, tx.day_gain_pct],
            ]) {
                cell.classList.toggle("pos", value >= 0);
                cell.classList.toggle("neg", value < 0);
            }
        } else {
            // The backend couldn't quote this ticker this cycle. The facts
            // still show; only the live cells degrade.
            valueCell.textContent = "—";
            gainCell.textContent = "—";
            gainPctCell.textContent = "—";
            dayGainCell.textContent = "—";
            dayPctCell.textContent = "—";
        }

        row.append(dateCell, typeCell, tickerCell, qtyCell, priceCell,
                   valueCell, gainCell, gainPctCell, dayGainCell, dayPctCell);
        ledgerBody.append(row);
    }
}

// Degrade live cells to "—" when a refresh cycle fails entirely but fact
// rows from an earlier cycle are still on screen (mirrors the watchlist's
// markWatchlistUnavailable).
function markLedgerUnavailable() {
    ledgerBody.querySelectorAll(".ledger-live").forEach((cell) => {
        cell.textContent = "—";
        cell.classList.remove("pos", "neg");
    });
}

// One ledger refresh cycle: GET -> rebuild rows. The backend's quote cache
// means at most every other cycle touches Yahoo — same rhythm as the chips
// and the watchlist.
async function refreshLedger() {
    try {
        const response = await fetch("/api/transactions");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const transactions = await response.json();
        renderLedger(transactions);
    } catch (err) {
        console.error("ledger refresh failed:", err);
        if (ledgerBody.querySelector(".ledger-row")) {
            markLedgerUnavailable();
        } else {
            // We never got rows at all — can't know if the ledger is empty
            // or unreachable, so say exactly that.
            setLedgerMessage("Ledger unavailable");
        }
    }
}

// Form submit: the ONLY way rows are born. preventDefault stops the
// browser's native full-page form POST — we want fetch + partial update,
// not a navigation. The backend remains the real validator: its named
// 400/404 messages are shown inline, its 201 is the trigger to re-fetch.
txForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    // FormData collects every named input's current value; fromEntries
    // turns it into a plain object. Numbers arrive as STRINGS from inputs
    // — Number() converts them to real JSON numbers before shipping.
    const fields = Object.fromEntries(new FormData(txForm));
    const body = {
        ticker: String(fields.ticker || "").trim().toUpperCase(),
        date: fields.date,
        price: Number(fields.price),
        qty: Number(fields.qty),
        type: fields.type,
    };

    // Fresh attempt, fresh error state.
    txErrorEl.hidden = true;

    try {
        const response = await fetch("/api/transactions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => null);
            txErrorEl.textContent =
                err?.error || `Could not log transaction (HTTP ${response.status})`;
            txErrorEl.hidden = false;
            return;
        }
        // 201: the row exists server-side. Clear the form (reset() restores
        // HTML-attribute defaults, so the date default — set in JS — must be
        // re-applied) and pull the truth immediately rather than waiting
        // for the next poll.
        txForm.reset();
        txDateInput.value = todayLocalISO();
        refreshLedger();
    } catch (err) {
        console.error("log transaction failed:", err);
        txErrorEl.textContent = "Could not reach the server — is it running?";
        txErrorEl.hidden = false;
    }
});

// Prefill the date input ONCE at load: "today" is the overwhelmingly common
// answer for a fresh transaction.
txDateInput.value = todayLocalISO();

// ---------------------------------------------------------------------------
// PORTFOLIO CHART — placeholder data for now. Chart.js itself came from the
// CDN <script> tag in index.html, so a global "Chart" class already exists
// by the time this runs. Real backend data comes later; this section proves
// the canvas renders and shows the config shape we'll reuse then.
// ---------------------------------------------------------------------------

// The canvas from the HTML — our blank drawing pad — and its "2D context":
// the object whose methods actually paint pixels onto the pad.
const portfolioCanvas = document.getElementById("portfolioChart");
const portfolioCtx = portfolioCanvas.getContext("2d");

// A handle we can use later to push real data into the same chart
// (see the comment at the end of this section).
let portfolioChart = null;

// Guard: the CDN could be unreachable (offline, blocked, down). Without this
// check, "new Chart(...)" would throw and kill EVERYTHING below in main.js —
// including the watchlist boot code. One if/else buys graceful degradation.
if (typeof Chart === "undefined") {
    console.error("Chart.js failed to load from the CDN — chart skipped");
} else {
    portfolioChart = new Chart(portfolioCtx, {
        // "type" picks the chart family. "line" connects each point to the
        // next — the classic stock-chart look. Other options: "bar",
        // "doughnut" (that one is planned for portfolio allocation later).
        type: "line",

        data: {
            // labels = x-axis categories, one slot per data point.
            labels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            datasets: [
                {
                    // A dataset is ONE series of numbers = one line.
                    label: "Portfolio Value",
                    data: [142.0, 143.5, 141.75, 144.2, 146.8, 145.1, 148.3],
                    // Google blue line + a faint translucent fill under it.
                    borderColor: "#1a73e8",
                    backgroundColor: "rgba(26, 115, 232, 0.1)",
                    fill: true,
                    // tension bends the line between points: 0 = straight
                    // segments, higher = smoother curves. ~0.3 looks like
                    // a finance chart without distorting the data.
                    tension: 0.3,
                    pointRadius: 3,
                },
            ],
        },

        options: {
            // responsive: redraw to match the parent .chart-box's size.
            // maintainAspectRatio: false lets our CSS height (300px) win —
            // otherwise Chart.js locks in its own width:height ratio.
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                // With only one dataset, the legend ("Portfolio Value"
                // swatch) adds nothing. Off it comes, for the clean look.
                legend: { display: false },
            },
            scales: {
                x: { grid: { display: false } }, // no vertical gridlines
                y: {
                    grid: { color: "#e0e0e0" },
                    // beginAtZero: false starts the y-axis near the data's
                    // minimum instead of 0 — exactly how real stock charts
                    // make small daily moves visible.
                    beginAtZero: false,
                },
            },
        },
    });
}

// "portfolioChart" is our handle on the live chart object. When real data
// arrives later, updating the chart will look like:
//   portfolioChart.data.labels = [...new labels];
//   portfolioChart.data.datasets[0].data = [...new values];
//   portfolioChart.update();
// — and the canvas redraws itself. No page reload, no new Chart needed.

// ---------------------------------------------------------------------------
// BOOT — the script's entry point. This block runs top-to-bottom the moment
// the browser reaches it, and only now are all the functions above defined.
// ---------------------------------------------------------------------------

// 1. Blank both managed sections so the outdated mockup numbers can never
//    masquerade as live data. The indices chips get "…"; the watchlist
//    starts truly empty and refreshWatchlist paints it within the second.
setChipState("…");

// 2. Fetch all three sections immediately — no waiting for the first interval.
refreshIndices();
refreshWatchlist();
refreshLedger();

// 3. Poll. ONE timer drives all cycles: all three sections' data changes at
//    the same rate, so polling them together keeps them in lockstep and
//    doubles as the change-detector for anything added through other
//    windows or tabs (add/remove/log shows up within a minute even without
//    its own trigger).
setInterval(() => {
    refreshIndices();
    refreshWatchlist();
    refreshLedger();
}, REFRESH_MS);
