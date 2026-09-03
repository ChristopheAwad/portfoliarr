// Frontend logic for the DASHBOARD page: the live indices bar, the live
// watchlist, and the transaction ledger.
//
// Talks to the Flask backend over HTTP only (fetch -> JSON -> DOM).
// Knows nothing about yfinance, Flask, or Python.
//
// Shared helpers — REFRESH_MS, the formatters (formatPrice/formatNumber/
// formatSigned), paintChange, and the whole navbar search dropdown — live
// in common.js, which base.html loads BEFORE this file. They are plain
// globals here; defining them again would just shadow the shared ones.

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

// Navigate: a watchlist ROW is a link to the detail page now (the search
// dropdown shouldn't be the only way there). A second delegated listener
// on the same <ul> — delegation again, since rows are rebuilt every cycle.
// The × button lives INSIDE its row, so this listener must stand down
// when a click started on it: the remove listener above handles that
// click, and navigating on top of deleting would be a nasty surprise.
watchlistEl.addEventListener("click", (event) => {
    if (event.target.closest(".remove-btn")) return; // that's a removal
    const row = event.target.closest(".watchlist-item");
    if (!row) return; // click landed on the list itself
    window.location.href = `/stock/${encodeURIComponent(row.dataset.symbol)}`;
});

// ---------------------------------------------------------------------------
// TRANSACTION LEDGER — the list of BUY/SELL events, plus the form that logs
// new ones. Same philosophy as the watchlist: the HTML ships an EMPTY
// <tbody>, and this code rebuilds the rows from /api/transactions every
// cycle. The backend returns each row's immutable facts PLUS live math
// (price_now, value, total_gain/pct, day_gain/pct — raw floats: its job is
// numbers, ours is formatting), so all this section does is place text and
// colours.
//
// Presentation: transactions GROUP BY TICKER — one collapsed summary row
// per ticker (holding-level math, BUY rows only), expandable to the
// individual transactions underneath. Which groups are open lives in the
// expandedTickers Set below, because the DOM itself is rebuilt every cycle.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
const txForm = document.querySelector("#tx-form");
const txErrorEl = document.querySelector(".tx-error");
const txEditingEl = document.querySelector(".tx-editing");
const txEditingTextEl = txEditingEl.querySelector(".tx-editing-text");
const txCancelBtn = txEditingEl.querySelector(".tx-cancel");
const txSubmitBtn = txForm.querySelector("button[type=submit]");
const ledgerBody = document.querySelector("#ledger-body");
const txDateInput = txForm.elements.date;

// Edit-mode state + the last fetched rows. Both live OUTSIDE the DOM —
// same reasoning as expandedTickers below: the tbody rebuilds every 60s,
// so form mode and data must not depend on rows staying put.
//   editingTxId === null  -> the form is in "log a new transaction" mode
//   editingTxId === 7     -> the form is editing transaction #7
let editingTxId = null;
// The freshest GET result. Action clicks (edit/delete) look rows up HERE,
// by id — never by scraping the row's cell text back into data.
let lastTransactions = [];

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

// Replace the tbody's contents with one full-width message row (empty
// ledger, backend unreachable). Same wipe-and-rebuild trick as the
// watchlist's setWatchlistMessage.
function setLedgerMessage(text) {
    ledgerBody.textContent = "";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 11; // one cell spanning the whole table (must match the
                       // <th> count — 11 columns, incl. the actions column)
    cell.className = "empty-state";
    cell.textContent = text;
    row.append(cell);
    ledgerBody.append(row);
}

// Which ledger groups are expanded, keyed by ticker. This lives OUTSIDE
// the DOM on purpose: renderLedger rebuilds the tbody every poll cycle
// (watchlist pattern), so expansion state stored only on the rows would be
// wiped 60 seconds later. A Set gives O(1) add/delete/has — and a ticker
// that has never been clicked simply isn't in it, which is what "collapsed
// by default" means in practice.
const expandedTickers = new Set();

