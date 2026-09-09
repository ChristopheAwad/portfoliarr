# Feature: Dark Mode

## Problem
No dark mode exists. The app is light-only with no way to switch themes.

## Plan

### 1. CSS: Add `.dark` variable overrides
Add a `.dark` selector after `:root` that redefines all color tokens for a deep blue-gray palette:
- `--bg-color: #0f1117`
- `--card-bg: #1a1d27`
- `--text-primary: #e4e4e7`
- `--text-secondary: #9ca3af`
- `--border-color: #2a2d3a`
- `--bg-hover: #252830`
- `--bg-inset: #16181f`
- `--border-subtle: #252830`
- `--border-strong: #3a3d4a`
- `--green-bg: #0d3320`
- `--green-bg-hover: #134d2e`
- `--red-bg: #3d1418`
- `--blue-bg: #1a2744`
- `--focus-ring: 0 0 0 3px rgba(96, 165, 250, 0.25)`
- Shadows: darker rgba tones

### 2. CSS: Fix hardcoded color values
Replace these hardcoded values with CSS custom properties so they respond to `.dark`:
- `.navbar` background `rgba(255, 255, 255, 0.85)` → new `--navbar-bg` token
- `.search-container input:focus` `#fff` → `var(--card-bg)`
- `.fx-knob` `background: #fff` → `var(--card-bg)`
- `.btn-action` / `.tx-form button` / `.import-actions button` / `.btn-primary` / `.btn-danger` `color: #fff` → new `--btn-text` token
- `.btn-danger:hover` `#b91c1c` → new `--red-neg-hover` token
- `.modal-overlay` `rgba(16, 24, 40, 0.45)` → new `--overlay-bg` token
- `.skeleton shimmer` `#eef1f5`/`#f8fafc` → new `--shimmer-base`/`--shimmer-highlight` tokens
- Scrollbar thumb hover `#b7bfca` → new `--scrollbar-hover` token

### 3. HTML: Toggle button + FOUC prevention
In `base.html`:
- Add inline `<script>` in `<head>` to read `localStorage('theme')` or OS preference and set `class="dark"` on `<html>` before paint
- Add a sun/moon toggle button in the navbar (right side, between logo and search)

### 4. JS: Dynamic chart colors
In `common.js`:
- Replace hardcoded `CHART_COLORS` with a function that reads CSS vars via `getComputedStyle`
- Replace hardcoded crosshair `#e4e7ec` with computed `--border-color`
- Replace hardcoded tooltip `#1a1f36` with computed `--text-primary`
- Replace hardcoded y-axis grid `#eef1f5` with computed `--border-subtle`
- Replace gradient endpoint `rgba(255, 255, 255, 0)` with theme-aware transparent

### 5. JS: Toggle handler
In `common.js`:
- Add click handler for the toggle button
- Toggle `.dark` on `<html>`, save to `localStorage('theme')`
- Update chart colors on theme change (re-read CSS vars)

## Files touched
- `static/style.css` — dark overrides + fix hardcoded values
- `templates/base.html` — toggle button + FOUC script
- `static/js/common.js` — dynamic chart colors + toggle handler

## Test plan
- Toggle button renders in navbar on both pages
- `data-theme` attribute or `.dark` class present on `<html>` when dark
- Theme persists across page loads (localStorage)
- CSS vars are redefined under `.dark`
- Hardcoded colors replaced with tokens
- Chart colors are dynamic
- Full `python -m pytest` passes
