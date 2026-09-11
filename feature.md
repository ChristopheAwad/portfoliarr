# Feature: Preferences Page

## Problem
The user wants dark mode and default ledger sort grouped under a Preferences page, accessible via a profile icon in the top-right corner of the navbar. The dropdown itself should just link to the page — not contain inline controls.

## Target State
- Profile icon in top-right of navbar → dropdown with a single "Preferences" link
- Clicking "Preferences" navigates to `/preferences`
- The `/preferences` page contains:
  - Theme selector (Light/Dark/System)
  - Default ledger sort selector (column + direction)

## Files to touch
- `app.py` — add `/preferences` route
- `templates/base.html` — simplify dropdown to just a "Preferences" link
- `templates/preferences.html` — new page template
- `static/style.css` — add preferences page styles
- `static/js/preferences.js` — new page script (theme + sort controls)
- `static/js/common.js` — remove theme select logic (moves to preferences.js)
- `static/js/main.js` — remove sort controls wiring (moves to preferences.js)
- `tests/test_dark_mode.py` — update selectors

## Plan

### 1. Route: Add `/preferences` to `app.py`
- Simple route returning `render_template("preferences.html")`
- No API needed — all settings are localStorage-based

### 2. HTML: Simplify profile dropdown in `base.html`
- Remove theme select and sort controls from dropdown
- Keep just the user icon button + a dropdown with a single "Preferences" link
- The link navigates to `/preferences`

### 3. HTML: Create `templates/preferences.html`
- Extends `base.html` (same pattern as stock.html)
- Two card sections:
  1. **Theme**: Light/Dark/System dropdown
  2. **Default Ledger Sort**: Column dropdown + direction toggle
- Reads current values from localStorage on load
- Saves to localStorage on change

### 4. CSS: Add preferences page styles
- `.preferences-page` — max-width container, centered
- `.preferences-card` — card styling (matches existing cards)
- Form elements reuse existing select/button styles

### 5. JS: Create `static/js/preferences.js`
- Reads `localStorage.getItem("theme")` → sets theme select
- Reads `localStorage.getItem("ledgerDefaultSort")` → sets sort controls
- Theme select change → saves to localStorage, applies theme, dispatches themechange
- Sort select/direction change → saves to localStorage

### 6. JS: Clean up `common.js`
- Remove theme select logic from `initProfileMenu()` (now in preferences.js)
- Keep only dropdown open/close + click-outside-close + Escape

### 7. JS: Clean up `main.js`
- Remove sort controls wiring (now in preferences.js)
- Keep header-click sort (direct manipulation) as-is

### 8. Tests
- Update `test_dark_mode.py` selectors
- Add test for `/preferences` route rendering
- Full `python -m pytest` passes

## Data flow
```
/preferences page load: localStorage → populate theme select + sort controls
Theme select change: localStorage ← value, apply .dark class, themechange event
Sort select change: localStorage ← value, dashboard reads on next load
Dashboard boot: localStorage → defaultSort → ledgerSort → renderLedger()
```