// Build ONE transaction detail row — the same 10 data cells the flat table
// always had, plus a trailing actions cell (edit/delete), extracted from
// renderLedger so the grouped view can stamp out one per transaction under
// its group's summary row. Facts are always present; live cells
// (value/gain) exist only when the backend could quote that ticker —
// otherwise they gap-fill to "—".
function buildTxRow(tx) {
    const row = document.createElement("tr");
    row.className = "ledger-row"; // refreshLedger's failure check keys on this class
    row.dataset.id = tx.id; // action buttons' hook: look this row up by id

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

    // --- Actions: edit + delete. They live ONLY on detail rows — a group
    // summary is an aggregate, not a record. Each button carries data-id;
    // the delegated listener looks the transaction up by id in
    // lastTransactions, so these buttons carry no row data themselves.
    const actionsCell = document.createElement("td");
    const editBtn = document.createElement("button");
    editBtn.className = "tx-action-btn edit";
    editBtn.textContent = "✎";
    editBtn.title = "Edit this transaction";
    editBtn.dataset.id = tx.id;
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "tx-action-btn delete";
    deleteBtn.textContent = "×";
    deleteBtn.title = "Delete this transaction";
    deleteBtn.dataset.id = tx.id;
    actionsCell.append(editBtn, deleteBtn);

    row.append(dateCell, typeCell, tickerCell, qtyCell, priceCell,
               valueCell, gainCell, gainPctCell, dayGainCell, dayPctCell,
               actionsCell);
    return row;
}

// Build ONE group summary row — the collapsed face of one ticker. It
// reuses the same 10 columns, but the numbers are GROUP-level:
//   Qty = NET position: buys add, sells subtract (facts only, so always
//         computable — even when the group's quote failed this cycle).
//   Value / Total Gain / Day Gain = sums over BUY rows ONLY. A SELL row's
//         "value" is what the sold shares would be worth today — summing
//         that into a group total would inflate it. BUY-only sums mirror
//         the holdings math Step 3 will formalize; SELL details stay
//         visible when the group is expanded.
//   Total Gain % = Σ total_gain ÷ Σ(price × qty of BUYs). Percentages
//         don't average — the group needs its cost basis back out of the
//         sums. Guarded: a SELL-only group has no cost basis → "—"
//         instead of dividing by zero.
//   Day Gain % = the ticker's daily move itself (price-level, identical
//         for every row — see the decoration comments in app.py), read
//         from any decorated row rather than aggregated.
// Decoration happens per UNIQUE ticker server-side, so within a group
// either every row has live math or none — no partial-group ambiguity.
function buildGroupRow(ticker, txs) {
    const row = document.createElement("tr");
    row.className = "ledger-group";
    row.dataset.ticker = ticker; // click-handler hook: find by meaning

    // --- Facts ---
    const dateCell = document.createElement("td");
    const caret = document.createElement("span");
    caret.className = "caret";
    caret.textContent = "▸";
    dateCell.append(caret, document.createTextNode(
        txs.length === 1 ? " 1 txn" : ` ${txs.length} txns`));

    // Deliberately blank: a group has no single type — the BUY/SELL mix
    // becomes visible when expanded.
    const typeCell = document.createElement("td");

    const tickerCell = document.createElement("td");
    // The group's ticker doubles as a link to the detail page. A real <a>
    // (not a click handler) means native middle-click / open-in-new-tab
    // for free — and the expand/collapse listener below must simply stand
    // down when a click starts on it. Still wrapped in <strong>: same
    // visual weight as before, the link is only revealed on hover.
    const tickerLink = document.createElement("a");
    tickerLink.className = "ticker-link";
    tickerLink.href = `/stock/${encodeURIComponent(ticker)}`;
    tickerLink.textContent = ticker;
    const tickerEl = document.createElement("strong");
    tickerEl.append(tickerLink);
    tickerCell.append(tickerEl);

    let netQty = 0;
    for (const tx of txs) {
        netQty += tx.transaction_type === "BUY" ? tx.qty : -tx.qty;
    }
    const qtyCell = document.createElement("td");
    qtyCell.className = "num";
    qtyCell.textContent = formatNumber(netQty, 4);

    // No single honest price for a group (average cost is Step 3's job) —
    // the column stays, but reads as empty.
    const priceCell = document.createElement("td");
    priceCell.className = "num";
    priceCell.textContent = "—";

    // --- Live cells (all-or-nothing per group, like the detail rows) ---
    const hasLive = txs[0].price_now !== undefined;

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
        // One currency per group by construction: it's auto-filled from
        // the ticker's quote at insert time, so every row in the group
        // carries the same code.
        const currency = txs[0].currency;

        let cost = 0;      // Σ price × qty over BUY rows — the % denominator
        let value = 0;
        let totalGain = 0;
        let dayGain = 0;
        for (const tx of txs) {
            if (tx.transaction_type !== "BUY") continue;
            cost += tx.price * tx.qty;
            value += tx.value;
            totalGain += tx.total_gain;
            dayGain += tx.day_gain;
        }

        // null = "no cost basis to divide by" (SELL-only group) → "—".
        const totalGainPct = cost > 0 ? (totalGain / cost) * 100 : null;

        valueCell.textContent = `${formatNumber(value)} ${currency}`;
        gainCell.textContent = formatSigned(totalGain, currency);
        gainPctCell.textContent = totalGainPct === null
            ? "—"
            : `${totalGainPct >= 0 ? "+" : ""}${totalGainPct.toFixed(2)}%`;
        dayGainCell.textContent = formatSigned(dayGain, currency);
        dayPctCell.textContent =
            `${txs[0].day_gain_pct >= 0 ? "+" : ""}${txs[0].day_gain_pct.toFixed(2)}%`;

        // Colour the sums with the same pos/neg rule as the detail rows —
        // with one guard: a null pct gets no colour, because "—" is
        // neither green nor red.
        for (const [cell, cellValue] of [
            [gainCell, totalGain],
            [gainPctCell, totalGainPct],
            [dayGainCell, dayGain],
            [dayPctCell, txs[0].day_gain_pct],
        ]) {
            if (cellValue === null) continue;
            cell.classList.toggle("pos", cellValue >= 0);
            cell.classList.toggle("neg", cellValue < 0);
        }
    } else {
        valueCell.textContent = "—";
        gainCell.textContent = "—";
        gainPctCell.textContent = "—";
        dayGainCell.textContent = "—";
        dayPctCell.textContent = "—";
    }

    // The actions column's 11th cell exists but stays EMPTY on summary
    // rows: groups are aggregates, not records — edit/delete belong to the
    // individual transactions, visible when the group is expanded.
    const actionsCell = document.createElement("td");

    row.append(dateCell, typeCell, tickerCell, qtyCell, priceCell,
               valueCell, gainCell, gainPctCell, dayGainCell, dayPctCell,
               actionsCell);
    return row;
}

