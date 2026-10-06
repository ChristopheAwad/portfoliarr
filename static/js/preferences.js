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

// ---------------------------------------------------------------------------
// PEOPLE — user accounts for this server (the People card above the
// About card). Same shapes as managePortfolios on purpose: one fetch
// helper per form, one error element per form, and typed-confirmation
// prompts for anything destructive. The SERVER re-checks every rule
// (self-delete, last user, confirming name); the JS simply never shows
// the controls that would be refused — you only see Delete on OTHER
// people's rows, because deleting your own signed-in account is always
// refused.
//
// 401s never reach our handlers: common.js's fetch hook bounces the
// browser to /auth/login the moment the session is gone.
// ---------------------------------------------------------------------------
(function managePeople() {
    const card = document.getElementById("people-card");
    if (!card) return;
    // The signed-in person's id (stamped by the template): the owner of
    // THIS session's rows. It drives which rows get a Delete control.
    const currentUid = Number(card.dataset.currentUid);

    const list = document.getElementById("people-list");
    const form = document.getElementById("people-create");
    const peopleError = document.getElementById("people-error");
    const passwordForm = document.getElementById("password-change");
    const passwordError = document.getElementById("password-error");

    function reportPeople(message) {
        peopleError.textContent = message;
        peopleError.hidden = !message;
    }
    function reportPassword(message) {
        passwordError.textContent = message;
        passwordError.hidden = !message;
    }

    async function request(path, options, onFail) {
        try {
            const response = await fetch(path, options);
            if (!response.ok && response.status !== 401) {
                const payload = await response.json().catch(() => null);
                onFail(payload?.error
                    || `Could not update people (HTTP ${response.status})`);
                return null;
            }
            return response;
        } catch {
            onFail("Could not reach the server.");
            return null;
        }
    }

    async function loadPeople() {
        reportPeople("");
        loadSignupSetting();
        const response = await request("/api/users", { method: "GET" },
            reportPeople);
        if (!response || !response.ok) return;
        const users = await response.json();
        list.replaceChildren();
        for (const user of users) {
            const row = document.createElement("li");
            row.dataset.id = user.id;
            const name = document.createElement("span");
            name.textContent = user.id === currentUid
                ? `${user.username} (you)` : user.username;
            row.append(name);
            // Only OTHER people's rows carry a Delete control — the
            // signed-in account is its own (the server would refuse a
            // self-delete with 400 anyway). Self sign-out is the
            // navbar's Log out button.
            if (user.id !== currentUid) {
                row.append(button("Delete", `Delete ${user.username}`));
            }
            list.append(row);
        }
    }

    function button(text, label, disabled = false) {
        const el = document.createElement("button");
        el.type = "button";
        el.dataset.action = "delete";
        el.textContent = text;
        el.setAttribute("aria-label", label);
        el.disabled = disabled;
        return el;
    }

    // The open sign-up switch: read once per card boot, flip on change.
    // A failed toggle reports in the note line and reverts the checkbox
    // so the picture never lies about the server's state.
    function loadSignupSetting() {
        request("/api/auth/signup-toggle", { method: "GET" },
            reportPeople).then((response) => {
            if (response && response.ok) {
                response.json().then((payload) => {
                    signupToggle.checked = payload.allow === true;
                });
            }
        });
    }

    const signupToggle = document.getElementById("allow-signup");
    signupToggle.addEventListener("change", async () => {
        const on = signupToggle.checked;
        const response = await request("/api/auth/signup-toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ allow: on }),
        }, reportPeople);
        if (response && response.ok) {
            // Re-pin the acknowledged value: a slow boot-time GET could
            // otherwise repaint the stale (pre-click) state.
            signupToggle.checked = on;
            showToast(on ? "Open sign-up is on" : "Open sign-up is off",
                "success");
        } else {
            signupToggle.checked = !on;
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const username = form.elements.username.value.trim();
        const password = form.elements.password.value;
        const response = await request("/api/users", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        }, reportPeople);
        if (response && response.ok) {
            form.reset();
            await loadPeople();
            showToast(`${username} is added`, "success");
        }
    });

    // The typed-confirmation delete: one round trip, one prompt. Both
    // fetches ride the same request() helper as everything else in the
    // card, so a dropped connection reports "Could not reach the
    // server." like every other action.
    list.addEventListener("click", async (event) => {
        const target = event.target.closest("button[data-action]");
        const row = target?.closest("li[data-id]");
        if (!row) return;
        const id = Number(row.dataset.id);
        const response = await request("/api/users", { method: "GET" },
            reportPeople);
        if (!response || !response.ok) return;
        const users = await response.json();
        const person = users.find((item) => item.id === id);
        if (!person) return;
        const typed = await showPrompt({
            title: `Delete ${person.username}?`,
            message: `Type ${person.username} to delete this person and ALL their portfolios, transactions, and watchlist. This cannot be undone.`,
            placeholder: person.username, confirmLabel: "Delete",
            danger: true });
        if (typed === null) return;
        if (typed !== person.username) {
            reportPeople("The typed username does not match.");
            return;
        }
        const response2 = await request(`/api/users/${id}`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: person.username }),
        }, reportPeople);
        if (response2 && response2.status === 204) {
            await loadPeople();
            showToast(`${person.username} is deleted`, "success");
        } else if (response2 && response2.status !== 401) {
            const payload = await response2.json().catch(() => null);
            reportPeople(payload?.error
                || `Could not delete ${person.username}.`);
        }
    });

    passwordForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const current = passwordForm.elements.current_password.value;
        const next = passwordForm.elements.new_password.value;
        const confirm = passwordForm.elements.confirm_password.value;
        if (next !== confirm) {
            reportPassword("The two new passwords do not match.");
            return;
        }
        const response = await request("/api/auth/password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ current_password: current,
                                   new_password: next }),
        }, reportPassword);
        if (response && response.status === 204) {
            passwordForm.reset();
            reportPassword("");
            showToast("Password changed", "success");
        }
    });

    loadPeople();
})();

