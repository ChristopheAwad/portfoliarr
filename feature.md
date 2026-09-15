# Feature: Android app connectivity/refresh hardening

## What

The Android app (a thin WebView wrapper in `android/`) keeps losing the
server after being open/backgrounded for hours. Symptom: a stream of
"Could not reach the server — is it running?" web toasts (every failed
60s poll), the native "Cannot reach server" toast, and — worst case — a
dead/blank WebView that never recovers without manually killing the app.

### Diagnosis (why it happens)

1. **The WebView loads once, never recovers** — `MainActivity.kt` calls
   `loadUrl()` only in `onCreate` (line 48). After hours backgrounded,
   Android may kill the WebView *renderer* (blank screen) or the page's
   fetches fail during Doze / network switch. `onReceivedError` (line 36)
   only fires a Toast and leaves Android's dead error page — no retry,
   ever.
2. **No reconnect logic in the web app** — all three pages poll with a
   blind `setInterval(..., REFRESH_MS)` (main.js:1044, ledger.js:1602,
   stock.js:373). Android throttles background timers; when Doze cuts
   network, every poll fails → toast spam. On return to foreground, data
   stays stale up to 60s. No `visibilitychange`/`online` handlers exist
   anywhere in `static/js/`.
3. **`webView.onPause()` is never called** — WebView JS timers keep
   running while backgrounded, burning battery and generating the
   failure storm.

### Approved design decisions

- **Layer A (web) does freshness, Layer B (Android) does recovery.**
  The Android `onResume` deliberately reloads ONLY when a load failed —
  an unconditional reload would wipe open dialogs/edit forms every time
  the user alt-tabs back; instant-freshness-on-return is the JS layer's
  job.
- **Only main-frame errors set the recovery flag.** Subresource errors
  (a blocked CDN, one failed fetch) must not trigger a full page
  reload.
- One shared `setupAutoRefresh` helper in `common.js` — one
  implementation serves the browser AND the WebView app.

## Files to touch

| File | Change |
|---|---|
| `static/js/common.js` | Add `setupAutoRefresh(refreshFn)`: owns the 60s `setInterval`, pauses while `document.hidden`, fires `refreshFn()` immediately on `visibilitychange` → visible, and on the `online` event (refresh + "Back online" success toast). Verbose teaching comments per house style. |
| `static/js/main.js` (~line 1044) | Replace raw `setInterval` with `setupAutoRefresh` |
| `static/js/ledger.js` (~line 1602) | Same |
| `static/js/stock.js` (~line 373) | Same |
| `android/app/src/main/java/com/portfoliarr/app/MainActivity.kt` | `loadFailed` flag set in `onReceivedError` (main frame only, NOT subresources); `onResume()` calls `webView.onResume()` + reloads the saved URL only when flagged; `onPause()` calls `webView.onPause()`; `onRenderProcessGone` rebuilds the WebView and reloads (fixes blank-screen-after-hours). |
| `tests/test_web_refresh_wiring.py` | NEW meta-test (test_docker.py style): string-checks `common.js` for `visibilitychange`/`online` wiring + `setupAutoRefresh` usage in the three page scripts, so a future refactor can't silently drop the reconnect logic. |

No backend/Python changes anywhere.

## Test plan

The meta-test above is the pytest surface (JS/Kotlin have no pytest
harness); it lands TOGETHER with Layer A so it passes from the first
run. The full suite (`python -m pytest`) must stay green — the change
touches no Python runtime code, so existing tests double as the
regression net.

Manual GUI gate (user verifies):

**Browser:**
1. Dashboard open ~2 min → refresh still happens on the 60s cadence
   (unchanged behavior).
2. Switch to another tab 2+ min, come back → data refreshes instantly
   (no waiting for the next tick).
3. DevTools → Network → Offline, wait for a poll failure, back to
   Online → "Back online" toast + immediate refresh, no toast spam.

**Phone (debug APK rebuilt in Android Studio):**
4. Background the app for hours, return → instant refresh, no
   disconnected state, no toast spam.
5. Airplane-mode ON (wait for the page to notice), OFF → app recovers
   on its own.
6. If a blank WebView is reproducible after long background, it now
   self-heals (renderer rebuild path).

## Status

- [x] Plan approved (both layers + meta-test)
- [x] feature.md written
- [x] Implementation (Layer A → Layer B → meta-test)
- [x] Full suite green (`python -m pytest`) — 408/408
- [ ] GUI gate
- [ ] Commit gate