// --- Edit mode: the form's second personality -----------------------------
// The form serves double duty: log mode (default) and edit mode. Reusing
// it (rather than a separate edit UI) means ONE set of inputs, ONE set of
// browser validations, ONE submit handler — the same reasoning as Step 2's
// "inline form, not prompt chain". Mode lives in editingTxId, not the DOM.

// Enter edit mode: prefill from the stored row, lock the ticker (the
// row's identity — NOT editable; currency was derived from it, so editing
// the ticker would silently rewrite a yfinance fact), rebrand Log -> Save.
function enterEditMode(tx) {
    editingTxId = tx.id;
    txForm.elements.ticker.value = tx.ticker;
    // Disabled inputs also drop out of FormData — fitting, since PUT's
    // contract is exactly the 4 editable fields.
    txForm.elements.ticker.disabled = true;
    txForm.elements.date.value = tx.transaction_date;
    txForm.elements.price.value = tx.price;
    txForm.elements.qty.value = tx.qty;
    txForm.elements.type.value = tx.transaction_type;
    txSubmitBtn.textContent = "Save";
    txEditingTextEl.textContent =
        `Editing ${tx.ticker} — ${tx.transaction_type} ` +
        `${formatNumber(tx.qty, 4)} @ ${formatNumber(tx.price)} on ` +
        `${tx.transaction_date}. `;
    txEditingEl.hidden = false;
    txErrorEl.hidden = true;
    // The clicked row may sit far below the form — bring the form to it.
    txForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// Leave edit mode: restore the form to "log a new transaction". Also the
// form's general reset — in log mode the edit-mode side effects are
// no-ops, so the submit handler can call this on BOTH success paths.
function exitEditMode() {
    editingTxId = null;
    txForm.reset();
    txForm.elements.ticker.disabled = false;
    txDateInput.value = todayLocalISO(); // reset() restores HTML defaults;
                                         // the JS-set date must be re-applied
    txSubmitBtn.textContent = "Log";
    txEditingEl.hidden = true;
    txErrorEl.hidden = true;
}

// Rebuild the tbody: one collapsed summary row per ticker, followed by that
// ticker's individual transactions as hidden detail rows. Grouping keeps
// first-appearance order — the backend list is newest-first, so the most
// recently transacted ticker lands on top.
function renderLedger(transactions) {
    if (transactions.length === 0) {
        setLedgerMessage("No transactions yet — log your first above.");
        return;
    }

    // Wipe last cycle's rows, then build fresh ones. createElement +
    // textContent only: assembled strings (innerHTML) would let any
    // backend-originated text execute as markup.
    ledgerBody.textContent = "";

    // A Map remembers insertion order (a plain object's key order isn't a
    // promise we want to lean on) — exactly the "newest ticker first"
    // grouping we want.
    const groups = new Map();
    for (const tx of transactions) {
        if (!groups.has(tx.ticker)) groups.set(tx.ticker, []);
        groups.get(tx.ticker).push(tx);
    }

    for (const [ticker, txs] of groups) {
        ledgerBody.append(buildGroupRow(ticker, txs));

        // Expanded state is consulted from the Set, not the DOM — a group
        // the user opened stays open across every poll rebuild.
        const open = expandedTickers.has(ticker);
        for (const tx of txs) {
            const detailRow = buildTxRow(tx);
            detailRow.classList.add("tx-detail");
            detailRow.dataset.ticker = ticker; // click-handler hook
            detailRow.hidden = !open; // collapsed by default
            ledgerBody.append(detailRow);
        }
    }
}

// Expand/collapse on click: ONE delegated listener on the tbody, same
// pattern as the watchlist's × button — summary rows are rebuilt every
// cycle, so a listener attached to the rows themselves would die with each
// rebuild; delegation on the parent survives it.
ledgerBody.addEventListener("click", (event) => {
    const groupRow = event.target.closest(".ledger-group");
    if (!groupRow) return; // click landed on a detail or message row

    // ...unless it started on the ticker LINK inside the group row: the
    // <a>'s native navigation wins, and toggling the group on top of
    // navigating would fight the page change.
    if (event.target.closest("a")) return;

    const ticker = groupRow.dataset.ticker;
    const open = !expandedTickers.has(ticker);

    // State first (it must survive the next poll rebuild), then the DOM
    // for the instant visual flip — no re-fetch, no re-render.
    if (open) expandedTickers.add(ticker);
    else expandedTickers.delete(ticker);
    groupRow.classList.toggle("open", open);

    // CSS.escape: tickers can contain selector-hostile characters
    // ("BRK.B") — the attribute-selector cousin of encodeURIComponent.
    ledgerBody.querySelectorAll(
        `.tx-detail[data-ticker="${CSS.escape(ticker)}"]`
    ).forEach((detailRow) => { detailRow.hidden = !open; });
});

// Edit/delete clicks: a SECOND delegated listener on the tbody, kept
// separate from the group-toggle listener so each concern reads alone.
// (Action buttons sit inside DETAIL rows, so the group listener's
// closest(".ledger-group") misses them — no conflict between the two.)
ledgerBody.addEventListener("click", async (event) => {
    // --- Edit: find the transaction BY ID in the cached fetch and hand
    // it to the form. The buttons are rebuilt every cycle, so delegation
    // is what keeps them alive.
    const editBtn = event.target.closest(".tx-action-btn.edit");
    if (editBtn) {
        const tx = lastTransactions.find(
            (t) => t.id === Number(editBtn.dataset.id));
        if (tx) enterEditMode(tx);
        return;
    }

    // --- Delete: confirm, DELETE, refresh. Not our click? Done.
    const deleteBtn = event.target.closest(".tx-action-btn.delete");
    if (!deleteBtn) return;
    const tx = lastTransactions.find(
        (t) => t.id === Number(deleteBtn.dataset.id));
    if (!tx) return;

    // Deletion is immediate and unrecoverable — the backend keeps no trash
    // bin. confirm() pauses the script until the user answers.
    if (!confirm(`Delete ${tx.transaction_type} of ${formatNumber(tx.qty, 4)} ` +
                 `${tx.ticker} @ ${formatNumber(tx.price)} on ` +
                 `${tx.transaction_date}?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/transactions/${tx.id}`, {
            method: "DELETE",
        });
        // 204 = gone. 404 = already gone (another window beat us to it) —
        // refreshing either way shows the stored truth, watchlist rule.
        if (!response.ok && response.status !== 404) {
            throw new Error(`HTTP ${response.status}`);
        }
        // If THIS row was open in the form, its edit target is gone —
        // drop back to log mode rather than submitting into a 404.
        if (editingTxId === tx.id) exitEditMode();
        refreshLedger();
        // The header totals depend on the ledger too — refresh both now.
        refreshPortfolioSummary();
    } catch (err) {
        console.error("delete transaction failed:", err);
        alert("Could not reach the server — is it running?");
    }
});

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
        lastTransactions = transactions; // cache for action-click lookups
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

// Form submit: the ONLY way rows are born (POST) or corrected (PUT).
// preventDefault stops the browser's native full-page form POST — we want
// fetch + partial update, not a navigation. The backend remains the real
// validator: its named 400/404 messages are shown inline, its 200/201 is
// the trigger to re-fetch.
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
        // Branch on mode: PUT for the row being edited (body is exactly
        // the 4 editable fields — the ticker input is disabled, so it
        // drops out of FormData, matching the backend's ignore-it rule),
        // POST for a brand-new row.
        const response = editingTxId === null
            ? await fetch("/api/transactions", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(body),
              })
            : await fetch(`/api/transactions/${editingTxId}`, {
                  method: "PUT",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                      date: body.date,
                      price: body.price,
                      qty: body.qty,
                      type: body.type,
                  }),
              });
        if (!response.ok) {
            const err = await response.json().catch(() => null);
            txErrorEl.textContent =
                err?.error || `Could not save transaction (HTTP ${response.status})`;
            txErrorEl.hidden = false;
            // A 404 while editing means the row no longer exists (deleted
            // in another window) — editing further is pointless. A 400 is
            // fixable: stay in edit mode and let the user correct the field.
            if (response.status === 404 && editingTxId !== null) {
                exitEditMode();
            }
            return;
        }
        if (editingTxId === null) {
            // 201 (log): auto-expand the logged ticker's group BEFORE the
            // refresh — groups collapse by default, and without this the
            // transaction just entered would land inside a collapsed
            // group, making the POST look like it did nothing.
            expandedTickers.add(body.ticker);
        }
        // Success: back to log mode (resets the form AND reapplies the
        // today-default date in one place), then pull the truth
        // immediately rather than waiting for the next poll.
        exitEditMode();
        refreshLedger();
        // The header totals depend on the ledger too — refresh both now.
        refreshPortfolioSummary();
    } catch (err) {
        console.error("save transaction failed:", err);
        txErrorEl.textContent = "Could not reach the server — is it running?";
        txErrorEl.hidden = false;
    }
});

