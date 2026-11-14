"""Browser startup assets must be available from this installation."""

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

import db
from app import app
from conftest import seed_user


ROOT = Path(__file__).resolve().parents[1]
FONT_FILES = {
    "fraunces-v38-vietnamese.woff2": ("Fraunces", "U+1EA0-1EF9"),
    "fraunces-v38-latin-ext.woff2": ("Fraunces", "U+0100-02BA"),
    "fraunces-v38-latin.woff2": ("Fraunces", "U+0000-00FF"),
    "instrument-sans-v4-latin-ext.woff2": ("Instrument Sans", "U+0100-02BA"),
    "instrument-sans-v4-latin.woff2": ("Instrument Sans", "U+0000-00FF"),
}


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.stack = []
        self.ancestors = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if "id" in attrs:
            self.ancestors[attrs["id"]] = [item[1].get("id") for item in self.stack]
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input",
                       "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


@pytest.mark.parametrize(
    "path,page_script,chart_page",
    [
        ("/", "main.js", True),
        ("/stock/AAPL", "stock.js", True),
        ("/ledger", "ledger.js", False),
        ("/preferences", "preferences.js", False),
    ],
)
def test_authenticated_pages_use_ordered_local_deferred_scripts(
    client, path, page_script, chart_page
):
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    tags = Tags(html).tags
    scripts = [attrs for tag, attrs in tags if tag == "script" and "src" in attrs]
    expected = ["/static/js/perf.js", "/static/js/common.js", f"/static/js/{page_script}"]
    if chart_page:
        expected = [
            "/static/vendor/chart.umd.4.6.1.js",
            "/static/vendor/chartjs-plugin-annotation.3.1.0.min.js",
        ] + expected
    assert [script["src"] for script in scripts] == expected
    assert all("defer" in script and "async" not in script for script in scripts)
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert "cdn.jsdelivr.net" not in html
    assert html.index("localStorage.getItem('theme')") < html.index('href="/static/style.css"')


@pytest.mark.parametrize("path", ["/", "/stock/AAPL", "/ledger", "/preferences"])
def test_shared_portfolio_status_starts_hidden_with_native_retry(client, path):
    parsed = Tags(client.get(path).get_data(as_text=True))
    by_id = {attrs["id"]: (tag, attrs) for tag, attrs in parsed.tags if "id" in attrs}
    status = by_id["portfolio-load-status"][1]
    assert "hidden" in status
    assert status.get("role") == "alert"
    assert by_id["portfolio-load-message"][0] == "span"
    assert "portfolio-load-status" in parsed.ancestors["portfolio-load-message"]
    retry_tag, retry_attrs = by_id["portfolio-load-retry"]
    assert retry_tag == "button"
    assert "portfolio-load-status" in parsed.ancestors["portfolio-load-retry"]
    assert retry_attrs.get("type") == "button"
    assert "disabled" not in retry_attrs


def test_signed_out_auth_pages_use_local_fonts_and_keep_forms(fresh_db):
    web = app.test_client()
    setup = web.get("/auth/setup")
    assert setup.status_code == 200
    seed_user("tester")
    login = web.get("/auth/login")
    assert login.status_code == 200
    db.set_setting("allow_signup", "true")
    signup = web.get("/auth/signup")
    assert signup.status_code == 200
    for response in (setup, login, signup):
        html = response.get_data(as_text=True)
        tags = Tags(html).tags
        assert any(tag == "form" and attrs.get("method", "").lower() == "post"
                   for tag, attrs in tags)
        assert not any(tag == "script" and "src" in attrs for tag, attrs in tags)
        assert "fonts.googleapis.com" not in html
        assert "fonts.gstatic.com" not in html
        assert html.index("localStorage.getItem('theme')") < html.index('href="/static/style.css"')


def test_chart_assets_are_real_pinned_fixtures_served_without_login(fresh_db):
    web = app.test_client()
    for name in ("chart.umd.4.6.1.js", "chartjs-plugin-annotation.3.1.0.min.js"):
        response = web.get(f"/static/vendor/{name}")
        assert response.status_code == 200
        assert "javascript" in response.content_type
        assert response.data == (ROOT / "tests/fixtures/perf" / name).read_bytes()


def test_local_fonts_keep_upstream_subsets_and_swap_fallback(fresh_db):
    web = app.test_client()
    css_response = web.get("/static/style.css")
    assert css_response.status_code == 200
    css = css_response.get_data(as_text=True)
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", css, re.S)
    for name, (family, range_sample) in FONT_FILES.items():
        matching = [face for face in faces if name in face]
        assert len(matching) == 1, name
        face = matching[0]
        assert family in face
        assert re.search(r"font-weight\s*:\s*400\s+700\s*;", face)
        assert re.search(r"font-display\s*:\s*swap\s*;", face)
        assert range_sample in face
        response = web.get(f"/static/fonts/{name}")
        assert response.status_code == 200
        assert response.data[:4] == b"wOF2"
        assert response.content_type.startswith("font/woff2")


def test_font_and_chart_licenses_ship_in_the_runtime_image():
    for name in (
        "static/vendor/chart.js.LICENSE.md",
        "static/vendor/chartjs-plugin-annotation.LICENSE.md",
        "static/fonts/fraunces.OFL.txt",
        "static/fonts/instrument-sans.OFL.txt",
    ):
        assert (ROOT / name).is_file(), name


def test_runtime_asset_records_match_the_distributed_bytes():
    for directory, names in (
        ("static/fonts", list(FONT_FILES) + ["fraunces.OFL.txt", "instrument-sans.OFL.txt"]),
        ("static/vendor", ["chart.umd.4.6.1.js", "chartjs-plugin-annotation.3.1.0.min.js"]),
    ):
        record = (ROOT / directory / "README.md").read_text()
        for name in names:
            digest = hashlib.sha256((ROOT / directory / name).read_bytes()).hexdigest()
            assert name in record
            assert digest in record
