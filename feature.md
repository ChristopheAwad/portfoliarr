# Feature: PWA Install-to-Homescreen

## Problem
The user wants the app to be installable as a PWA — an icon on the homescreen that opens the app in standalone mode (no browser chrome). No offline support needed.

## Status: ROOT CAUSE FOUND — implemented, tests green (316/316), awaiting commit approval
The manifest, icons, meta tags, service worker, and routes were all **correct all along** (verified: icons are real 192×192/512×512 PNGs, `/sw.js` serves 200 with the right MIME type, manifest fields match Chrome's criteria). The bug was never in the code.

### The actual root cause: insecure origin on the phone
The phone reaches the app at `http://<dev-PC-IP>:5000` — plain HTTP over the LAN. Chrome only treats `https://` or `localhost` origins as **secure contexts**, and on an insecure origin it will never install a PWA:
- No automatic prompt (this is Chrome's non-negotiable rule).
- "Add to Home screen" degrades to a bookmark shortcut that opens in a regular Chrome tab — exactly the reported symptom.

feature.md's checklist had one wrong checkmark: "✅ Served over HTTPS (localhost counts)" — true only on the dev machine's own browser, false from the phone's perspective.

### Postmortem of the failed attempts
- **Attempt 1 (added a service worker):** Chrome **no longer requires a service worker** for installability — the requirement was removed from the official install criteria (web.dev "What does it take to be installable?", updated 2024-09-19). Chasing a removed requirement.
- **Attempt 2 (served SW from `/sw.js`):** correct hygiene, but irrelevant — no SW is needed, and the SW wasn't the blocker.
- **Attempt 3 (`"scope": "/"` in manifest):** correct hygiene (the default scope of a manifest in `/static/` would be `/static/`), but the manifest was never the blocker either.
- Also expected, not a bug: modern Chrome Android no longer shows the automatic mini-infobar; install is menu-only.

Chrome's remaining install criteria: HTTPS (✗ on the phone), manifest fields (all ✅), user engagement (✅ — the site has been used 30s+), not already installed.

## The plan (approved)

### Phase 1 — Caddy HTTPS sidecar on the server (the real fix)
- New `Caddyfile` (repo root):
  ```
  {$PWA_SITE_ADDRESS:-https://localhost} {
      tls internal
      reverse_proxy portfoliarr:5000
  }
  ```
  `tls internal` = Caddy runs its own mini certificate authority. Let's Encrypt cannot work here (no public CA can reach a home LAN), so a locally-issued cert is the LAN answer. Caddy mints an IP-SAN cert for whatever `PWA_SITE_ADDRESS` says.
- `docker-compose.yml`: add a `caddy` service — pinned image, host port `9968` → 443, Caddyfile mounted read-only, certs persisted in named volumes, `depends_on: portfoliarr`. The existing `9967:5000` HTTP mapping stays for desktop use. The server's LAN IP goes in `PWA_SITE_ADDRESS` (set in a `.env` next to docker-compose.yml on the server), so the repo file stays generic.
- `tests/test_docker.py`: new meta-tests locking all of the above in both directions. Existing assertions stay untouched.

### Phase 2 — Code polish (small, tests-first)
- `app.py`: `/manifest.json` route serving the same file with the proper `application/manifest+json` MIME type (the hygiene item this file's old "investigate next" list floated; Chrome accepts application/json, this is normalization).
- `base.html`: manifest link → `{{ url_for('manifest') }}`; SW registration gets a `.catch()` so an insecure-origin rejection logs visibly instead of dying silently.
- `sw.js`: add `/manifest.json` to the shell cache list, bump `CACHE_VERSION` to 2.

### Phase 3 — Tests first, then implement
New failing tests in `tests/test_pwa.py` (route status/content-type/body, root link, `.catch`) and `tests/test_docker.py` (Caddy service contracts, Caddyfile contracts). Then implement, then full `python -m pytest` green.

## Verification — CONSTRAINT: user has no desktop access right now
The planned desktop gate (install icon in desktop Chrome at `http://localhost:5000`) is **deferred**. The phone gate is the GUI gate, and it requires the code to reach the server:

1. Tests green → **explicit user yes to commit + push** (phone gate needs it: the server runs the published image, and its checked-out compose files must match).
2. CI builds the image (first push that actually contains the PWA files — everything so far was uncommitted).
3. On the server: `git pull`, create `.env` with `PWA_SITE_ADDRESS=https://<server-ip>`, `docker compose pull && docker compose up -d`.
4. On the phone:
   - **Delete the old homescreen shortcut first** (old shortcuts stay browser-tab mode forever).
   - Visit `https://<server-ip>:9968` → one "connection is not private" warning (untrusted self-signed CA — expected) → Advanced → Proceed anyway.
   - Menu → "Install app" → verify homescreen icon + standalone (no URL bar).
   - Desktop gate can be re-run later when a desktop is available (same code, nothing server-specific about it).

### Known risk + fallback
Chrome Android normally "mints" real WebAPK installs via a Google server that cannot reach a LAN-only site; when unreachable, Chrome falls back to a locally-created shortcut that should still honor standalone — fairly confident, not certain. If standalone still fails after HTTPS:
1. `chrome://flags#unsafely-treat-insecure-origin-as-secure` on the phone (30 seconds, also removes the cert warning),
2. or a real domain via Cloudflare Tunnel / Tailscale for a fully trusted cert.

## Tests
Run: `python -m pytest` from the project root. All existing 301 tests must stay green; new PWA/docker tests added in this feature.