// Cancel: leave edit mode, back to logging. type="button" in the markup
// is what stops this button from triggering the form's submit handler —
// a plain <button> inside a form defaults to submit.
txCancelBtn.addEventListener("click", exitEditMode);

// Prefill the date input ONCE at load: "today" is the overwhelmingly common
// answer for a fresh transaction.
txDateInput.value = todayLocalISO();

// Deep-link prefill: the stock detail page's "Log Transaction" button lands
// here as /?ticker=AAPL#tx-form. The #tx-form anchor scrolls the browser to
// this form; reading the param here prefills the ticker, so the user's next
// keystroke is the price. That's the whole integration — no second form on
// the detail page, ONE form and ONE submit handler for logging (the same
// reuse rule the edit mode follows).
const prefillTicker =
    new URLSearchParams(window.location.search).get("ticker");
if (prefillTicker) {
    txForm.elements.ticker.value = prefillTicker.trim().toUpperCase();
    txForm.elements.ticker.focus();
}

// ---------------------------------------------------------------------------
// IMPORT PANEL — bulk-load a pasted batch of transactions. The format is
// four tab-separated columns per line: ticker, "16 Mar 2026" date, price,
// qty; every row is a BUY (the format has no side column — see the panel's
// hint text). Two phases, mirroring the backend's two routes:
//   Preview -> POST /api/transactions/import/preview — parses + quote-checks
//              server-side, writes NOTHING; the report is the whole truth
//   Commit  -> POST /api/transactions/import/commit — the SAME text again;
//              the server re-parses and writes only the rows that pass
// The frontend never parses or edits rows: it ships the paste verbatim to
// both routes, so the server's verdict is the single source of truth and
// nothing the browser did in between can change what gets stored.
// ---------------------------------------------------------------------------

