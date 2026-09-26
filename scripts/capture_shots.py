"""Capture auth/People UI screenshots from the throwaway capture server
(port 5001, started by scripts/capture_server.py).

Playwright lives in the SYSTEM python, NOT the project venv:
    /usr/bin/python3 scripts/capture_shots.py [--out DIR] [--dark-only]

The flow wires itself through the REAL forms (no cookie forging): setup
first (the throwaway DB boots with zero users), then Preferences with
the real open-sign-up switch, then the pages it unlocks. Themes swap via
the localStorage 'theme' key the app's head bootstrap reads; every shot
is taken in light AND dark. Output never touches main by itself — commit
the shots you want to a `pr-<N>-screenshots` branch under
docs/screenshots/ and link them in the PR body
(raw.githubusercontent.com), the PR #88 pattern.
"""

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", default="docs/screenshots",
                    help="PNG output directory (default: docs/screenshots)")
parser.add_argument("--dark-only", action="store_true",
                    help="capture the dark variants only")
OPTIONS = parser.parse_args()

BASE = "http://localhost:5001"
OUT = Path(OPTIONS.out)
OUT.mkdir(parents=True, exist_ok=True)
THEMES = ("dark",) if OPTIONS.dark_only else ("light", "dark")


def set_theme(page, theme):
    page.evaluate(f"localStorage.setItem('theme', '{theme}')")


def settle(page, ms=700):
    page.wait_for_load_state("networkidle")
    time.sleep(ms / 1000)  # let web fonts swap in


def shot(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"))


def for_themes(page, visit):
    """Run `visit` once per theme, reloading between swaps."""
    for theme in THEMES:
        set_theme(page, theme)
        page.reload()
        settle(page)
        visit(theme)


def add_person(page):
    """The card's own form: a second person makes the list show the
    (you) badge and a Delete control on a row that is not the session."""
    page.fill("#people-new-username", "alex")
    page.fill("#people-new-password", "alex-pass-1234")
    page.click("#people-create button[type=submit]")
    page.wait_for_selector("li[data-id='2']")
    settle(page, 400)
    page.locator("#people-card").scroll_into_view_if_needed()


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                              device_scale_factor=2)

    # ── 1. Setup page (the throwaway DB boots with zero users) ───────
    page = ctx.new_page()
    page.goto(f"{BASE}/auth/setup")
    set_theme(page, "light")
    for theme in THEMES:
        set_theme(page, theme)
        page.reload()
        settle(page)
        shot(page, f"setup-{theme}")

    # ── 2. Complete setup: demo account, signed in ──────────────────
    set_theme(page, "light")
    page.reload()
    page.fill("#setup-username", "demo")
    page.fill("#setup-password", "demo-pass-1234")
    page.fill("#setup-confirm", "demo-pass-1234")
    page.click(".auth-form button[type=submit]")
    page.wait_for_url(f"{BASE}/")
    settle(page)

    # ── 3. Preferences: People card, open-sign-up switch ON ─────────
    page.goto(f"{BASE}/preferences")
    settle(page)
    people = page.locator("#people-card")
    people.scroll_into_view_if_needed()
    for_themes(page, lambda t: shot(page, f"people-{t}"))

    add_person(page)
    page.locator("#allow-signup").check()
    page.wait_for_selector("text=Open sign-up is on")
    settle(page, 400)
    page.locator("#people-card").scroll_into_view_if_needed()
    for_themes(page, lambda t: shot(page, f"people-signup-on-{t}"))

    # ── 4. Log out → login page now carries the signup link ─────────
    page.click("#profile-btn")
    page.wait_for_selector("#profile-dropdown:not([hidden])")
    page.click("#profile-dropdown button[type=submit]")
    page.wait_for_url("**/auth/login")
    for_themes(page, lambda t: shot(page, f"login-with-signup-link-{t}"))

    # ── 5. The open sign-up form itself ──────────────────────────────
    page.goto(f"{BASE}/auth/signup")
    for_themes(page, lambda t: shot(page, f"signup-form-{t}"))

    # ── 6. Wrong password still fails uniformly ──────────────────────
    page.goto(f"{BASE}/auth/login")
    set_theme(page, "light")
    page.reload()
    settle(page)
    page.fill("#login-username", "demo")
    page.fill("#login-password", "wrong-key")
    page.click(".auth-form button[type=submit]")
    page.wait_for_selector(".action-error")
    settle(page, 400)
    shot(page, "login-error")

    browser.close()

print("saved:", sorted(f.name for f in OUT.glob("*.png")))
