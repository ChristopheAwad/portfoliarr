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
// (price_now, value, total_gain/pct, day_gain/pct — raw floats: its job is
// numbers, ours is formatting), so all this section does is place text and
// colours.
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
// Day Gain in transaction and group rows (percentage columns stay
// visible). State persists in localStorage ("hideLedger") so the
// preference survives refreshes. (The portfolio header's eye lives in
// main.js, on the page that owns the portfolio header.)
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

// Ledger sort state — lives OUTSIDE the DOM for the same reason as
// expandedTickers: the tbody rebuilds every poll cycle, so the chosen sort
// must survive it. null = the backend's natural order (most recently
// transacted ticker first). Otherwise {col, dir} where col is one of the
// data-col values the sortable <th>s carry and dir is "asc"|"desc".
let ledgerSort = null;

// Persistent default sort — loaded from localStorage at boot. When no
// user-initiated sort is active (ledgerSort === null), this controls the
// initial sort order. Survives page reloads. {col, dir} or null.
let defaultSort = null;

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
// can validate the saved column key).
try {
    const saved = JSON.parse(localStorage.getItem("ledgerDefaultSort"));
    if (saved && SORT_COLS[saved.col] &&
        (saved.dir === "asc" || saved.dir === "desc")) {
        defaultSort = saved;
    }
} catch { /* first visit or corrupt — keep null */ }

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

    // Price display: in CAD mode the backend converts each row at its
    // STORED fx rate (the buy-date fact — frozen forever); in native
    // mode the display fields simply equal the native facts. The ?? 
    // fallbacks keep old cached payloads harmless.
    const displayCurrency = tx.display_currency || tx.currency;
    const priceCell = document.createElement("td");
    priceCell.className = "num";
    priceCell.textContent =
        `${formatNumber(tx.price_display ?? tx.price)} ${displayCurrency}`;

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
        // The live cells are in display_currency: CAD when the row was
        // converted (value & day gain at the LIVE rate, the cost side at
        // the stored rate — the backend's two-rate contract), native
        // otherwise. Raw floats in, text out, as always.
        valueCell.textContent = `${formatNumber(tx.value)} ${displayCurrency}`;

        // Total gain/pct: the position's whole lifetime since purchase.
        gainCell.textContent = formatSigned(tx.total_gain, displayCurrency);
        gainPctCell.textContent =
            `${tx.total_gain_pct >= 0 ? "+" : ""}${tx.total_gain_pct.toFixed(2)}%`;

        // Day gain/pct: TODAY's move only. The % is the ticker's daily
        // move itself — the same for any position size or currency.
        dayGainCell.textContent = formatSigned(tx.day_gain, displayCurrency);
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

    // --- Actions: edit + delete. They live ONLY on detail rows — a group
    // summary is an aggregate, not a record. Each button carries data-id;
    // the delegated listener looks the transaction up by id in
    // lastTransactions, so these buttons carry no row data themselves.
    const actionsCell = document.createElement("td");
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
    // test locks the 11 data-col keys to exactly these map keys, so a
    // mismatch means a template column gained/lost without its JS cell —
    // it degrades to a blank cell instead of littering the row with the
    // text "undefined" (what append() would make of a missing cell).
    const cells = {
        date: dateCell, type: typeCell, ticker: tickerCell, qty: qtyCell,
        price: priceCell, value: valueCell, total_gain: gainCell,
        total_gain_pct: gainPctCell, day_gain: dayGainCell,
        day_gain_pct: dayPctCell, actions: actionsCell,
    };
    row.append(...ledgerColOrder.map((col) => stampCell(col, cells)));
    return row;
}