const importBtn = document.querySelector("#import-btn");
const importPanel = document.querySelector("#import-panel");
const importTextEl = document.querySelector("#import-text");
const importPreviewBtn = document.querySelector("#import-preview-btn");
const importCommitBtn = document.querySelector("#import-commit-btn");
const importCloseBtn = document.querySelector("#import-close-btn");
const importReportEl = document.querySelector("#import-report");

// Toggle the panel. The hidden attribute is the one source of truth — no
// extra "open" class to keep in sync. Focus goes to the textarea so the
// very next keystroke lands in the paste area.
importBtn.addEventListener("click", () => {
    importPanel.hidden = !importPanel.hidden;
    if (!importPanel.hidden) importTextEl.focus();
});

importCloseBtn.addEventListener("click", () => {
    importPanel.hidden = true;
});

// Render the report area from a payload: a counts line, then one line per
// row — valid rows with their normalized facts, broken rows in red with
// the backend's reason (including its line number, so the user can find
// the bad line in their paste). createElement + textContent throughout:
// the paste is USER input and this report renders it back — innerHTML
// would turn a crafted line into executable markup.
// summaryText overrides the default "N valid, M invalid" line — the
// commit path uses it for a post-import receipt instead.
function renderImportReport(payload, summaryText) {
    importReportEl.textContent = "";
    if (payload.rows.length === 0) {
        importReportEl.hidden = true; // nothing to say (e.g. no failures)
        return;
    }

    const summary = document.createElement("p");
    summary.className = "import-summary";
    summary.textContent =
        summaryText ||
        `${payload.valid_count} valid, ${payload.invalid_count} invalid`;
    importReportEl.append(summary);

    for (const row of payload.rows) {
        const line = document.createElement("p");
        if (row.error !== null) {
            line.className = "import-row-bad";
            line.textContent = `Line ${row.line}: ${row.raw} — ${row.error}`;
        } else {
            // Same formatting rules as the ledger rows: raw floats in,
            // human text out. formatNumber's maxDigits keeps fractional
            // qtys (1.296383) honest without trailing-zero spam.
            line.className = "import-row-ok";
            line.textContent =
                `Line ${row.line}: BUY ${formatNumber(row.qty, 4)} ` +
                `${row.ticker} @ ${formatNumber(row.price)} ` +
                `${row.currency} on ${row.transaction_date}`;
        }
        importReportEl.append(line);
    }
    importReportEl.hidden = false;
}

