// ---------------------------------------------------------------------------
// PREFERENCES PAGE — reads/writes localStorage for theme and default
// ledger sort. Runs only on /preferences (preferences.html).
// ---------------------------------------------------------------------------

(function initPreferences() {
    const root = document.documentElement;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");

    // --- Theme ---
    const themeSelect = document.getElementById("pref-theme");
    if (themeSelect) {
        // Sync to current state.
        const saved = localStorage.getItem("theme");
        themeSelect.value = saved === "dark" || saved === "light" ? saved : "system";

        themeSelect.addEventListener("change", () => {
            const value = themeSelect.value;
            if (value === "system") {
                localStorage.removeItem("theme");
                root.classList.toggle("dark", mql.matches);
            } else {
                localStorage.setItem("theme", value);
                root.classList.toggle("dark", value === "dark");
            }
            // Refresh chart colors and notify page scripts.
            if (typeof getChartColors === "function") {
                CHART_COLORS = getChartColors();
            }
            document.dispatchEvent(new CustomEvent("themechange",
                { detail: { dark: root.classList.contains("dark") } }));
        });
    }

    // --- Default ledger sort ---
    const sortColSelect = document.getElementById("pref-sort-col");
    const sortDirBtn = document.getElementById("pref-sort-dir-btn");
    const sortDirIcon = document.getElementById("pref-sort-dir-icon");

    if (sortColSelect && sortDirBtn && sortDirIcon) {
        // Load saved default sort.
        let defaultSort = null;
        try {
            const raw = localStorage.getItem("ledgerDefaultSort");
            if (raw) {
                defaultSort = JSON.parse(raw);
                if (!defaultSort.col || !["asc", "desc"].includes(defaultSort.dir)) {
                    defaultSort = null;
                }
            }
        } catch { /* corrupt data — ignore */ }

        // Sync UI.
        function syncUI() {
            if (defaultSort) {
                sortColSelect.value = defaultSort.col;
                sortDirBtn.disabled = false;
                sortDirIcon.textContent = defaultSort.dir === "asc" ? "▲" : "▼";
            } else {
                sortColSelect.value = "";
                sortDirBtn.disabled = true;
                sortDirIcon.textContent = "▼";
            }
        }
        syncUI();

        // Column change.
        sortColSelect.addEventListener("change", () => {
            const col = sortColSelect.value;
            if (!col) {
                defaultSort = null;
                localStorage.removeItem("ledgerDefaultSort");
            } else {
                const dir = col === "ticker" ? "asc" : "desc";
                defaultSort = { col, dir };
                localStorage.setItem("ledgerDefaultSort", JSON.stringify(defaultSort));
            }
            sortDirBtn.disabled = !col;
            syncUI();
        });

        // Direction toggle.
        sortDirBtn.addEventListener("click", () => {
            if (!defaultSort) return;
            defaultSort.dir = defaultSort.dir === "asc" ? "desc" : "asc";
            localStorage.setItem("ledgerDefaultSort", JSON.stringify(defaultSort));
            syncUI();
        });
    }

    // --- Show closed positions ---
    // OFF (default): the ledger hides tickers you hold zero shares of.
    // Stored as the STRING "true"/"false" — the privacy-eye convention:
    // compared with === "true", so an absent key cleanly means OFF and a
    // corrupt value can never mean ON. ledger.js re-reads this key on
    // every render, so a flip here reaches the ledger page (even open in
    // another tab) within one 60s poll — no storage events, no reload.
    const showClosedToggle = document.getElementById("pref-show-closed");
    if (showClosedToggle) {
        showClosedToggle.checked =
            localStorage.getItem("showClosedPositions") === "true";

        showClosedToggle.addEventListener("change", () => {
            localStorage.setItem(
                "showClosedPositions", String(showClosedToggle.checked));
        });
    }
})();

// Portfolios are stored on the server. This page edits the ordered list;
// common.js keeps the browser's selected ID in sync with other tabs.
(function managePortfolios() {
    const list = document.getElementById("portfolio-list");
    const form = document.getElementById("portfolio-create");
    const errorEl = document.getElementById("portfolio-error");
    if (!list || !form) return;

    function report(message) {
        errorEl.textContent = message;
        errorEl.hidden = !message;
    }
    function broadcast() {
        localStorage.setItem("portfolioRevision", String(Date.now()));
    }
    async function mutate(url, method, body) {
        report("");
        try {
            const response = await fetch(url, {
                method, headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => null);
                report(payload?.error || `Could not update portfolio (HTTP ${response.status})`);
                return null;
            }
            const result = response.status === 204 ? true : await response.json();
            await refreshPortfolioList();
            broadcast();
            return result;
        } catch (error) {
            report("Could not reach the server.");
            return null;
        }
    }
    function button(text, action, label, disabled = false) {
        const el = document.createElement("button");
        el.type = "button";
        el.textContent = text;
        el.dataset.action = action;
        el.setAttribute("aria-label", label);
        el.disabled = disabled;
        return el;
    }
    function render() {
        list.replaceChildren();
        knownPortfolios.forEach((portfolio, index) => {
            const row = document.createElement("li");
            row.dataset.id = portfolio.id;
            const name = document.createElement("span");
            name.textContent = portfolio.name;
            row.append(name,
                button("↑", "up", `Move ${portfolio.name} up`, index === 0),
                button("↓", "down", `Move ${portfolio.name} down`,
                       index === knownPortfolios.length - 1),
                button("Rename", "rename", `Rename ${portfolio.name}`),
                button("Delete", "delete", `Delete ${portfolio.name}`,
                       knownPortfolios.length === 1));
            list.append(row);
        });
    }
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const created = await mutate("/api/portfolios", "POST",
            { name: form.elements.name.value });
        if (created) {
            form.reset();
            setActivePortfolio(created.id);
        }
    });
    list.addEventListener("click", async (event) => {
        const target = event.target.closest("button[data-action]");
        const row = target?.closest("li[data-id]");
        if (!row) return;
        const id = Number(row.dataset.id);
        const portfolio = knownPortfolios.find((item) => item.id === id);
        if (!portfolio) return;
        const action = target.dataset.action;
        if (action === "up" || action === "down") {
            await mutate(`/api/portfolios/${id}/move`, "PATCH", { direction: action });
        } else if (action === "rename") {
            const name = await showPrompt({ title: `Rename ${portfolio.name}`,
                message: "Enter a unique portfolio name (up to 60 characters).",
                placeholder: portfolio.name, confirmLabel: "Rename" });
            if (name !== null) await mutate(`/api/portfolios/${id}`, "PATCH", { name });
        } else if (action === "delete") {
            const name = await showPrompt({ title: `Delete ${portfolio.name}?`,
                message: `Type ${portfolio.name} to delete this portfolio and ALL its transactions. This cannot be undone.`,
                placeholder: portfolio.name, confirmLabel: "Delete", danger: true });
            if (name === null) return;
            if (name !== portfolio.name) {
                report("The typed name does not match.");
                return;
            }
            await mutate(`/api/portfolios/${id}`, "DELETE", { name });
        }
    });
    document.addEventListener("portfoliolistchange", render);
    portfolioReady.then(render);
})();
