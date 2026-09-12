# Feature: PWA Install-to-Homescreen — SCRAPPED

## Outcome
Scrapped on 2026-09-12 without ever working. The full implementation (web app
manifest, service worker, icons, PWA meta tags, root-level routes, and a Caddy
HTTPS sidecar for docker-compose) shipped in commit `d4cd772` and was reverted
in the commit that added this note. Nothing remains in the codebase except
this record.

## What the investigation established (the durable knowledge)
- Chrome only installs a site as a PWA (WebAPK → standalone window, no
  browser chrome) from a **secure context**: HTTPS that the browser actually
  trusts, or localhost. There is no plain-HTTP path, and no manifest or
  service-worker trick around it.
- A service worker is NOT part of Chrome's installability criteria anymore —
  early attempts in this feature (adding one, re-scoping it) were chasing a
  requirement Chrome removed years ago.
- Tapping "Proceed anyway" on an untrusted-certificate warning does NOT
  create trust. Chrome refuses to register service workers behind certificate
  errors, the site stays non-installable, and "Add to Home screen" produces a
  bookmark shortcut that opens a regular browser tab. A self-signed cert only
  works if every device installs the issuing CA into its trust store
  (Android: Settings → Security → Install a certificate → CA certificate).
- `chrome://flags` → "Insecure origins treated as secure" is a per-device,
  per-(host+port) override — explains why one phone can install over plain
  HTTP, but it is a hack, not a fix.

## Why scrapped
Portfoliarr is LAN-only selfhosted. Every route to a trusted HTTPS name costs
something the user rejected: installing our own CA on every phone (per-device
setup), a third-party mesh/tunnel (Tailscale or Cloudflare), or a bought
domain with DNS-01 certificates and split-horizon DNS (money + setup). None
were worth it for homescreen-icon convenience on a hobby app, so the whole
feature was scrapped rather than shipped half-working.

## If this is ever revisited
- Lowest-friction trusted-cert option: add the app to the home server's
  existing Cloudflare Tunnel (real publicly-trusted cert, zero per-device
  setup, works off-LAN — but the hostname is internet-reachable).
- The reverted commit `d4cd772` contains the complete, verified-correct
  artifact set (manifest, icons, SW, routes, meta tags) — the app code was
  never the problem.