// Show a single red line (HTTP-level errors, network failures) in the
// report area — inline, matching the tx-error pattern above.
function showImportError(text) {
    importReportEl.textContent = "";
    const line = document.createElement("p");
    line.className = "import-row-bad";
    line.textContent = text;
    importReportEl.append(line);
    importReportEl.hidden = false;
}

// Preview: the dress rehearsal. Nothing is stored; the report shows
// exactly what commit WOULD store. The Import button only appears when at
// least one row is valid — committing zero rows is not an action.
importPreviewBtn.addEventListener("click", async () => {
    importCommitBtn.hidden = true; // stale verdict until this preview lands
    try {
        const response = await fetch("/api/transactions/import/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: importTextEl.value }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => null);
            showImportError(
                err?.error || `Preview failed (HTTP ${response.status})`
            );
            return;
        }
        const payload = await response.json();
        renderImportReport(payload);
        importCommitBtn.hidden = payload.valid_count === 0;
        importCommitBtn.textContent =
            `Import ${payload.valid_count} row` +
            `${payload.valid_count === 1 ? "" : "s"}`;
    } catch (err) {
        console.error("import preview failed:", err);
        showImportError("Could not reach the server — is it running?");
    }
});

// Commit: same paste, write half. Afterwards the report becomes the
// receipt — a success summary, or the failed rows if the batch was
// partial. The panel stays OPEN (unlike the original plan's "close
// panel"): closing it would hide the failure report, and the ledger
// refresh below is visible either way. The user closes when done.
importCommitBtn.addEventListener("click", async () => {
    try {
        const response = await fetch("/api/transactions/import/commit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: importTextEl.value }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => null);
            showImportError(
                err?.error || `Import failed (HTTP ${response.status})`
            );
            return;
        }
        const payload = await response.json();
        if (payload.failed.length > 0) {
            // Partial success: show ONLY what failed (the imported rows
            // are already visible in the ledger behind the panel), with
            // a receipt-style summary instead of the preview counts.
            renderImportReport(
                {
                    rows: payload.failed,
                    valid_count: 0,
                    invalid_count: payload.failed.length,
                },
                `Imported ${payload.imported}, ` +
                `${payload.failed.length} failed:`
            );
        } else {
            showImportSuccess(payload.imported);
        }
        importCommitBtn.hidden = true; // one paste, one commit — re-preview first
        // Pull the truth immediately rather than waiting for the next poll
        // (same rule as the log form's submit handler) — the ledger AND
        // the header totals, which are computed from it.
        refreshLedger();
        refreshPortfolioSummary();
    } catch (err) {
        console.error("import commit failed:", err);
        showImportError("Could not reach the server — is it running?");
    }
});

