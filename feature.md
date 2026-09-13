# Feature: Privacy eye toggles (portfolio header + ledger header)

## What
Two eye-icon buttons let the user hide sensitive financial values for screen
sharing, like a show-password toggle:

- **Portfolio header** — masks the total value, the day-change pill and the
  total-return pill with `****`
- **Ledger header** — masks Qty, Value, Total Gain and Day Gain in every
  transaction and group row (percentage columns stay visible)

State persists in `localStorage`; the eye icon swaps to eye-off while active.
All UI logic stays in Flask + vanilla JS per the stack rules.

## GUI-verified bug history (why the first implementation was reworked)
String tests can't run a browser, so the user's GUI check surfaced three
deeper bugs after the first round — each root cause now locked by a test:

1. **Icon vanished when ON** — the eye-off SVGs carried inline
   `style="display:none"`; inline styles beat any CSS selector, so the
   `data-hidden="true"` swap rule could never un-hide them. Fix: CSS owns
   visibility (base `.privacy-btn .privacy-eye-off { display: none }` rule,
   no inline styles). Locked by `test_html_eye_off_has_no_inline_display` +
   `test_css_eye_off_hidden_by_default`.
2. **Layout shift when masking** — masked text is far narrower than real
   numbers, and the value row is plain wrapping inline content, so masking
   changed the wrap point (pills jumped inline with the value). Fix:
   geometry locks — measure each span's box and freeze as inline
   `min-width`/`min-height` before overwriting with `****` (value span
   flipped to inline-block: `min-width` is ignored on plain inline).
   Locked by `test_js_locks_masked_geometry`.
3. **Mask self-lifted** — `refreshPortfolioSummary` painted unconditionally
   and the `setInterval` poll kept calling it, overwriting `****` within one
   cycle. Fix: `portfolioMasked()` guard in both paint paths
   (`refreshPortfolioSummary`, `setPortfolioUnavailable`); masked-at-load
   paints the masks at boot. Locked by `test_js_mask_persists_across_refresh`.
4. **Unmask lagged ~1s, then jumped** — locks released before the repaint
   let `****` collapse narrow until the fetch landed. Fix: locks release
   only after real content is painted (`clearPortfolioGeometryLocks`, same
   JS turn as the paint — one layout pass), and a mask-time snapshot
   (`lastPortfolioPaint`) is repainted instantly on unmask so the wait is
   invisible. Locked by `test_js_locks_masked_geometry` +
   `test_js_unmask_restores_cached_values_instantly`.

## Rollback
Revert the commit. Touches only `templates/index.html`, `static/style.css`,
`static/js/main.js`, `tests/test_privacy_toggles.py`, `tests/test_ui_revamp.py`,
`feature.md`.

## Verification
- 31 string-check locks in `tests/test_privacy_toggles.py`; full suite
  **338 passed**.
- GUI confirmed by user: eye visible both themes × both states; no layout
  shift on mask; mask survives the poll; instant, jump-free unmask.