// Build ONE group summary row — the collapsed face of one ticker. It
// reuses the same 10 columns, but the numbers are GROUP-level:
//   Qty = NET position: buys add, sells subtract (computed HERE from
//         facts, so the Qty cell stays honest even when the group's
//         quote failed this cycle).
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
// Every live number a GROUP displays comes from list_transactions: the
// backend decorates each row with its TICKER's group fields (group_value,
// group_cost_basis, group_total_gain, group_day_gain + their pcts),
// computed with the same holdings math as /api/portfolio/summary. One
// formula, one implementation — the ledger and the header can't drift.
// This function is the frontend's SINGLE reading point: buildGroupRow
// renders these numbers, and the ledger sorter keys off the very same
// values — so what you see above a column header is exactly what sorting
// by that header uses. Returns a plain object; fields:
//   netQty        Σ BUY.qty − Σ SELL.qty (the one fact-computed field)
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

    const { netQty } = groupSortKeys(txs);
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
        // One display currency per group by construction: the backend
        // converts (or not) per row, and every row of a group shares the
        // same ticker and rate situation. In CAD mode that's "CAD"; in
        // native mode the group's own trading currency.
        const currency = txs[0].display_currency || txs[0].currency;

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

    // The actions column's 11th cell. A group is an aggregate, not a
    // record — editing/deleting INDIVIDUAL transactions belongs to the
    // detail rows — but the group owns exactly ONE action of its own:
    // deleting EVERY transaction of this ticker (the bulk verb). The
    // confirmation that guards it (type-the-ticker, in the delegated
    // listener below) is deliberately stronger than the single row's
    // confirm dialog: this destroys many immutable facts at once, no undo.
    const actionsCell = document.createElement("td");
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
        price: priceCell, value: valueCell, total_gain: gainCell,
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
// ticker's individual transactions as hidden detail rows. The GROUPS
// (ticker summary rows) are what the header-click sort controls — the
// individual detail rows are never re-sorted, always newest-first within
// their group (the backend's order). With no sort clicked the groups keep
// first-appearance order = backend order = most recently transacted ticker
// on top.
function renderLedger(transactions) {
    if (transactions.length === 0) {
        setLedgerMessage("No transactions yet — log your first above.");
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

    // Persist header-click sort as the new default so it survives reload.
    defaultSort = { ...ledgerSort };
    localStorage.setItem("ledgerDefaultSort", JSON.stringify(defaultSort));

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

    // --- Bulk delete (group rows): wipe EVERY transaction of one ticker.
    // Checked BEFORE the single-row delete below, because this button
    // ALSO carries the .delete class (shared styling) — the generic
    // branch would otherwise swallow the click and no-op looking for a
    // data-id the group button doesn't carry.
    const deleteTickerBtn = event.target.closest(".ticker-delete-btn");
    if (deleteTickerBtn) {
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

        try {
            // Same percent-encoding rule as the watchlist path: symbols
            // can contain URL-hostile characters ("^GSPC", "BRK.B") —
            // encode the PATH segment, never the whole URL.
            const response = await fetch(
                `/api/transactions/ticker/${encodeURIComponent(ticker)}`,
                { method: "DELETE" }
            );
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
            refreshLedger();
        } catch (err) {
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
    } catch (err) {
        console.error("delete transaction failed:", err);
        showToast("Could not reach the server — is it running?", "error");
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
// and the watchlist. The display-currency param rides along on every
// fetch, so a toggle click and the 60s poll always agree on the mode.
async function refreshLedger() {
    try {
        const response = await fetch(
            `/api/transactions?${ledgerCurrencyParam()}`
        );
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
        // (same rule as the log form's submit handler).
        refreshLedger();
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
        setClosedSalesMessage("No closed sales yet");
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

async function refreshClosedSales() {
    try {
        const response = await fetch("/api/portfolio/realized");
        // fetch does NOT throw on 4xx/5xx — only on network failure.
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderClosedSales(await response.json());
    } catch (err) {
        console.error("closed sales refresh failed:", err);
        setClosedSalesMessage("Closed sales unavailable");
    }
}


// ---------------------------------------------------------------------------
// BOOT & POLL — the ledger page's own heartbeat. The dashboard used to
// refresh this data on ITS timer; now the data lives here, so the timer
// does too (same 60s cadence, REFRESH_MS from common.js).
// ---------------------------------------------------------------------------

refreshLedger();
refreshClosedSales();
setInterval(() => {
    refreshLedger();
    refreshClosedSales();
}, REFRESH_MS);