// Success receipt: the report area doubles as one, so the panel gives
// feedback instead of silently sitting there after a clean import.
function showImportSuccess(count) {
    importReportEl.textContent = "";
    const line = document.createElement("p");
    line.className = "import-summary";
    line.textContent =
        `Imported ${count} transaction${count === 1 ? "" : "s"} into the ledger.`;
    importReportEl.append(line);
    importReportEl.hidden = false;
}

// ---------------------------------------------------------------------------
// PORTFOLIO HEADER — the "Your Portfolio" card's three live numbers: total
// value, today's move, and total return. Rendering only, like every section
// above: GET /api/portfolio/summary computes the raw floats from the ledger
// + live quotes; this code formats and paints them.
//
// The three spans ship blank in index.html ("…") so the old mockup numbers
// can never masquerade as live data — same rule as the indices chips.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
const portfolioValueEl = document.getElementById("portfolio-value");
const portfolioDayChangeEl = document.getElementById("portfolio-day-change");
const portfolioTotalReturnEl =
    document.getElementById("portfolio-total-return");

// Degraded state: value "—", change lines blank. Used when the fetch fails
// entirely AND when the backend reports that nothing priced is contributing
// (every held ticker unquotable this cycle) — a bare "0.00" would imply the
// holdings are worthless, when the truth is "we couldn't price them".
// tooltipText (optional) explains WHY on hover.
function setPortfolioUnavailable(tooltipText = "") {
    portfolioValueEl.textContent = "—";
    portfolioValueEl.title = tooltipText;
    for (const el of [portfolioDayChangeEl, portfolioTotalReturnEl]) {
        el.textContent = "";
        el.classList.remove("pos", "neg");
    }
}

// (The change-pill painter itself is common.js's paintChange — the stock
// detail page paints the exact same shape, so the helper moved there.)

