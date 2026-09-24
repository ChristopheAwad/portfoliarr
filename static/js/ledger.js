// ledger.js — the /ledger page's brain: the transaction ledger (table,
// log/edit form, import panel, display-currency toggle, privacy eye) and
// the Closed sales table.
//
// This code used to live in main.js, back when the dashboard shipped
// everything on one page. The ledger is a records/history surface, not a
// live-glance surface, so it moved to its own page — and its code moved
// with it. Same architecture as before, one page narrower:
//   - Flask serves JSON; this file does ALL rendering (fetch + DOM).
//   - The HTML ships empty <tbody>s; every cycle rebuilds the rows from
//     the API responses (facts + display math from the backend, raw
//     floats; formatting here — the 60s cadence is REFRESH_MS from
//     common.js).
//   - Shared helpers (formatters, paintChange, UI kit) are globals from
//     common.js, loaded before this file by base.html.
// Mutating actions (log/edit/delete/import) refresh only LEDGER data:
// there is no portfolio summary on this page to refresh. The dashboard,
// if open in another tab, picks the change up on its own next poll.

// ---------------------------------------------------------------------------
// TRANSACTION LEDGER — the list of BUY/SELL events, plus the form that logs
// new ones. Same philosophy as the watchlist: the HTML ships an EMPTY
// <tbody>, and this code rebuilds the rows from /api/transactions every
// cycle. The backend returns each row's immutable facts PLUS live math
// (price_now, value, total_gain/pct and day_gain/pct on every row, the
// ticker's group_* aggregates alongside — raw floats: its job is numbers,
// ours is formatting), so all this section does is place text and colours.
// Day gain/pct are rendered only on the group summary row; detail rows
// leave those two columns blank (the individual transaction's daily move
// is redundant noise — see buildTxRow).
//
// Presentation: transactions GROUP BY TICKER — one collapsed summary row
// per ticker (backend-computed holdings math — sells net out), expandable
// to the individual transactions underneath. Which groups are open lives
// in the expandedTickers Set below, because the DOM itself is rebuilt
// every cycle.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
const txForm = document.querySelector("#tx-form");
const txErrorEl = document.querySelector(".tx-error");
const txEditingEl = document.querySelector(".tx-editing");
const txEditingTextEl = txEditingEl.querySelector(".tx-editing-text");
const txCancelBtn = txEditingEl.querySelector(".tx-cancel");
const txSubmitBtn = txForm.querySelector("button[type=submit]");
const ledgerBody = document.querySelector("#ledger-body");
const ledgerHead = document.querySelector(".ledger-table thead");
const txDateInput = txForm.elements.date;

// Ticker autocomplete — the SAME /api/search suggestion dropdown the
// navbar uses, via the shared setupTickerSuggestions factory from
// common.js (loaded before this file). Typing in the Ticker field shows
// suggestions; clicking one (or pressing Enter while the dropdown shows)
// fills the field with the picked symbol AND prefills the latest price
// (prefillPriceForTicker below), so the user flows straight into
// Price → Qty → Log with a real Yahoo symbol, never a typo. The factory
// hides the dropdown after a pick and keeps focus in the field.
//
// Edit mode is naturally inert: the ticker input is disabled there, and a
// disabled input fires no input/keydown events, so no suggestions can
// appear while identity is locked. Same for the deep-link prefill
// (/ledger?ticker=... sets .value programmatically — no events fire).
// The default (no scopeEl / pickTypedTextOnEnter) leaves Enter alone once
// the dropdown closes, so Enter-to-submit still works as it always has.
const txTickerResultsEl = document.querySelector("#tx-ticker-results");
setupTickerSuggestions(txForm.elements.ticker, txTickerResultsEl,
    (symbol) => {
        txForm.elements.ticker.value = symbol;
        prefillPriceForTicker();
    });

// Today or an empty date means the live quote (today has no settled close
// yet); any other date means the recorded close on or before it, so a past
// transaction is priced by the market's actual print — weekends and
// holidays fall back to the prior trading day.
function priceQuoteUrl(symbol) {
    const date = txDateInput.value;
    return (date && date !== todayLocalISO())
        ? `/api/quote/${encodeURIComponent(symbol)}?date=${encodeURIComponent(date)}`
        : `/api/quote/${encodeURIComponent(symbol)}`;
}

