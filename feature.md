# Logo detail: beveled coin stack (web + Android)

Status: in progress
Branch: fix/logo-bevel-detail
Scope: tweak (not a roadmap item; refines shipped #25/#60)

## Goal

Apply the user-approved **beveled edge** study to the coin-stack mark:

- a 1.5-unit side wall under each coin, at 78% opacity (the bevel);
- a 0.66-unit inner rim on each coin, at 55% opacity (the engraving);
- a longer growth arrow at the new scale (`M12 9 V2.4`,
  head `M8.7 5.4 L12 2.1 L15.3 5.4`, stroke 2.6);
- coins at `cy=12.0` and `cy=19.4`, `rx=7.8`, `ry=3`.

The silhouette **does** change from the shipped mark: the coins are narrower
(7.8 vs 8.6), the stack is taller (bottom 23.9 vs 20.3), and the top coin
moves down (12.0 vs 10.4). The two-coin + arrow idea is unchanged. 16 px
legibility must be re-checked, not assumed.

The mark stays single-colour (`currentColor`) in the navbar, auth pages and
lockup. The app icon keeps navy `#1c3a5e` + gold `#d0a959`.

This is a visual tweak, so it adds no roadmap entry and does not change
`roadmap.md` statuses.

## Geometry (source of truth)

`assets/logo/portfoliarr-mark.svg`, viewBox `0 0 24 24`:

```svg
<path d="M12 9 V2.4 M8.7 5.4 L12 2.1 L15.3 5.4"
      fill="none" stroke="currentColor" stroke-width="2.6"
      stroke-linecap="round" stroke-linejoin="round"/>
<!-- top coin, cy=12 -->
<path d="M4.2 12 v1.5 a7.8 3 0 0 0 15.6 0 v-1.5 Z"
      fill="currentColor" opacity=".78"/>
<ellipse cx="12" cy="12" rx="7.8" ry="3" fill="currentColor"/>
<ellipse cx="12" cy="12" rx="6.1" ry="1.9" fill="none"
         stroke="currentColor" stroke-opacity=".55" stroke-width=".66"/>
<!-- bottom coin, cy=19.4: the same three shapes -->
```

This block is only the bevel baseline. The shipped source of truth also wraps
the top coin in `<g mask="url(#logoDollar…)">` and adds the metal `$` strokes
described in **Dollar sign on the top coin**; those paths are part of the same
contract and are locked by `tests/test_brand_assets.py`.

The bottom wall ends at `19.4 + 1.5 + 3 = 23.9`, inside the 24-unit viewBox.
The arrow's round cap reaches about `y=0.8`, so the visual mark is
`~23.1` units tall.

`assets/logo/portfoliarr-icon.svg`, viewBox `0 0 1024 1024`:

- `<rect width="1024" height="1024" rx="220" fill="#1c3a5e"/>`
- `<g transform="translate(164,154) scale(29)">` around the same paths, with
  `#d0a959` instead of `currentColor`. The group centres the visual bounds
  (`x=12`, `y=12.35`) and the glyph is `23.1 × 29 = 670` units tall
  (65.4% of the tile).

`assets/logo/portfoliarr-lockup.svg`: same paths in a
`translate(6,9) scale(2.4)` group; the wordmark text element is unchanged.
The group uses `currentColor`; no gold belongs in the lockup. Mark bottom:
`9 + 23.9 × 2.4 = 66.4`, about the old 66.7. `x=6` keeps the mark's left
edge at `6 + 4.2 × 2.4 = 16.1`, matching the old lockup; the narrower mark
therefore leaves a slightly wider gap to the text at x=72 (18.5 vs 14.6).

## Android foreground

`android/app/src/main/res/drawable/ic_launcher_foreground.xml` keeps the
existing outer safe-zone group and replaces the inner group:

```xml
<group android:pivotX="512" android:pivotY="512"
       android:scaleX="0.95" android:scaleY="0.95">
  <group android:translateX="164" android:translateY="154"
         android:scaleX="29" android:scaleY="29">
    <!-- arrow, walls, ellipses, rims -->
  </group>
</group>
```

Exact `pathData` (comma form) and local stroke widths:

- arrow: `M12,9 V2.4 M8.7,5.4 L12,2.1 L15.3,5.4`,
  `strokeWidth="2.6"` (not multiplied by 29);
- top wall: `M4.2,12 v1.5 a7.8,3 0 0,0 15.6,0 v-1.5 Z`,
  `fillAlpha="0.78"`;
- top coin: `M4.2,12 a7.8,3 0 1,0 15.6,0 a7.8,3 0 1,0 -15.6,0 Z`;
- top rim: `M5.9,12 a6.1,1.9 0 1,0 12.2,0 a6.1,1.9 0 1,0 -12.2,0 Z`,
  `strokeWidth="0.66"`, `strokeAlpha="0.55"`;
- bottom wall/coin/rim: the same three with `19.4` instead of `12`.

The arrow path has comma-separated `M12,9`; tests must accept a comma or a
space between `M12` and `9`.

Effective glyph height: `23.1 × 29 × 0.95 = 636` units (62.1% of 1024),
inside the adaptive-icon safe zone. VectorDrawable uses
`android:fillAlpha="0.78"` for the walls and
`android:strokeAlpha="0.55"` for the rims. **No SVG `opacity=` or
`stroke-opacity=` may appear in this XML** (VectorDrawable ignores them).
The coin and rim ellipses use the arc paths above.

Update the file header comment to the new numbers and the safe-zone math.

## Rasterization (reproducible)

Add `scripts/render_brand_assets.py` (Playwright, Chromium) and run it with
the interpreter that owns Playwright:

```bash
/usr/bin/python3 scripts/render_brand_assets.py
```

It reads `assets/logo/portfoliarr-icon.svg` and writes exact-size PNGs with a
transparent page background (`omit_background=True`, `device_scale_factor=1`):

- `assets/logo/portfoliarr-icon.png` — 1254×1254 RGBA
- `static/favicon.png` — 64×64 RGBA
- `android/.../mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png` —
  48, 72, 96, 144, 192 RGBA

The script prints each written path; no network, no new Python dependency
(the venv does not need Playwright).

## Dollar sign on the top coin (user request 2026-10-22)

Engrave a `$` into the top coin's face, on top of the bevel work:

- **Web mark** (`portfoliarr-mark.svg`, `base.html`, `_auth_head.html`,
  `portfoliarr-lockup.svg`): a `<mask>` cuts a 1.2-wide groove out of the
  top coin, then the `$` is redrawn in `currentColor` at `stroke-width=".55"`
  so the sign reads as raised metal inside a groove. The mask id is unique
  per file (`logoDollarMark`, `logoDollarNav`, `logoDollarAuth`,
  `logoDollarLockup`). The top wall + ellipse are wrapped in
  `<g mask="url(#…)">`; the rim is drawn after, so the engraving stays
  inside the rim.
- **Icon + Android** (`portfoliarr-icon.svg`, `ic_launcher_foreground.xml`):
  a metal engraving in the tile palette. Three strokes of the same `$`:
  a dark-gold groove `#7a5f27` at `1.35`, a light-gold highlight `#f2d78f`
  at `.45` shifted `-0.34` units up (the lit edge), then the gold `$`
  `#d0a959` at `.75`. Android uses `android:translateY="-0.34"` on a
  `<group>` for the highlight; no SVG opacity leaks in.

Geometry (same `$` path in every file):

```svg
<path d="M12 10.2 V13.8 M13.2 10.9 C13.2 10.35 12.65 10.1 12 10.1 C11.35 10.1 10.85 10.45 10.85 11 C10.85 12.25 13.15 11.75 13.15 13 C13.15 13.55 12.65 13.9 12 13.9 C11.35 13.9 10.8 13.65 10.8 13.1"
      fill="none" stroke-linecap="round" stroke-linejoin="round"/>
```

Android uses the comma form of the same path with
`android:strokeColor="#7a5f27"` / `#f2d78f` / `#d0a959` and
`android:strokeWidth` `1.35` / `0.45` / `0.75`.

Extra test assertions: `<mask` present in the mark, lockup, base and auth
regions; the web mark keeps `stroke-width="1.2"` and `stroke-width=".55"`;
the icon SVG has `stroke="#7a5f27"`, `stroke="#f2d78f"`,
`transform="translate(0,-0.34)"`, and widths `1.35` / `.45` / `.75`; the
Android vector has the matching `strokeColor` values, widths, and
`android:translateY="-0.34"`. The existing counts (`<ellipse` 4,
`opacity=".78"` 2, `stroke-opacity=".55"` 2, `v1.5` 2, `a7.8,3` 6,
`a6.1,1.9` 4, `fillAlpha` 2, `strokeAlpha` 2) are unchanged.

Edge cases: at 16 px the `$` fades to a speck (the stack still reads); at
24 px it is a small engraving; the icon and master show the metal groove and
lit edge clearly. The `$` sits inside the rim (`y 10.1–13.9`), clear of the
arrow stem that ends at `y=9`. Regenerate the PNGs after the icon SVG
change: `/usr/bin/python3 scripts/render_brand_assets.py`.

## Files

1. `assets/logo/portfoliarr-mark.svg` — new detailed mark.
2. `assets/logo/portfoliarr-icon.svg` — 1024 navy tile + detailed gold mark.
3. `assets/logo/portfoliarr-lockup.svg` — updated mark group.
4. `assets/logo/portfoliarr-icon.png` — 1254×1254 RGBA, transparent corners.
5. `static/favicon.png` — 64×64 RGBA, transparent corners (converted from
   the current indexed type-3 file).
6. `android/app/src/main/res/drawable/ic_launcher_foreground.xml` — full
   tree, arc paths, fill/stroke alpha, new arrow, updated comment.
7. `android/app/src/main/res/mipmap-*/ic_launcher.png` — five RGBA sizes.
8. `templates/base.html` — navbar inline SVG + comment.
9. `templates/_auth_head.html` — auth inline SVG + comment.
10. `scripts/render_brand_assets.py` — deterministic rasterizer.
11. `tests/test_brand_assets.py` — update locks; add counts, alpha, and
    auth/lockup/bevel tests.
12. `scripts/capture_shots.py` — `navbar-{theme}` shots for approval.
13. `feature.md` — this plan.

Comments to update: `templates/base.html:96-105`, `templates/base.html:19-25`
(if it mentions the old 1254 master), `templates/_auth_head.html:49-50`,
`ic_launcher_foreground.xml:1-4`, and the lockup SVG. Do not change
`project-brief.md`, `roadmap.md` statuses, `VERSION`, `VERSION_CODE`, Kotlin,
CI, `assets/logo/candidates/`, or the dated backup.

## Tests (write first)

Run `.venv/bin/python -m pytest tests/test_brand_assets.py -v` and confirm
the new/updated assertions fail against the old flat mark.

1. `test_mark_svg_has_bevel_and_rim`
   - `viewBox="0 0 24 24"`, `currentColor`;
   - `opacity=".78"` count == 2, `stroke-opacity=".55"` count == 2,
     `<ellipse` count == 4, `v1.5` count == 2;
   - `M12 9` present; `M12 5.6` absent.
2. `test_base_logo_mark_is_coin_stack` (update)
   - region from `class="logo-mark"` to `</svg>`;
   - same four counts and `M12 9` present; `M12 5.6` absent;
   - no `polyline` (historical sparkline guard);
   - `class="logo-accent"` still in the file.
3. `test_auth_logo_mark_is_coin_stack` (new)
   - same assertions for `templates/_auth_head.html`.
4. `test_lockup_uses_beveled_mark` (new)
   - exact `translate(6,9) scale(2.4)`;
   - `opacity=".78"` 2, `stroke-opacity=".55"` 2, `<ellipse` 4;
   - `stroke-width="2.6"` and `stroke-width=".66"` present;
   - `currentColor` present, `#d0a959` absent;
   - wordmark `font-size="46"` and `Portfoli`/`arr` text unchanged;
   - `M12 5.6` absent.
5. `test_favicon_is_64_square_and_transparent` (update)
   - size 64×64, color type 6;
   - corner alpha 0, center alpha 255.
6. `test_master_icon_is_1254_rgba` (update)
   - 1254×1254, color type 6, corner alpha 0.
7. `test_android_launcher_icon` (update)
   - sizes and color type 6;
   - corner alpha 0 for every density.
8. `test_adaptive_foreground_is_gold_glyph` (update)
   - `android:width="108dp"`, `android:height="108dp"`,
     `android:viewportWidth="1024"`, `android:viewportHeight="1024"`; gold;
   - `a7.8,3` count == 6:
     two walls × one arc + two coin ellipses × two arcs = 6;
   - `a6.1,1.9` count == 4 (two rims × two arcs);
   - `android:fillAlpha="0.78"` count == 2,
     `android:strokeAlpha="0.55"` count == 2;
   - `android:strokeWidth="2.6"` and `android:strokeWidth="0.66"` present;
   - `M12` + optional comma/space + `9` present (regex), `M12 5.6` absent;
   - `"opacity="` absent; outer `0.95`, inner `164/154/29` present.
9. `test_adaptive_icon_points_at_brand_layers`,
   `test_adaptive_background_is_brand_navy`,
   `test_manifest_keeps_ic_launcher_name` (existing) — unchanged.
10. `test_icon_svg_exists`, `test_navbar_mark_uses_accent_token` (existing)
    — unchanged.

Add a stdlib RGBA reader (`zlib` + PNG unfilter) in the test file; no
Pillow dependency. It handles 8-bit, non-interlaced, colour type 6 PNGs and
filter types 0–4. Sample alpha at `(0,0)` (must be 0) and
`(w//2, h//2)` (must be 255). `tests/test_ui_revamp.py` and
`tests/test_users_ui.py` need no change (favicon link and `logo-mark` hook
stay).

## Verification

1. Targeted: `.venv/bin/python -m pytest tests/test_brand_assets.py -v`.
2. Rasterize: `/usr/bin/python3 scripts/render_brand_assets.py`.
3. Visual: open the 1254 master, 64 favicon, and a 48 mipmap with the read
   tool. Confirm the rim/bevel at large sizes and a clean stack at 16 px.
4. Capture real UI: start `.venv/bin/python scripts/capture_server.py`, then
   extend `scripts/capture_shots.py` with a `navbar-{theme}` shot after
   setup (it already signs in) by visiting `/preferences` and capturing the
   top of the page before scrolling, in both themes. Run
   `/usr/bin/python3 scripts/capture_shots.py --out instance/logo-previews`.
   The script already captures setup/login/signup (auth logo). If a PR is
   opened, commit the shots to a `pr-<N>-screenshots` branch with
   `git add -f` and embed them in the PR body; `main` carries none.
5. Full suite: `.venv/bin/python -m pytest`.
6. Android: no Kotlin/manifest change, so no `tests/test_docker.py` run is
   needed. APK verification needs the CI Build Android APK run;
   `VERSION_CODE` stays unchanged until a release is requested.

## Edge cases

- 16 px: the 0.66 rim and 0.78 bevel may vanish; the two filled ellipses and
  the arrow must still read.
- Dark mode: `--accent` is gold; the bevel/rim use the same colour with
  opacity, so they read as darker gold, not a second hue.
- Transparent corners: favicon and legacy mipmaps must be RGBA with corner
  alpha 0.
- Adaptive icon: outer 0.95 + inner 29 keeps the taller glyph centred and
  inside the safe zone.
- Lockup: mark bottom is 66.4, near the old 66.7; wordmark bytes unchanged.
- No network, no new dependency; Playwright runs outside the venv.
- Do not touch the untouched suites listed above; their hooks stay valid.

## Review

After tests pass, run the `reviewer` subagent in diff mode on
`git diff main...HEAD` plus uncommitted changes. Fix blocking issues, then
show the user the web and icon previews before merging.