// One summary refresh cycle: GET -> paint the three spans.
async function refreshPortfolioSummary() {
    try {
        const response = await fetch("/api/portfolio/summary");
        // fetch does NOT throw on 4xx/5xx — only on network failure.
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        // "unpriced" lists the tickers the backend couldn't quote this
        // cycle. They were excluded from EVERY sum, so if the sums are
        // all zero WHILE that list is non-empty, nothing priced is
        // contributing — degrade the whole header instead of showing a
        // hollow "0.00" that would imply worthless holdings.
        const nothingPriced = data.unpriced.length > 0 &&
            data.total_value === 0 &&
            data.day_gain === 0 &&
            data.total_gain === 0;
        if (nothingPriced) {
            setPortfolioUnavailable(
                `Couldn't price: ${data.unpriced.join(", ")}`
            );
            return;
        }

        // Partial case: paint the priced totals, but say on hover which
        // tickers are missing. title="" wipes a stale tooltip from an
        // earlier cycle — the hover text must always match THIS payload.
        portfolioValueEl.title = data.unpriced.length > 0
            ? `Excludes ${data.unpriced.join(", ")} — couldn't be priced`
            : "";
        portfolioValueEl.textContent = formatNumber(data.total_value);
        paintChange(portfolioDayChangeEl, data.day_gain, data.day_gain_pct,
                    "Today");
        paintChange(portfolioTotalReturnEl, data.total_gain,
                    data.total_gain_pct, "Total");
    } catch (err) {
        console.error("portfolio summary refresh failed:", err);
        setPortfolioUnavailable();
    }
}

// ---------------------------------------------------------------------------
// PORTFOLIO CHART — real portfolio value over time. (It began life as
// hardcoded placeholder data — a learning exercise — before the ledger
// made real numbers possible.) Chart.js itself comes from the CDN <script>
// tag in base.html's <head>, so a global "Chart" class already exists by
// the time this runs.
//
// The chart itself is built by common.js's setupTimeframeChart — the stock
// detail page plots the identical picture with a different endpoint, so
// the Chart.js config, the 1D–MAX button wiring, and the refresh cycle all
// moved there. This page's only input is WHERE the data comes from.
// ---------------------------------------------------------------------------

// The canvas from the HTML — our blank drawing pad — and the timeframe
// button bar above it.
const portfolioCanvas = document.getElementById("portfolioChart");
const chartButtonsEl = document.querySelector(".chart-timeframe-selectors");

// The default period — must match the `active` button in index.html (5D),
// so the first thing the chart shows is the same range the button bar
// claims is selected.
const DEFAULT_CHART_PERIOD = "5D";

// Build once at load with empty data; every refresh swaps the arrays and
// redraws — no re-creating the Chart, no page reload. The factory wires
// the delegated .time-btn listener too, so a click re-fetches with the
// clicked button's textContent as the PERIOD_MAP key.
const portfolioChartHandle = setupTimeframeChart({
    canvas: portfolioCanvas,
    buttonBar: chartButtonsEl,
    datasetLabel: "Portfolio Value",
    endpoint: "/api/portfolio/history",
    defaultPeriod: DEFAULT_CHART_PERIOD,
});

// The boot section below calls this with no argument (the default 5D view);
// nothing else needs it — button clicks are wired inside the factory.
function refreshPortfolioChart(period = DEFAULT_CHART_PERIOD) {
    // If Chart.js never loaded, the handle is null — nothing to paint.
    if (portfolioChartHandle) portfolioChartHandle.refresh(period);
}

// ---------------------------------------------------------------------------
// BOOT — the script's entry point. This block runs top-to-bottom the moment
// the browser reaches it, and only now are all the functions above defined.
// ---------------------------------------------------------------------------

// 1. Blank both managed sections so the outdated mockup numbers can never
//    masquerade as live data. The indices chips get "…"; the watchlist
//    starts truly empty and refreshWatchlist paints it within the second.
setChipState("…");

// 2. Fetch all four quote-driven sections immediately — no waiting for the
//    first interval.
refreshIndices();
refreshWatchlist();
refreshLedger();
refreshPortfolioSummary();
// The portfolio chart is fetched once at load (its default 5D view) and
// again only when a timeframe button is clicked — unlike the quote-driven
// sections, price history doesn't change on a 60s cadence, so it would be
// wasteful (and Yahoo rate-limit-hammering) to poll it too.
refreshPortfolioChart();

// 3. Poll. ONE timer drives all cycles: all four sections' data changes at
//    the same rate (the summary is quote-driven too — prices move, totals
//    follow), so polling them together keeps them in lockstep and doubles
//    as the change-detector for anything added through other windows or
//    tabs (add/remove/log shows up within a minute even without its own
//    trigger).
setInterval(() => {
    refreshIndices();
    refreshWatchlist();
    refreshLedger();
    refreshPortfolioSummary();
}, REFRESH_MS);