// Prefill the Price field with the picked ticker's LATEST price, from the
// lightweight /api/quote/<symbol> endpoint (the get_quote dict WITHOUT the
// heavy name fetch — see app.py). Called from BOTH ways a ticker lands in
// the field: the suggestion dropdown's onPick above, and the deep-link
// prefill (/ledger?ticker=... from the stock page's "Log Transaction"
// button). One helper, one behavior, so the two paths can never drift.
//
// Why native currency: the ledger stores native facts (price, currency)
// and converts at display time — so the number dropped HERE must be what
// the security actually trades at (Yahoo's quoted price), not a CAD
// conversion. The submit route derives the currency from the same quote.
//
// Why clear first: a stale price from a PRIOR pick must never sit under a
// different ticker. We clear at pick time and only fill on a successful,
// still-current fetch — a failed fetch leaves the field EMPTY (honest;
// the price input is required, so the user types it, and the backend
// re-validates the ticker at submit anyway). Quiet on failure — a no-fill
// needs no error toast, console.error is the audit trail.
//
// The stale-guard: while this fetch is in flight the user may have picked
// a second ticker OR changed the date. Rare, but a SLOWER EARLIER reply
// must not overwrite a newer pick or a newer date — same rule as the
// search dropdown's stale-guard, applied to the fill.
function prefillPriceForTicker() {
    const symbol = txForm.elements.ticker.value.trim().toUpperCase();
    if (!symbol) return; // nothing picked — nothing to fetch
    const requestedDate = txDateInput.value; // the date this reply prices

    txForm.elements.price.value = ""; // never leave a prior pick's price
    fetch(priceQuoteUrl(symbol))
        .then((response) => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then((quote) => {
            if (txForm.elements.ticker.value.trim().toUpperCase() !== symbol ||
                txDateInput.value !== requestedDate) {
                return; // stale reply — a newer pick or date superseded this one
            }
            // Keep the FULL quote price for the ledger (autofillPrice), and
            // show only 2 decimals in the field — the app's "store accurate,
            // paint 2 decimals" rule applied to the form. toFixed(2) is safe
            // here: the value is a display, the accurate number rides in
            // autofillPrice, and the submit handler picks it up untouched.
            autofillPrice = quote.price;
            priceEdited = false;
            txForm.elements.price.value = quote.price.toFixed(2);
        })
        .catch((err) => {
            console.error("price prefill failed:", err);
        });
}

// The ledger's display currency, read fresh from the toggle on EVERY
// fetch (not cached in a variable — the checkbox is the single source of
// truth, so clicks, polls and refetches can never disagree).
//   unchecked (default) → ?currency=CAD    everything in CAD
//   checked             → ?currency=NATIVE USD rows back in USD
// This is the ONLY endpoint the toggle touches: the portfolio total and
// the chart are computed CAD-always server-side. The toggle starts
// unchecked on every page load (session-only, by design).
const usdNativeToggle = document.querySelector("#usd-native-toggle");

// Privacy toggle — the ledger's eye. Masks Qty, Value, Total Gain and
// Day Gain on GROUP rows (percentage columns stay visible). Detail rows
// show no Day Gain to mask. State persists in localStorage ("hideLedger")
// so the preference survives refreshes. (The portfolio header's eye lives
// in main.js, on the page that owns the portfolio header.)
const hideLedgerToggle = document.getElementById("hide-ledger-toggle");

// Restore persisted privacy state from localStorage. Strings "true"/"false"
// — same pattern as the portfolio toggle's restore in main.js.
if (hideLedgerToggle) {
    const hidden = localStorage.getItem("hideLedger") === "true";
    hideLedgerToggle.dataset.hidden = hidden;
    hideLedgerToggle.title = hidden
        ? "Show holding values" : "Hide holding values";
    hideLedgerToggle.setAttribute("aria-label", hideLedgerToggle.title);
    hideLedgerToggle.setAttribute("aria-pressed", String(hidden));
}

function ledgerCurrencyParam() {
    return usdNativeToggle && usdNativeToggle.checked
        ? "currency=native"
        : "currency=CAD";
}

// Edit-mode state + the last fetched rows. Both live OUTSIDE the DOM —
// same reasoning as expandedTickers below: the tbody rebuilds every 60s,
// so form mode and data must not depend on rows staying put.
//   editingTxId === null  -> the form is in "log a new transaction" mode
//   editingTxId === 7     -> the form is editing transaction #7
let editingTxId = null;
// The freshest GET result. Action clicks (edit/delete) look rows up HERE,
// by id — never by scraping the row's cell text back into data.
let lastTransactions = [];

// True once a refresh cycle fails AFTER rows have painted. The cached
// lastTransactions then still describe a quote the page has stopped
// trusting, so every later render path (header sort, column drag) must keep
// suppressing live cells and Quick Sell actions until a fresh fetch
// succeeds. Without this, a sort after a failed poll would resurrect the
// stale actions markLedgerUnavailable just removed.
let ledgerStale = false;

// The Price field's accurate-value state — the split between what the EYE
// sees and what the LEDGER stores:
//   autofillPrice — the FULL-precision price behind a cosmetic 2-decimal
//                   display (a programmatic fill on the field, or the exact
//                   stored fact in edit mode). null = no fill in effect.
//   priceEdited   — true once the USER types in the Price field. Their
//                   typed value then wins at submit; only an untouched
//                   display falls back to autofillPrice.
// Why the split at all: the ledger's permanent rule is "store the accurate
// number, paint 2 decimals" — a filled-in price field must obey the same
// rule. A `toFixed(2)` value dropped straight into the input would ROUND the
// stored fact (a problem for multi-decimal instruments), and `input
// type="number"` has no display-vs-value split of its own — so this is the
// mechanism that gives the field one. Programmatic `.value` sets never fire
// the `input` event, which is exactly why the listener below can be the
// reliable "did the user touch it?" signal.
let autofillPrice = null;
let priceEdited = false;
// The dirty signal: any real keystroke/editor gesture in the Price field
// marks it edited. A refreshLedger() re-render never touches the form, so
// this flag cannot be reset by the page's 60s poll — only by a programmatic
// fill (which sets it back to false) or exitEditMode.
txForm.elements.price.addEventListener("input", () => { priceEdited = true; });

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
    cell.colSpan = 12; // one cell spanning the whole table (must match the
                       // <th> count, incl. the actions column)
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

// Ledger sort state — lives OUTSIDE the DOM for the same reason as
// expandedTickers: the tbody rebuilds every poll cycle, so the chosen sort
// must survive it. null = the backend's natural order (most recently
// transacted ticker first). Otherwise {col, dir} where col is one of the
// data-col values the sortable <th>s carry and dir is "asc"|"desc".
let ledgerSort = null;

// Which data-col values identity keys off. The sortable columns (matching
// the data-col attrs in index.html) map to the matching key of the object
// groupSortKeys returns — so sorting by a column reads the VERY value the
// table already shows, never a re-derivation that could drift.
const SORT_COLS = {
    ticker: "ticker",
    qty: "netQty",
    value: "value",
    total_gain: "totalGain",
    total_gain_pct: "totalGainPct",
    day_gain: "dayGain",
    day_gain_pct: "dayGainPct",
};

// Load default sort from localStorage (must come after SORT_COLS so we
// can validate the saved column key). Preferences owns this value —
// loaded once at boot, then read-only; header clicks change only
// ledgerSort for the current page session. {col, dir} or null.
const defaultSort = (() => {
    try {
        const saved = JSON.parse(localStorage.getItem("ledgerDefaultSort"));
        if (saved && SORT_COLS[saved.col] &&
            (saved.dir === "asc" || saved.dir === "desc")) {
            return saved;
        }
    } catch { /* first visit or corrupt — fall through to null */ }
    return null;
})();

// Paint (or clear) the ▲/▼ indicator + aria-sort on the sortable <th>s.
// ▲ = ascending, ▼ = descending — a plain, honest statement of the current
// sort direction, for both text (ticker) and numeric columns alike. All
// sortable headers except ticker are numeric.
function renderSortIndicators() {
    document.querySelectorAll("thead .sortable").forEach((th) => {
        const col = th.dataset.col;
        th.classList.toggle("active", !!ledgerSort && ledgerSort.col === col);
        th.setAttribute("aria-sort",
            !ledgerSort || ledgerSort.col !== col
                ? "none"
                : ledgerSort.dir === "asc" ? "ascending" : "descending");
        const indicator = th.querySelector(".sort-indicator");
        if (indicator) indicator.remove();
        if (ledgerSort && ledgerSort.col === col) {
            const span = document.createElement("span");
            span.className = "sort-indicator";
            span.textContent = ledgerSort.dir === "asc" ? "▲" : "▼";
            th.append(span);
        }
    });
}

// --- Reorderable columns: the ONE source of column order ------------------
// The template's static <th> row declares the ledger's columns (every
// header carries a data-col). This code reads that row ONCE here — the
// DOM is ready because the page scripts load at the end of <body> — and
// from then on, ledgerColOrder is the order everything consults:
//   - the drag logic reorders this array when you drop a header,
//   - the <th> row itself is physically re-ordered to match,
//   - both row builders append their cells in this order.
// Reordering a column is therefore a change to ONE array, never an edit
// scattered across builders.

// The template's default order, read live so adding a column to the HTML
// (with its data-col) is the ONLY step needed — no JS list to keep in sync.
const ledgerDefaultOrder =
    [...ledgerHead.querySelectorAll("th")].map((th) => th.dataset.col);

// The ACTIVE order. Starts as the template default; the boot block below
// may replace it with a saved order from localStorage. Lives OUTSIDE the
// DOM for the same reason as ledgerSort: the tbody rebuilds every poll
// cycle, and both builders read this array on every rebuild.
let ledgerColOrder = [...ledgerDefaultOrder];

// Header TEXT per data-col, read once at boot from the same <th> row —
// the mobile card layout's labels come from HERE, not a second hardcoded
// list, so a card line's caption is always the exact text the desktop
// table shows for that column. (Read at boot: the ▲/▼ indicator spans
// don't exist yet — the strip below makes that harmless even if a sort
// was somehow already painted. The actions header's text is "" by design;
// its card-mode presentation is handled purely in CSS.)
const ledgerColLabels = {};
for (const th of ledgerHead.querySelectorAll("th")) {
    ledgerColLabels[th.dataset.col] = th.textContent.replace(/[▲▼]/g, "").trim();
}

// Restore a saved order, if one exists AND is still valid. Validation is
// deliberately strict: the saved value must be a PERMUTATION of the live
// headers — same keys, same count, no duplicates — with actions last
// (it's pinned by design). Anything else (absent, corrupt, or saved by an
// older column set after the template gains/loses a column) silently falls
// back to the default order rather than rendering a broken table.
try {
    const saved = JSON.parse(localStorage.getItem("ledgerColOrder"));
    const isValid =
        Array.isArray(saved) &&
        saved.length === ledgerDefaultOrder.length &&
        new Set(saved).size === saved.length &&
        saved.every((col) => ledgerDefaultOrder.includes(col)) &&
        saved[saved.length - 1] === "actions";
    if (isValid) ledgerColOrder = saved;
} catch {
    // getItem returned null (first visit) → JSON.parse(null) → null.length
    // throws → we land here and keep the default order. Exactly right.
}

// Move the actual <th> elements into ledgerColOrder's order. append() on
// an EXISTING child moves it (DOM nodes can't be in two places at once),
// so re-appending the headers one by one reorders the row in place. The
// elements carry everything with them — data-col, tabindex, aria-sort —
// and the sort listeners live on the <thead> (delegated), so click-to-sort
// works identically no matter where a header sits.
function paintLedgerColOrder() {
    const headRow = ledgerHead.querySelector("tr");
    for (const col of ledgerColOrder) {
        headRow.append(headRow.querySelector(`th[data-col="${col}"]`));
    }
}
paintLedgerColOrder(); // boot: apply the saved (or default) order

// Stamp ONE ledger cell with its column identity: data-col (the machine
// key, identical to its <th>'s) and data-label (the human caption, read
// from that header's text at boot). Desktop rendering ignores both — the
// ≤600px card layout's CSS reads them to re-layout cells BY MEANING and
// to caption each fact line, so a card label can never drift from the
// column it represents. Unknown col → the same blank-cell fallback as
// before, stamped anyway so the cell count never changes.
function stampCell(col, cells) {
    const cell = cells[col] ?? document.createElement("td");
    cell.dataset.col = col;
    cell.dataset.label = ledgerColLabels[col] ?? "";
    return cell;
}

// Build ONE transaction detail row — 11 data cells plus a trailing actions
// cell (edit/delete), extracted from renderLedger so the grouped view can
// stamp out one per transaction under
// its group's summary row. Facts are always present; live cells
// (value/gain) exist only when the backend could quote that ticker —
// otherwise they gap-fill to "—".
//
// Day Gain / Day Gain % are deliberately NOT painted here: a single
// transaction is a record, not a position — its "today's move" is noise
// (the ticker's daily move is identical on every row, and the dollar
// amount is just that move scaled by one lot's qty). Those two belong to
// the group summary row, which measures the NET position. The cells still
// exist (stampCell and the 12-column contract need them) but render empty;
// on phones the whole line is removed by style.css's card-mode rule.
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

    // Price display: in CAD mode the backend converts each row at its
    // STORED fx rate (the buy-date fact — frozen forever); in native
    // mode the display fields simply equal the native facts. The ?? 
    // fallbacks keep old cached payloads harmless.
    const displayCurrency = tx.display_currency || tx.currency;
    const priceCell = document.createElement("td");
    priceCell.className = "num";
    priceCell.textContent =
        `${formatNumber(tx.price_display ?? tx.price)} ${displayCurrency}`;
    const feeCell = document.createElement("td");
    feeCell.className = "num";
    feeCell.textContent = tx.fee === null || tx.fee === undefined
        ? "—" : `${formatNumber(tx.fee)} ${tx.currency}`;

    // --- Live cells (present only when decorated) ---
    const hasLive = !ledgerStale && tx.price_now !== undefined;

    const valueCell = document.createElement("td");
    valueCell.className = "num ledger-live";
    const gainCell = document.createElement("td");
    gainCell.className = "num ledger-live";
    const gainPctCell = document.createElement("td");
    gainPctCell.className = "num ledger-live";
    // Day gain/pct cells exist to keep the row aligned with the 12 columns
    // (and the group rows that DO show daily returns) but stay empty here.
    // Deliberately NO .ledger-live class: markLedgerUnavailable() stamps "—"
    // into every .ledger-live cell on a failed refresh, which would leak a
    // dash into a column the detail row never shows.
    const dayGainCell = document.createElement("td");
    dayGainCell.className = "num";
    const dayPctCell = document.createElement("td");
    dayPctCell.className = "num";

    if (hasLive) {
        // The live cells are in display_currency: CAD when the row was
        // converted (value at the LIVE rate, the cost side at the stored
        // rate — the backend's two-rate contract), native otherwise. Raw
        // floats in, text out, as always.
        valueCell.textContent = `${formatNumber(tx.value)} ${displayCurrency}`;

        // Total gain/pct: the position's whole lifetime since purchase.
        gainCell.textContent = formatSigned(tx.total_gain, displayCurrency);
        gainPctCell.textContent =
            `${tx.total_gain_pct >= 0 ? "+" : ""}${tx.total_gain_pct.toFixed(2)}%`;

        // Green for gains, red for losses — the shared pos/neg classes.
        // Each pair colours independently: a position can be up overall
        // (green Total) while today is red (neg Day). Day gain rides on
        // the group row only, so only the Total pair is coloured here.
        for (const [cell, value] of [
            [gainCell, tx.total_gain],
            [gainPctCell, tx.total_gain_pct],
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
    }

    // Privacy masking: when the ledger privacy toggle is active, replace
    // Qty, Value, and Total Gain with asterisks. Percentage columns
    // (Total Gain %, and the group row's Day Gain %) stay visible — they
    // show relative performance without revealing absolute amounts. Day
    // Gain is not masked here: the detail row never shows it.
    if (hideLedgerToggle && hideLedgerToggle.dataset.hidden === "true") {
        qtyCell.textContent = "****";
        if (tx.fee !== null && tx.fee !== undefined) feeCell.textContent = "****";
        valueCell.textContent = "****";
        gainCell.textContent = "****";
        // Remove pos/neg coloring from masked cells
        gainCell.classList.remove("pos", "neg");
    }

    // --- Actions: edit + delete. They live ONLY on detail rows — a group
    // summary is an aggregate, not a record. Each button carries data-id;
    // the delegated listener looks the transaction up by id in
    // lastTransactions, so these buttons carry no row data themselves.
    const actionsCell = document.createElement("td");
    // Keyboard parity: the detail row's ticker is plain text (unlike the
    // group row's ticker LINK), so nothing in this row is focusable while
    // the buttons are visibility:hidden — and hidden buttons are not in
    // the tab order. This cell is the tab stop that makes the CSS
    // `.ledger-row:focus-within` reveal fire, after which Tab reaches the
    // now-visible edit/delete buttons.
    actionsCell.tabIndex = 0;
    const editBtn = document.createElement("button");
    editBtn.className = "tx-action-btn edit";
    editBtn.append(icon("pencil"));
    editBtn.title = "Edit this transaction";
    editBtn.dataset.id = tx.id;
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "tx-action-btn delete";
    deleteBtn.append(icon("trash"));
    deleteBtn.title = "Delete this transaction";
    deleteBtn.dataset.id = tx.id;
    actionsCell.append(editBtn, deleteBtn);

    // Append in ledgerColOrder order — the same array the <th> row is
    // ordered by. Cells are keyed by data-col and pulled from the shared
    // array, so reordering a column stays a one-array change; no builder
    // edit. The ?? blank-cell fallback is defensive only: the template
    // test locks the 12 data-col keys to exactly these map keys, so a
    // mismatch means a template column gained/lost without its JS cell —
    // it degrades to a blank cell instead of littering the row with the
    // text "undefined" (what append() would make of a missing cell).
    const cells = {
        date: dateCell, type: typeCell, ticker: tickerCell, qty: qtyCell,
        price: priceCell, fee: feeCell, value: valueCell, total_gain: gainCell,
        total_gain_pct: gainPctCell, day_gain: dayGainCell,
        day_gain_pct: dayPctCell, actions: actionsCell,
    };
    row.append(...ledgerColOrder.map((col) => stampCell(col, cells)));
    return row;
}

// Build ONE group summary row — the collapsed face of one ticker. It
// reuses the same columns, but the numbers are GROUP-level:
//   Qty = NET position: buys add, sells subtract (computed HERE from
//         facts, so the Qty cell stays honest even when the group's
//         quote failed this cycle).
//   Price = the backend's group_avg_cost: the current open position's
//         average acquisition price (average-cost pool — a partial sale
//         does NOT reprice the shares that remain). Facts-only, so it
//         paints even when the live quote failed; null (flat position)
//         reads as "—".
//   Value / Total Gain / Day Gain (+ pcts) = the backend's group
//         aggregates (groupSortKeys reads them off the group's first
//         row): holdings math with SELLS NETTED OUT — value is the net
//         position × live price, and the cost basis is buys paid minus
//         sells recouped. (The old "sum BUY rows only" rule is retired:
//         it froze Value/Total/Day when a SELL was logged and made the
//         ledger disagree with the portfolio header.) SELL details stay
//         visible when the group is expanded — each row keeps its own
//         live math.
//   Total Gain % = null when the cost basis is ≤ 0 (SELL-only or
//         fully-sold-at-profit group) → "—" instead of a meaningless %.
//   Day Gain % = the ticker's daily move itself (price-level, identical
//         for every row — see the decoration comments in app.py).
// Decoration happens per UNIQUE ticker server-side, so within a group
// either every row has live math or none — no partial-group ambiguity.
//
// --- Group aggregates (read from the backend, not re-derived) -----------
// Every number a GROUP displays comes from list_transactions: the
// backend decorates each row with its TICKER's group fields (group_avg_cost,
// group_value, group_cost_basis, group_total_gain, group_day_gain + their
// pcts), computed with the same holdings math as /api/portfolio/summary
// (and an average-cost replay for the price). One formula, one
// implementation — the ledger and the header can't drift.
// This function is the frontend's SINGLE reading point: buildGroupRow
// renders these numbers, and the ledger sorter keys off the very same
// values — so what you see above a column header is exactly what sorting
// by that header uses. Returns a plain object; fields:
//   netQty        Σ BUY.qty − Σ SELL.qty (the one fact-computed field)
//   avgCost       the backend's group_avg_cost — null when the position
//                 is flat (or a legacy reply omitted it)
//   value         the backend's group_value (live)
//   totalGain     the backend's group_total_gain (live)
//   dayGain       the backend's group_day_gain (live)
//   totalGainPct  null when the backend sent none (cost basis ≤ 0) —
//                 the row shows "—" and sorts LAST
//   dayGainPct    the ticker's daily move — null when the group's quote
//                 failed this cycle
function groupSortKeys(txs) {
    // Qty stays fact-computed: it needs no price, so it survives an
    // unquoted cycle while every live cell degrades to "—".
    let netQty = 0;
    for (const tx of txs) {
        netQty += tx.transaction_type === "BUY" ? tx.qty : -tx.qty;
    }
    // The group fields ride on EVERY row of the ticker (all rows share
    // the same quote), so the first row speaks for the whole group.
    // ?? null keeps the sorter's "unavailable sorts last" contract when
    // the backend sent no group fields at all (unquoted ticker).
    const first = txs[0] || {};
    return {
        netQty,
        avgCost: first.group_avg_cost ?? null,
        value: first.group_value,
        totalGain: first.group_total_gain,
        totalGainPct: first.group_total_gain_pct ?? null,
        dayGain: first.group_day_gain,
        dayGainPct: first.group_day_gain_pct ?? null,
    };
}

function buildGroupRow(ticker, txs) {
    const row = document.createElement("tr");
    row.className = "ledger-group";
    row.dataset.ticker = ticker; // click-handler hook: find by meaning

    // --- Facts ---
    const dateCell = document.createElement("td");
    // The expand/collapse chevron: the .caret wrapper span stays EXACTLY
    // as it was (CSS rotates .caret for the open state) — only what's
    // INSIDE it changed, from a text glyph to the SVG chevron.
    const caret = document.createElement("span");
    caret.className = "caret";
    caret.append(icon("caret"));
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

    const { netQty, avgCost } = groupSortKeys(txs);
    const qtyCell = document.createElement("td");
    qtyCell.className = "num";
    qtyCell.textContent = formatNumber(netQty, 4);

    // One display currency for the whole group — read ONCE and shared by
    // the Price cell and the live cells below, so the two render paths
    // can never label the same row with different currencies.
    // (Backend construction keeps the group homogeneous — except for a
    // mixed-currency unquoted group, which sends avg_cost null anyway.)
    const currency = txs[0].display_currency || txs[0].currency;

    // The parent Price is the backend's average acquisition price for
    // the CURRENT open position (average-cost pool of stored facts — a
    // partial sale does not reprice remaining shares). Painted OUTSIDE
    // the hasLive branch below: it needs no quote, so a Yahoo failure
    // still shows the average while Value/Gain degrade to "—". Null =
    // flat or mixed-currency position (or legacy reply) → "—"; the
    // check is explicit so a legitimate 0 is never mistaken for missing.
    const priceCell = document.createElement("td");
    priceCell.className = "num";
    if (avgCost === null) {
        priceCell.textContent = "—";
    } else {
        priceCell.textContent = `${formatNumber(avgCost)} ${currency}`;
    }
    const feeCell = document.createElement("td"); // no single fee for a group

    // --- Live cells (all-or-nothing per group, like the detail rows) ---
    const hasLive = !ledgerStale && txs[0].price_now !== undefined;

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
        // The group's currency was read once above (one label source for
        // Price and every live cell). In CAD mode that's "CAD"; in
        // native mode the group's own trading currency.

        // The same aggregates groupSortKeys reads for sorting — render
        // them here so the table and the sort order can never disagree.
        const { value, totalGain, totalGainPct, dayGain, dayGainPct } =
            groupSortKeys(txs);

        valueCell.textContent = `${formatNumber(value)} ${currency}`;
        gainCell.textContent = formatSigned(totalGain, currency);
        gainPctCell.textContent = totalGainPct === null
            ? "—"
            : `${totalGainPct >= 0 ? "+" : ""}${totalGainPct.toFixed(2)}%`;
        dayGainCell.textContent = formatSigned(dayGain, currency);
        dayPctCell.textContent =
            `${dayGainPct >= 0 ? "+" : ""}${dayGainPct.toFixed(2)}%`;

        // Colour the sums with the same pos/neg rule as the detail rows —
        // with one guard: a null pct gets no colour, because "—" is
        // neither green nor red.
        for (const [cell, cellValue] of [
            [gainCell, totalGain],
            [gainPctCell, totalGainPct],
            [dayGainCell, dayGain],
            [dayPctCell, dayGainPct],
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

    // Privacy masking: when the ledger privacy toggle is active, replace
    // Qty, Value, Total Gain, and Day Gain with asterisks. Percentage
    // columns (Total Gain %, Day Gain %) stay visible — they show relative
    // performance without revealing absolute amounts.
    if (hideLedgerToggle && hideLedgerToggle.dataset.hidden === "true") {
        qtyCell.textContent = "****";
        valueCell.textContent = "****";
        gainCell.textContent = "****";
        dayGainCell.textContent = "****";
        // Remove pos/neg coloring from masked cells
        gainCell.classList.remove("pos", "neg");
        dayGainCell.classList.remove("pos", "neg");
    }

    // The actions column's last cell. A group is an aggregate, not a
    // record — editing/deleting INDIVIDUAL transactions belongs to the
    // detail rows — but the group owns two actions of its own:
    //   1. Quick Sell — prepare (never submit) a full-position SELL of this
    //      ticker in the form above. Only offered when the group is
    //      actually long (net qty above the flat tolerance) AND quoted this
    //      cycle: there are no owned shares to sell in a closed or short
    //      group, and an unquoted ticker has no honest price to prefill.
    //      The price is the NATIVE quote (price_now), never the CAD-
    //      converted display — the ledger stores native facts.
    //   2. Delete-all — the bulk verb. Its type-the-ticker confirmation
    //      (delegated listener below) is deliberately stronger than the
    //      single row's confirm dialog: it destroys many immutable facts
    //      at once, no undo.
    const actionsCell = document.createElement("td");
    const priceNow = txs[0].price_now;
    const canSell =
        !ledgerStale && netQty > 1e-9
        && Number.isFinite(priceNow) && priceNow > 0;
    if (canSell) {
        const sellBtn = document.createElement("button");
        // type="button" is defensive only: the button lives in a table
        // cell, not a form — but an explicit type can never accidentally
        // submit anything.
        sellBtn.type = "button";
        sellBtn.className = "tx-action-btn ticker-sell-btn";
        sellBtn.textContent = "Sell";
        sellBtn.title = `Sell all ${ticker} shares`;
        sellBtn.dataset.ticker = ticker; // which group this button is
        actionsCell.append(sellBtn);
    }
    const deleteTickerBtn = document.createElement("button");
    // Classes: .tx-action-btn.delete borrows the detail rows' delete
    // styling; .ticker-delete-btn is the JS hook that keeps the delegated
    // listener's bulk branch from being confused with the single-row one.
    deleteTickerBtn.className = "tx-action-btn delete ticker-delete-btn";
    deleteTickerBtn.append(icon("trash"));
    deleteTickerBtn.title = `Delete ALL ${ticker} transactions`;
    deleteTickerBtn.dataset.ticker = ticker; // which group this button is
    actionsCell.append(deleteTickerBtn);

    // Same keyed-append as buildTxRow above — the two builders MUST order
    // cells identically, and sourcing the order from the same
    // ledgerColOrder array is what guarantees they can never drift.
    const cells = {
        date: dateCell, type: typeCell, ticker: tickerCell, qty: qtyCell,
        price: priceCell, fee: feeCell, value: valueCell, total_gain: gainCell,
        total_gain_pct: gainPctCell, day_gain: dayGainCell,
        day_gain_pct: dayPctCell, actions: actionsCell,
    };
    row.append(...ledgerColOrder.map((col) => stampCell(col, cells)));
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
    // The stored price is the EXACT fact — never a live quote (edit mode
    // keeps the submitted value, as it always has). autofillPrice carries
    // full precision so the later submit saves the untouched row unchanged;
    // only the DISPLAY rounds to 2 decimals (the app's paint rule). Mark
    // it untouched: the user hasn't edited this fill yet.
    autofillPrice = tx.price;
    priceEdited = false;
    txForm.elements.price.value = tx.price.toFixed(2);
    txForm.elements.qty.value = tx.qty;
    txForm.elements.fee.value = tx.fee ?? "";
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
    // The accurate backing dies with the fill it described: after a reset
    // the field is empty, so a leftover autofillPrice must never resurface
    // on the NEXT row's submit (and priceEdited resets too — the empty
    // field is a fresh, untouched slate).
    autofillPrice = null;
    priceEdited = false;
    txDateInput.value = todayLocalISO(); // reset() restores HTML defaults;
                                         // the JS-set date must be re-applied
    txSubmitBtn.textContent = "Log";
    txEditingEl.hidden = true;
    txErrorEl.hidden = true;
}

// Prepare the form for a full-position SELL of one ticker. This is the
// group row's Quick Sell action — it FILLS the existing form and stops.
// The user reviews the prepared facts and presses Log, so the ledger never
// records a sale the user did not see.
//
// Why the facts are re-derived HERE rather than read off the button: a
// click can race the 60s poll, and the button carries only the ticker. The
// cached transaction rows are the freshest successful fetch, so the exact
// net quantity (buys add, sells subtract — the same fold as groupSortKeys)
// and the exact native price_now come from there. If the group is no longer
// long or no longer quoted, the helper does nothing — a stale or vanished
// button can never prepare an impossible sale.
//
// exitEditMode() runs FIRST so the prepared sale is a NEW transaction
// (POST), not a correction of whatever row was open before (PUT). It also
// resets the form, re-enables the ticker input, restores "Log", and hides
// old errors in one place.
//
// Precision: the field displays two decimals (the ledger's paint rule) but
// autofillPrice keeps the exact quote — the same display-vs-stored split
// the dropdown and deep-link prefills use. A user edit still wins at submit
// (priceEdited flips on the input event; this programmatic fill leaves it
// false).
function prepareFullSale(ticker, txs) {
    // groupSortKeys is the documented single source for the group's exact
    // net quantity — reusing it here means the prepared sale can never
    // drift from the number the row displays.
    const { netQty } = groupSortKeys(txs);
    const livePrice = txs[0] ? txs[0].price_now : undefined;
    if (!(netQty > 1e-9) || !Number.isFinite(livePrice) || !(livePrice > 0)) {
        return; // position gone or quote missing — nothing to prepare
    }

    exitEditMode();
    txForm.elements.ticker.value = ticker;
    txForm.elements.date.value = todayLocalISO();
    txForm.elements.qty.value = netQty;
    txForm.elements.fee.value = "";
    txForm.elements.type.value = "SELL";
    autofillPrice = livePrice;
    priceEdited = false;
    txForm.elements.price.value = livePrice.toFixed(2);
    // The group row can sit far below the form — bring the prepared form
    // to the user instead of leaving the fill off-screen.
    txForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// Rebuild the tbody: one collapsed summary row per ticker, followed by that
// ticker's individual transactions as hidden detail rows. The GROUPS
// (ticker summary rows) are what the header-click sort controls — the
// individual detail rows are never re-sorted, always newest-first within
// their group (the backend's order). With no sort clicked the groups keep
// first-appearance order = backend order = most recently transacted ticker
// on top.
function renderLedger(transactions) {
    if (transactions.length === 0) {
        setLedgerMessage(
            "No transactions yet — log your first buy in the form above, " +
            "or paste an import.");
        return;
    }

    // On first render, if no user-initiated sort is active, apply the
    // persistent default. This ensures the ledger opens sorted even before
    // the user clicks a header.
    if (ledgerSort === null && defaultSort) {
        ledgerSort = { ...defaultSort };
    }

    // Keep the ▲/▼ header indicators in step with the sort state.
    renderSortIndicators();

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

    // Sorting an array is stable in modern JS: equal keys keep their
    // current (insertion) order, so a tie between two groups falls back to
    // the backend's newest-first order. Baked into sortGroupRows below.
    const groupRows = sortGroupRows(groups);

    // Hide closed positions unless the user opted in (Preferences →
    // "Show closed positions"). Read HERE, per render — the poll rebuilds
    // the tbody every 60s, so a flip on /preferences reaches this page
    // within one cycle, no event wiring needed. netQty is the SAME fact-
    // arithmetic sum (Σ buys − sells, groupSortKeys) the group row's Qty
    // cell shows — it needs no price, so it works for unquoted and
    // delisted tickers too, whose live group fields are absent. The keep
    // condition is a TOLERANCE, not !== 0: fractional qtys (the
    // importer's 6-decimal flagship) leave binary residue — 0.1 + 0.2 −
    // 0.3 is 5.55e-17 — and an exact check would resurrect sold-out
    // fractional tickers as phantom "0.0000" rows. A real short
    // (negative netQty) is an active position and stays.
    // Presentation only: the stored transactions (the Closed sales cost
    // basis) are never touched.
    const showClosed =
        localStorage.getItem("showClosedPositions") === "true";
    const visibleGroups = showClosed
        ? groupRows
        : groupRows.filter(({ txs }) =>
              Math.abs(groupSortKeys(txs).netQty) > 1e-9);

    if (visibleGroups.length === 0) {
        // Transactions exist (the early return above handled a truly
        // empty ledger) but every position is fully sold and hidden.
        // Say exactly that and point at the switch's home — "No
        // transactions yet" here would be a lie about WHY it's empty.
        setLedgerMessage(
            "No open positions — enable 'Show closed positions' in Preferences.");
        return;
    }

    for (const { ticker, txs } of visibleGroups) {
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

// Turn a ticker→rows Map into a sorted array of {ticker, txs} entries.
// When ledgerSort is null (no header clicked) the original insertion order
// is preserved. When a sort IS active, each group's sort value comes from
// the SAME groupSortKeys numbers buildGroupRow renders. Unavailable values
// (null — SELL-only Total Gain %, or an unquoted group's live cells) sort
// LAST in both directions, so "—" never floats to the top of a gain sort.
function sortGroupRows(groups) {
    const entries = [...groups.entries()].map(([ticker, txs]) => ({
        ticker,
        txs,
        key: groupSortKeys(txs),
    }));

    if (!ledgerSort) return entries;

    const sortKey = SORT_COLS[ledgerSort.col];
    const dir = ledgerSort.dir === "asc" ? 1 : -1;

    entries.sort((a, b) => {
        let av = sortKey === "ticker"
            ? a.ticker.toLowerCase()
            : a.key[sortKey];
        let bv = sortKey === "ticker"
            ? b.ticker.toLowerCase()
            : b.key[sortKey];

        // Ticker is text; all the other sortable keys are numbers.
        if (sortKey === "ticker") {
            if (av === bv) return 0;
            return av < bv ? -dir : dir;
        }

        // Numeric path: null/undefined (unavailable) or NaN (an unquoted
        // group's live sums never materialized) always sorts last, whatever
        // the direction. Strip the sign for the magnitude comparison below.
        if (typeof av === "number" && Number.isNaN(av)) av = null;
        if (typeof bv === "number" && Number.isNaN(bv)) bv = null;
        const aNull = av === null || av === undefined;
        const bNull = bv === null || bv === undefined;
        if (aNull && bNull) return 0;
        if (aNull) return 1;  // a last
        if (bNull) return -1; // b last
        return (av - bv) * dir;
    });
    return entries;
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

    // ...or on the group's own DELETE button: the actions listener below
    // owns that click, and toggling on top of a bulk delete would both
    // flicker the rows and fight the confirmation dialog. Guarding on
    // the whole .tx-action-btn family (not just delete) keeps this true
    // for any future group-level action button too.
    if (event.target.closest(".tx-action-btn")) return;

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

// Header-click sorting: ONE delegated listener on the <thead>, the same
// delegation rationale as everything else — the headers are static (never
// rebuilt), but consolidating here keeps all sort handling in one place
// and avoids duplicating the enter/exit logic on each <th>. Clicking a
// sortable header sorts, and clicking the SAME column again flips the
// direction (asc ⇄ desc); clicking a new column starts it on that
// column's default direction — ticker begins A→Z (asc), numeric columns
// begin biggest-first (desc, the finance convention).
function applyLedgerSort(col) {
    if (!SORT_COLS[col]) return; // non-sortable header — nothing to do

    if (ledgerSort && ledgerSort.col === col) {
        // Same column again → flip direction: asc ⇄ desc.
        ledgerSort = { col, dir: ledgerSort.dir === "asc" ? "desc" : "asc" };
    } else {
        // New column → minimal re-sort from the cached rows, no refetch.
        const defaultDir = col === "ticker" ? "asc" : "desc";
        ledgerSort = { col, dir: defaultDir };
    }

    renderLedger(lastTransactions);
}
ledgerHead.addEventListener("click", (event) => {
    const th = event.target.closest("th.sortable");
    if (th) applyLedgerSort(th.dataset.col);
});
// Keyboard parity for the tabindex="0" headers: Enter or Space triggers
// the same sort as a click (native buttons would do this sight-unseen, but
// the <th> is a plain element — accessibility is our job here).
ledgerHead.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const th = event.target.closest("th.sortable");
    if (th) {
        event.preventDefault(); // don't scroll the page on Space
        applyLedgerSort(th.dataset.col);
    }
});

// --- Drag-to-reorder columns ----------------------------------------------
// HTML5 drag & drop on the <th>s. Two behaviors share one header and the
// browser splits them for us: a quick click (down + up, no movement) fires
// click → column sort above; holding and MOVING fires dragstart → reorder
// here. dragstart can never result from a plain click, so the two never
// collide — no threshold logic needed.
//
// Honest limitation: HTML5 drag events are pointer-only — keyboard users
// keep the default (or last saved) order and full click-to-sort, which
// stays keyboard-reachable via the tabindex headers above.

// Which column is being dragged. Module-level so dragstart's record and
// dragend's cleanup (different listeners, different elements) share it.
let draggedCol = null;

// Commit a drop: splice the dragged column to its new slot, then make
// everything agree — the state array, the <th> row, localStorage, and the
// visible tbody (re-rendered NOW; waiting up to 60s for the next poll
// would feel broken).
function moveLedgerColumn(sourceCol, targetCol, before) {
    if (sourceCol === targetCol) return; // dropped on itself — no-op

    const from = ledgerColOrder.indexOf(sourceCol);
    const at = ledgerColOrder.indexOf(targetCol);
    if (from === -1 || at === -1) return; // unknown keys — never reorder

    // Splice semantics: remove the source first, THEN recompute the
    // insert index from the target's shifted position. Everything right
    // of the removed source slides left by one, so the target's index
    // after removal is the honest insertion point; `before` selects the
    // target's slot (0 = land on its left) vs the one after it (1).
    ledgerColOrder.splice(from, 1);
    const insertAt = ledgerColOrder.indexOf(targetCol) + (before ? 0 : 1);
    ledgerColOrder.splice(insertAt, 0, sourceCol);

    // actions can never end up mid-table: it's not draggable (so never a
    // source) and never a drop target (its <th> gets no drag listeners),
    // so nothing can be spliced around it.

    // Persist. Best-effort on purpose: some privacy modes throw on
    // localStorage writes, and a failed SAVE should never sink a
    // successful REORDER — the order still lives in memory (and the DOM)
    // for this session; it just won't survive a reload. Mirrors the
    // try/catch around the boot-time read.
    try {
        localStorage.setItem("ledgerColOrder", JSON.stringify(ledgerColOrder));
    } catch { /* persistence unavailable — session-only order */ }
    paintLedgerColOrder();
    renderLedger(lastTransactions);
}

for (const th of ledgerHead.querySelectorAll("th")) {
    // The actions column is PINNED last: skip it entirely — no draggable
    // attribute, no listeners — so it can neither be dragged nor dropped on.
    if (th.dataset.col === "actions") continue;
    th.draggable = true;

    th.addEventListener("dragstart", (event) => {
        draggedCol = th.dataset.col;
        th.classList.add("dragging");
        // Firefox refuses to start a drag with an empty dataTransfer —
        // setting the payload is also a natural place to announce the
        // dragged column to whatever the OS does with drag data.
        event.dataTransfer.setData("text/plain", draggedCol);
        event.dataTransfer.effectAllowed = "move";
    });

    th.addEventListener("dragover", (event) => {
        // Guard + REQUIRED preventDefault: dragover is what licences a
        // drop — without preventDefault here, the drop event never fires.
        if (!draggedCol || draggedCol === th.dataset.col) return;
        event.preventDefault();
        // Left half of the header = "insert before it", right half =
        // "insert after it" — clientX against the header's own box, so a
        // child element (the ▲/▼ indicator span) can't skew the split.
        const rect = th.getBoundingClientRect();
        const before = event.clientX < rect.left + rect.width / 2;
        th.classList.toggle("drop-before", before);
        th.classList.toggle("drop-after", !before);
    });

    th.addEventListener("dragleave", () => {
        th.classList.remove("drop-before", "drop-after");
    });

    th.addEventListener("drop", (event) => {
        event.preventDefault();
        const rect = th.getBoundingClientRect();
        const before = event.clientX < rect.left + rect.width / 2;
        th.classList.remove("drop-before", "drop-after");
        moveLedgerColumn(draggedCol, th.dataset.col, before);
    });

    // dragend fires whether the drop succeeded, was cancelled, or missed
    // every target — the one place cleanup is guaranteed. Stray indicator
    // classes are cleared here too, not just on dragleave/drop.
    th.addEventListener("dragend", () => {
        draggedCol = null;
        th.classList.remove("dragging");
        ledgerHead.querySelectorAll("th").forEach((t) => {
            t.classList.remove("drop-before", "drop-after");
        });
    });
}

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

    // --- Quick Sell (group rows): prepare a full-position SELL in the form
    // above. Checked BEFORE the delete branches below for the same reason
    // the bulk delete is checked before the single-row delete: the action
    // is a prepare-only fill, and its click must never fall through to any
    // destructive branch. The ticker's CURRENT cached rows are the source
    // of the exact quantity and price (prepareFullSale rechecks both).
    const sellBtn = event.target.closest(".ticker-sell-btn");
    if (sellBtn) {
        const ticker = sellBtn.dataset.ticker;
        const txs = lastTransactions.filter((t) => t.ticker === ticker);
        prepareFullSale(ticker, txs);
        return;
    }

    // --- Bulk delete (group rows): wipe EVERY transaction of one ticker.
    // Checked BEFORE the single-row delete below, because this button
    // ALSO carries the .delete class (shared styling) — the generic
    // branch would otherwise swallow the click and no-op looking for a
    // data-id the group button doesn't carry.
    const deleteTickerBtn = event.target.closest(".ticker-delete-btn");
    if (deleteTickerBtn) {
        const epoch = portfolioEpoch();
        const ticker = deleteTickerBtn.dataset.ticker;
        // The confirmation's wording comes from the CACHED rows: how many
        // facts this action would erase. The backend stays the real
        // authority (0 matched → its 404), same division of labour as
        // every other action here.
        const txs = lastTransactions.filter((t) => t.ticker === ticker);
        if (txs.length === 0) return;

        // THE GATE. showPrompt resolves null when the user cancels; any
        // other answer must equal the ticker after the same trim+upper
        // normalization the backend applies. A mismatch (or a bare
        // OK/cancel reflex) aborts — typing the exact ticker is the
        // deliberate, conscious step that single-row deletes don't need.
        const typed = await showPrompt({
            title: `Delete ALL ${ticker} transactions?`,
            message: `Type ${ticker} to confirm deleting ALL ${txs.length} ` +
                     `${ticker} transactions. This cannot be undone.`,
            placeholder: ticker,
            confirmLabel: "Delete all",
            danger: true,
        });
        if (typed === null) return;
        if (typed.trim().toUpperCase() !== ticker) {
            showToast(
                `Cancelled — you typed "${typed.trim()}", not ${ticker}.`,
                "error"
            );
            return;
        }
        if (epoch !== portfolioEpoch()) return;

        try {
            // Same percent-encoding rule as the watchlist path: symbols
            // can contain URL-hostile characters ("^GSPC", "BRK.B") —
            // encode the PATH segment, never the whole URL.
            const response = await fetch(
                `/api/transactions/ticker/${encodeURIComponent(ticker)}${portfolioQuery()}`,
                { method: "DELETE" }
            );
            if (epoch !== portfolioEpoch()) return;
            // 204 = all rows gone. 404 = another window beat us to it —
            // refreshing either way shows the stored truth.
            if (!response.ok && response.status !== 404) {
                throw new Error(`HTTP ${response.status}`);
            }
            // The deleted ticker's group state is now meaningless — drop
            // it so a future ticker reuse starts collapsed (the Set
            // survives rebuilds, so a stale entry would linger).
            expandedTickers.delete(ticker);
            // If the form was editing one of THIS ticker's transactions,
            // its target is gone — drop back to log mode rather than
            // submitting into a 404 (same rule as the row delete).
            const editingTx = lastTransactions.find(
                (t) => t.id === editingTxId);
            if (editingTx && editingTx.ticker === ticker) exitEditMode();
            refreshLedgerViews();
        } catch (err) {
            if (epoch !== portfolioEpoch()) return;
            console.error("delete ticker transactions failed:", err);
            showToast("Could not reach the server — is it running?", "error");
        }
        return;
    }

    // --- Delete: confirm, DELETE, refresh. Not our click? Done.
    const deleteBtn = event.target.closest(".tx-action-btn.delete");
    if (!deleteBtn) return;
    const tx = lastTransactions.find(
        (t) => t.id === Number(deleteBtn.dataset.id));
    if (!tx) return;
    const epoch = portfolioEpoch();

    // Deletion is immediate and unrecoverable — the backend keeps no trash
    // bin. showConfirm (awaited — this listener is async) resolves once the
    // user picks a side; false means they backed out.
    if (!(await showConfirm({
        title: "Delete transaction?",
        message: `Delete ${tx.transaction_type} of ${formatNumber(tx.qty, 4)} ` +
                 `${tx.ticker} @ ${formatNumber(tx.price)} on ` +
                 `${tx.transaction_date}?`,
        confirmLabel: "Delete",
        danger: true,
    }))) {
        return;
    }
    if (epoch !== portfolioEpoch()) return;

    try {
        const response = await fetch(`/api/transactions/${tx.id}${portfolioQuery()}`, {
            method: "DELETE",
        });
        if (epoch !== portfolioEpoch()) return;
        // 204 = gone. 404 = already gone (another window beat us to it) —
        // refreshing either way shows the stored truth, watchlist rule.
        if (!response.ok && response.status !== 404) {
            throw new Error(`HTTP ${response.status}`);
        }
        // If THIS row was open in the form, its edit target is gone —
        // drop back to log mode rather than submitting into a 404.
        if (editingTxId === tx.id) exitEditMode();
        refreshLedgerViews();
    } catch (err) {
        if (epoch !== portfolioEpoch()) return;
        console.error("delete transaction failed:", err);
        showToast("Could not reach the server — is it running?", "error");
    }
});

// Degrade live cells to "—" when a refresh cycle fails entirely but fact
// rows from an earlier cycle are still on screen (mirrors the watchlist's
// markWatchlistUnavailable).
//
// The rendered Quick Sell actions go with them: each one was built from a
// live quote, and that quote is exactly what this failure invalidated.
// Leaving them clickable would let the user prepare a sale at a price the
// page just stopped trusting. Removing the buttons removes only the
// unclicked action — a form the user already prepared holds editable input
// awaiting review and is deliberately left untouched. Edit and both delete
// actions remain (they need no live data), and the next successful render
// recreates eligible Sell actions on its own.
function markLedgerUnavailable() {
    ledgerStale = true;
    ledgerBody.querySelectorAll(".ledger-live").forEach((cell) => {
        cell.textContent = "—";
        cell.classList.remove("pos", "neg");
    });
    ledgerBody.querySelectorAll(".ticker-sell-btn").forEach((button) => {
        button.remove();
    });
}

// One ledger refresh cycle: GET -> rebuild rows. The backend's quote cache
// means at most every other cycle touches Yahoo — same rhythm as the chips
// and the watchlist. The display-currency param rides along on every
// fetch, so a toggle click and the 60s poll always agree on the mode.
async function refreshLedger() {
    if (!currentPortfolioId()) return;
    const epoch = portfolioEpoch();
    try {
        const response = await fetch(
            `/api/transactions${portfolioQuery()}&${ledgerCurrencyParam()}`
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const transactions = await response.json();
        if (epoch !== portfolioEpoch()) return;
        lastTransactions = transactions; // cache for action-click lookups
        ledgerStale = false; // fresh quotes — live cells and Sell may return
        renderLedger(transactions);
    } catch (err) {
        if (epoch !== portfolioEpoch()) return;
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

// The toggle: one click = one immediate ledger refetch (waiting up to a
// minute for the next poll would make the checkbox feel broken). Nothing
// else refreshes — the summary and chart are CAD in both modes.
usdNativeToggle.addEventListener("change", () => refreshLedger());

// Form submit: the ONLY way rows are born (POST) or corrected (PUT).
// preventDefault stops the browser's native full-page form POST — we want
// fetch + partial update, not a navigation. The backend remains the real
// validator: its named 400/404 messages are shown inline, its 200/201 is
// the trigger to re-fetch.
txForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentPortfolioId()) return;
    const epoch = portfolioEpoch();
    const destination = portfolioQuery();

    // FormData collects every named input's current value; fromEntries
    // turns it into a plain object. Numbers arrive as STRINGS from inputs
    // — Number() converts them to real JSON numbers before shipping.
    const fields = Object.fromEntries(new FormData(txForm));
    // The price question had a split: the field SHOWS 2 decimals of the
    // accurate value (autofillPrice), but the ledger must store full
    // precision. Resolution rule: if the user EDITED the field, their typed
    // value is the fact; if it was left untouched after a programmatic
    // fill (pick / deep-link / edit-mode), the exact autofillPrice is. When
    // there was never a fill (autofillPrice null — the user typed a price
    // without ever picking a ticker), the typed value is the fact.
    const price = priceEdited
        ? Number(fields.price)
        : (autofillPrice ?? Number(fields.price));
    const body = {
        ticker: String(fields.ticker || "").trim().toUpperCase(),
        date: fields.date,
        price: price,
        qty: Number(fields.qty),
        fee: fields.fee === "" ? null : Number(fields.fee),
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
            ? await fetch(`/api/transactions${destination}`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(body),
              })
            : await fetch(`/api/transactions/${editingTxId}${destination}`, {
                  method: "PUT",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                      date: body.date,
                      price: body.price,
                      qty: body.qty,
                      fee: body.fee,
                      type: body.type,
                  }),
              });
        if (epoch !== portfolioEpoch()) return;
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
        refreshLedgerViews();
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

// Changing the date re-prices an auto-filled ticker, because Date and Price
// are two facts about one event and must agree. Three guards:
//   - edit mode: the row's stored price is the recorded fact, never a
//     fresh lookup of a possibly different day;
//   - priceEdited: a price the user typed wins over any auto-fill;
//   - empty ticker: there is nothing to price yet.
txDateInput.addEventListener("change", () => {
    if (editingTxId !== null) return;
    if (priceEdited) return;
    if (!txForm.elements.ticker.value.trim()) return;
    prefillPriceForTicker();
});

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
    prefillPriceForTicker();
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
let previewPortfolioId = null;
let previewText = null;
importTextEl.addEventListener("input", () => {
    previewPortfolioId = null;
    importCommitBtn.hidden = true;
});

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
    if (!currentPortfolioId()) return;
    const epoch = portfolioEpoch();
    const text = importTextEl.value;
    try {
        const response = await fetch(`/api/transactions/import/preview${portfolioQuery()}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
        });
        if (epoch !== portfolioEpoch() || text !== importTextEl.value) return;
        if (!response.ok) {
            const err = await response.json().catch(() => null);
            showImportError(
                err?.error || `Preview failed (HTTP ${response.status})`
            );
            return;
        }
        const payload = await response.json();
        if (epoch !== portfolioEpoch() || text !== importTextEl.value) return;
        renderImportReport(payload);
        previewPortfolioId = currentPortfolioId();
        previewText = text;
        importCommitBtn.hidden = payload.valid_count === 0;
        importCommitBtn.textContent =
            `Import ${payload.valid_count} row` +
            `${payload.valid_count === 1 ? "" : "s"}`;
    } catch (err) {
        if (epoch !== portfolioEpoch()) return;
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
    if (!currentPortfolioId() || previewPortfolioId !== currentPortfolioId() ||
        previewText !== importTextEl.value) {
        importCommitBtn.hidden = true;
        showImportError("Preview again for this portfolio before importing.");
        return;
    }
    const epoch = portfolioEpoch();
    importCommitBtn.hidden = true;
    try {
        const response = await fetch(`/api/transactions/import/commit${portfolioQuery()}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: importTextEl.value }),
        });
        if (epoch !== portfolioEpoch()) return;
        if (!response.ok) {
            const err = await response.json().catch(() => null);
            showImportError(
                err?.error || `Import failed (HTTP ${response.status})`
            );
            return;
        }
        const payload = await response.json();
        if (epoch !== portfolioEpoch()) return;
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
        // (same rule as the log form's submit handler).
        refreshLedgerViews();
    } catch (err) {
        if (epoch !== portfolioEpoch()) return;
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
if (hideLedgerToggle) {
    hideLedgerToggle.addEventListener("click", () => {
        const hidden = hideLedgerToggle.dataset.hidden === "true";
        hideLedgerToggle.dataset.hidden = !hidden;
        hideLedgerToggle.title = hidden
            ? "Hide holding values" : "Show holding values";
        // Same screen-reader state sync as the portfolio button.
        hideLedgerToggle.setAttribute("aria-label", hideLedgerToggle.title);
        hideLedgerToggle.setAttribute("aria-pressed", String(!hidden));
        localStorage.setItem("hideLedger", !hidden);
        // Re-render the ledger with current data to apply/remove masks.
        // Only when data exists: a failed ledger fetch leaves
        // lastTransactions empty, and re-rendering would overwrite the
        // honest "Ledger unavailable" message with "No transactions yet"
        // — a lie about WHY the table is empty. Either state self-
        // corrects on the next poll.
        if (lastTransactions.length) {
            renderLedger(lastTransactions);
        }
    });
}


// ---------------------------------------------------------------------------
// CLOSED SALES — the realized result of every SELL, in CAD. One row per
// sell transaction, fed by GET /api/portfolio/realized (an average-cost
// replay the backend recomputes per request — numbers in, text out, the
// same renderer rule as the ledger above). Unlike the ledger's per-row
// gain, which compares the sell price to YESTERDAY'S close (market
// noise), this is proceeds vs what the sold shares actually COST:
// performance.
//
// Degraded rows (a missing fx_rate anywhere in the position's history)
// keep their facts but show "—" for the CAD fields, with the reason on
// hover; the header total goes "—" too rather than summing a partial
// picture and letting it look complete.
// ---------------------------------------------------------------------------

const closedSalesBody = document.querySelector("#closed-sales-body");
const realizedTotalEl = document.querySelector("#realized-total");

// The expand/collapse pair: the card HEADER is the toggle control and the
// table's wrapper is what opens and closes. The collapsed state ships in
// the HTML (`hidden` on the wrapper) — so "collapsed by default on every
// page load" needs no boot-time JS at all; this code only ever REVERSES
// the shipped state. The realized-total span lives in the header, outside
// the wrapper, so it stays visible in both states by construction.
const closedSalesToggle = document.querySelector("#closed-sales-toggle");
const closedSalesWrap = document.querySelector("#closed-sales-wrap");

// One toggle for both input paths (click + keyboard). Reading the wrapper's
// hidden BEFORE flipping: "is it showing right now?" → close it. The .open
// class rotates the header's .caret; aria-expanded keeps the
// screen-reader state truthful (it must mirror hidden, never drift).
function toggleClosedSales() {
    const open = closedSalesWrap.hidden;
    closedSalesWrap.hidden = !open;
    closedSalesToggle.classList.toggle("open", open);
    closedSalesToggle.setAttribute(
        "aria-expanded", String(!closedSalesWrap.hidden));
}
closedSalesToggle.addEventListener("click", () => toggleClosedSales());
closedSalesToggle.addEventListener("keydown", (event) => {
    // A role="button" DIV responds to no keys natively — Enter and Space
    // are wired by hand, the sortable-<th> kit's exact pattern
    // (preventDefault stops Space from scrolling the page).
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    toggleClosedSales();
});

// Cell captions for phone card mode, read from the thead ONCE at boot —
// the same rule as the ledger's ledgerColLabels: the caption is the
// header's own text, so the two can never drift apart. Keyed by the
// data-cs-col each <th> declares (the table's single column contract).
const closedSalesLabels = {};
for (const th of document.querySelectorAll(".closed-sales-table th")) {
    closedSalesLabels[th.dataset.csCol] = th.textContent.trim();
}

// Stamp a cell with its two identity attributes: data-cs-col (which
// column it belongs to — how card mode's CSS finds it) and data-label
// (the caption card mode draws beside the value). Mirrors the ledger's
// stampCell; the empty-state message cell deliberately gets neither
// (it's structure, not a fact).
function stampSaleCell(cell, col) {
    cell.dataset.csCol = col;
    cell.dataset.label = closedSalesLabels[col] ?? "";
    return cell;
}

// Same wipe-and-rebuild message row as the ledger's setLedgerMessage,
// spanning the closed-sales table's 8 columns.
function setClosedSalesMessage(text) {
    closedSalesBody.textContent = "";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 8; // must match the <th> count (8 data-cs-col columns)
    cell.className = "empty-state";
    cell.textContent = text;
    row.append(cell);
    closedSalesBody.append(row);
}

function renderClosedSales(payload) {
    // Header total first. null means at least one row's CAD math was
    // unknowable — summing the rest would look complete and be wrong.
    realizedTotalEl.textContent = payload.total_realized === null
        ? "—"
        : formatSigned(payload.total_realized, "CAD");
    realizedTotalEl.classList.toggle(
        "pos", payload.total_realized !== null && payload.total_realized >= 0);
    realizedTotalEl.classList.toggle(
        "neg", payload.total_realized !== null && payload.total_realized < 0);

    closedSalesBody.textContent = "";
    if (payload.rows.length === 0) {
        setClosedSalesMessage(
            "No closed sales yet — the realized result of each SELL " +
            "appears here.");
        return;
    }
    for (const sale of payload.rows) {
        const row = document.createElement("tr");
        row.className = "closed-sales-row";

        // Ticker is a link to the detail page — same rule as the ledger's
        // ticker cells and the watchlist rows: real anchors give native
        // middle-click / new-tab for free.
        const tickerCell = stampSaleCell(document.createElement("td"),
                                         "ticker");
        const tickerLink = document.createElement("a");
        tickerLink.href = `/stock/${encodeURIComponent(sale.ticker)}`;
        tickerLink.textContent = sale.ticker;
        tickerCell.append(tickerLink);

        const nameCell = stampSaleCell(document.createElement("td"), "name");
        nameCell.className = "closed-sales-name";
        nameCell.textContent = sale.name || "—";

        const soldCell = stampSaleCell(document.createElement("td"), "sold");
        soldCell.textContent = sale.transaction_date;

        const qtyCell = stampSaleCell(document.createElement("td"), "qty");
        qtyCell.className = "num";
        qtyCell.textContent = formatNumber(sale.qty, 4);

        // Native facts stay native (the ledger's price convention):
        // avg cost and sell price show in the security's own currency,
        // only the realized columns are CAD.
        const avgCostCell = stampSaleCell(document.createElement("td"),
                                          "avg_cost");
        avgCostCell.className = "num";
        avgCostCell.textContent =
            `${formatNumber(sale.avg_cost)} ${sale.currency}`;

        const priceCell = stampSaleCell(document.createElement("td"),
                                        "sell_price");
        priceCell.className = "num";
        priceCell.textContent =
            `${formatNumber(sale.price)} ${sale.currency}`;

        const realizedCell = stampSaleCell(document.createElement("td"),
                                           "realized");
        realizedCell.className = "num";
        if (sale.realized === null) {
            realizedCell.textContent = "—";
            if (sale.degraded) realizedCell.title = sale.degraded;
        } else {
            realizedCell.textContent = formatSigned(sale.realized, "CAD");
            realizedCell.classList.toggle("pos", sale.realized >= 0);
            realizedCell.classList.toggle("neg", sale.realized < 0);
        }

        const pctCell = stampSaleCell(document.createElement("td"),
                                      "realized_pct");
        pctCell.className = "num";
        if (sale.realized_pct === null) {
            pctCell.textContent = "—";
            if (sale.degraded) pctCell.title = sale.degraded;
        } else {
            const sign = sale.realized_pct >= 0 ? "+" : "";
            pctCell.textContent = `${sign}${sale.realized_pct.toFixed(2)}%`;
            pctCell.classList.toggle("pos", sale.realized_pct >= 0);
            pctCell.classList.toggle("neg", sale.realized_pct < 0);
        }

        row.append(tickerCell, nameCell, soldCell, qtyCell, avgCostCell,
                   priceCell, realizedCell, pctCell);
        closedSalesBody.append(row);
    }
}

// Mutation paths change the ledger AND the realized picture it feeds
// (a SELL edits both a row and the closed-sales card). Refreshing only
// one leaves the other stale until the next 60s poll. One call keeps
// the two views on the same truth.
function refreshLedgerViews() {
    refreshLedger();
    refreshClosedSales();
}

async function refreshClosedSales() {
    if (!currentPortfolioId()) return;
    const epoch = portfolioEpoch();
    try {
        const response = await fetch(`/api/portfolio/realized${portfolioQuery()}`);
        // fetch does NOT throw on 4xx/5xx — only on network failure.
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (epoch !== portfolioEpoch()) return;
        renderClosedSales(data);
    } catch (err) {
        if (epoch !== portfolioEpoch()) return;
        console.error("closed sales refresh failed:", err);
        setClosedSalesMessage("Closed sales unavailable");
    }
}


// ---------------------------------------------------------------------------
// BOOT & POLL — the ledger page's own heartbeat. The dashboard used to
// refresh this data on ITS timer; now the data lives here, so the timer
// does too (same 60s cadence, REFRESH_MS from common.js).
// ---------------------------------------------------------------------------

portfolioReady.then(() => {
    refreshLedger();
    refreshClosedSales();
});
document.addEventListener("portfoliochange", () => {
    exitEditMode();
    expandedTickers.clear();
    lastTransactions = [];
    previewPortfolioId = null;
    previewText = null;
    importCommitBtn.hidden = true;
    importReportEl.hidden = true;
    setLedgerMessage("Loading portfolio...");
    setClosedSalesMessage("Loading portfolio...");
    refreshLedger();
    refreshClosedSales();
});
// setupAutoRefresh owns the interval and wires visibility/online events
// so the page refreshes instantly when the user returns (see common.js).
setupAutoRefresh(() => {
    refreshLedger();
    refreshClosedSales();
});