// ---------------------------------------------------------------------------
// PHONE WIDGETS — the read-only tokens the Android home-screen widget uses
// (#51). The PHONE creates a token when the user connects a widget; this
// card only lists them and offers Revoke. The plaintext token is never
// present here: the server returns it once, to the phone, and stores only
// a hash. Revoking makes the widget show its connect state on the next
// refresh. Same shapes as the cards above: one fetch helper, one error
// line, a toast on success.
// ---------------------------------------------------------------------------
(function manageWidgetTokens() {
    const list = document.getElementById("widget-list");
    const errorEl = document.getElementById("widget-error");
    if (!list) return;

    function report(message) {
        errorEl.textContent = message;
        errorEl.hidden = !message;
    }

    function day(iso) {
        return iso ? iso.slice(0, 10) : "";
    }

    function render(tokens) {
        list.replaceChildren();
        for (const token of tokens) {
            const row = document.createElement("li");
            row.dataset.id = token.id;
            // A watchlist token names no portfolio (#59); label it plainly.
            // A portfolio token whose portfolio row is gone (only via a
            // manual DB edit) still deserves a label.
            const displayName = token.scope === "watchlist"
                ? "Watchlist" : (token.portfolio_name ?? "Portfolio");
            const name = document.createElement("span");
            name.textContent = displayName;
            // Dates are ISO-8601 UTC from the server; only the day part is
            // useful in a management list.
            const meta = document.createElement("small");
            const used = token.last_used_at
                ? `last used ${day(token.last_used_at)}` : "never used";
            meta.textContent = `created ${day(token.created_at)} · ${used}`;
            const revoke = document.createElement("button");
            revoke.type = "button";
            revoke.dataset.action = "revoke";
            revoke.textContent = "Revoke";
            revoke.setAttribute(
                "aria-label", `Revoke widget access to ${displayName}`);
            row.append(name, meta, revoke);
            list.append(row);
        }
    }

    async function load() {
        report("");
        try {
            const response = await fetch("/api/widget/tokens");
            if (!response.ok) {
                report(`Could not load widgets (HTTP ${response.status})`);
                return;
            }
            render(await response.json());
        } catch {
            report("Could not reach the server.");
        }
    }

    list.addEventListener("click", async (event) => {
        const target = event.target.closest("button[data-action='revoke']");
        const row = target?.closest("li[data-id]");
        if (!row) return;
        const confirmed = await showPrompt({
            title: "Revoke this widget?",
            message: "The widget stops updating until you connect it again.",
            confirmLabel: "Revoke", danger: true,
        });
        if (confirmed === null) return;
        report("");
        try {
            const response = await fetch(
                `/api/widget/tokens/${encodeURIComponent(row.dataset.id)}`,
                { method: "DELETE" });
            if (response.status === 204) {
                showToast("Widget access revoked", "success");
                await load();
            } else {
                report(`Could not revoke the widget (HTTP ${response.status})`);
            }
        } catch {
            report("Could not reach the server.");
        }
    });

    load();
})();

