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
})();