// ---------------------------------------------------------------------------
// PERFORMANCE — the Performance card reads /api/perf once and on demand.
// Metric keys are bounded (endpoints, cache outcomes, pages), so this is a
// handful of lists, never per-ticker data.
// ---------------------------------------------------------------------------
(function managePerformance() {
    const card = document.getElementById("perf-card");
    if (!card) return;
    const readout = document.getElementById("perf-readout");
    const errorEl = document.getElementById("perf-error");

    function report(message) {
        errorEl.textContent = message;
        errorEl.hidden = !message;
    }

    function row(label, value) {
        const el = document.createElement("div");
        el.className = "pref-row";
        const name = document.createElement("span");
        name.className = "pref-label";
        name.textContent = label;
        const number = document.createElement("span");
        number.textContent = value;
        el.append(name, number);
        return el;
    }

    function heading(text) {
        const el = document.createElement("p");
        el.className = "perf-heading";
        el.textContent = text;
        return el;
    }

    function byP95(a, b) { return b.p95_ms - a.p95_ms; }
    function ms(value) { return `${Math.round(value)} ms`; }
    function plural(count, word) {
        return `${count} ${word}${count === 1 ? "" : "s"}`;
    }

    function uptime(seconds) {
        if (!Number.isFinite(seconds)) return "—";
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes} min`;
        const hours = Math.floor(minutes / 60);
        return `${hours} h ${minutes % 60} min`;
    }

    function render(payload) {
        readout.replaceChildren();
        readout.append(
            row("Uptime", uptime(payload.uptime_s)),
            row("Requests", String(payload.requests_total ?? "—")),
        );
        const metrics = Array.isArray(payload.metrics) ? payload.metrics : [];

        const pageLoads = metrics
            .filter((item) => item.name === "client.page_load")
            .sort(byP95);
        if (pageLoads.length) {
            readout.append(heading("Page loads"));
            for (const item of pageLoads) {
                readout.append(row(
                    item.tags.page,
                    `${plural(item.count, "load")} · avg ${ms(item.avg_ms)} · ` +
                    `p95 ${ms(item.p95_ms)}`));
            }
        }

        const byEndpoint = new Map();
        for (const item of metrics) {
            if (!item.name.startsWith("http.") || item.count === 0) continue;
            const name = item.name.slice("http.".length);
            const existing = byEndpoint.get(name);
            if (!existing) {
                byEndpoint.set(name, {
                    name, count: item.count, p95_ms: item.p95_ms,
                });
            } else {
                existing.count += item.count;
                existing.p95_ms = Math.max(existing.p95_ms, item.p95_ms);
            }
        }
        const endpoints = [...byEndpoint.values()].sort(byP95).slice(0, 5);
        if (endpoints.length) {
            readout.append(heading("Slowest endpoints"));
            for (const item of endpoints) {
                readout.append(row(
                    item.name,
                    `p95 ${ms(item.p95_ms)} · ${plural(item.count, "call")}`));
            }
        }

        const cacheNames = [
            "market.get_quote", "market.get_history", "market.get_name",
            "market.get_profile", "market.get_financials",
            "market.get_events", "market.get_volume_leaders",
        ];
        const cacheLines = [];
        for (const name of cacheNames) {
            const rows = metrics.filter((item) => item.name === name);
            if (!rows.length) continue;
            let hit = 0;
            let miss = 0;
            let wait = 0;
            let missP95 = 0;
            for (const item of rows) {
                const outcome = item.tags.cache;
                if (outcome === "hit") {
                    hit += item.count;
                } else if (outcome === "miss") {
                    miss += item.count;
                    missP95 = Math.max(missP95, item.p95_ms);
                } else if (outcome === "wait") {
                    wait += item.count;
                }
            }
            const calls = hit + miss + wait;
            const rate = calls ? Math.round((hit / calls) * 100) : 0;
            cacheLines.push(row(name.replace("market.", ""),
                `${rate}% cached · miss p95 ${ms(missP95)}`));
        }
        if (cacheLines.length) {
            readout.append(heading("Market data cache"));
            readout.append(...cacheLines);
        }
    }

    async function load() {
        report("");
        try {
            const response = await fetch("/api/perf");
            if (!response.ok) {
                report(`Could not load performance data ` +
                    `(HTTP ${response.status})`);
                return;
            }
            render(await response.json());
            perfMark("preferences:perf-card");
        } catch {
            report("Could not reach the server.");
        }
    }

    document.getElementById("perf-reload").addEventListener("click", load);
    load();
})();
