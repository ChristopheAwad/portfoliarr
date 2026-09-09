"""Previous-day-close reference line contract tests.

These are string checks, not rendering tests — pytest can't run a browser
or JavaScript. What they lock is the CONTRACT that the previous-close
horizontal dotted line (1D only) is wired end-to-end:

  1. base.html ships the chartjs-plugin-annotation CDN;
  2. common.js's setupTimeframeChart has the prevCloseLine plugin and the
     updatePrevClose method;
  3. stock.js reads previous_close from the quote and passes it to the
     chart handle;
  4. main.js computes total_value - day_gain and passes it to the chart
     handle.

The visual output (dashed line, label position, color) is out of scope —
that's a browser concern.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def base_html() -> str:
    return (ROOT / "templates" / "base.html").read_text()


def common_js() -> str:
    return (ROOT / "static" / "js" / "common.js").read_text()


def style_css() -> str:
    return (ROOT / "static" / "style.css").read_text()


def stock_js() -> str:
    return (ROOT / "static" / "js" / "stock.js").read_text()


def main_js() -> str:
    return (ROOT / "static" / "js" / "main.js").read_text()


# ── CDN ──────────────────────────────────────────────────────────────────────


def test_annotation_plugin_cdn_in_base_html():
    """The annotation plugin must be loaded from a CDN in base.html, right
    after the Chart.js tag. Without it, the prevCloseLine plugin's
    annotations config would be silently ignored."""
    html = base_html()
    assert "chartjs-plugin-annotation" in html, (
        "base.html must include the chartjs-plugin-annotation CDN"
    )


def test_prev_close_css_token_in_light_and_dark():
    """The --prev-close token must exist in both :root (light) and .dark
    (dark) so the line color adapts to the theme — blue in light mode,
    yellow in dark mode."""
    css = style_css()
    # Find the :root block and the .dark class block — both must define
    # --prev-close. Split on ".dark {" (the selector) not ".dark" which
    # appears earlier in a comment.
    dark_at = css.index(".dark {")
    root_block = css[:dark_at]
    dark_block = css[dark_at:]
    assert "--prev-close" in root_block, (
        ":root must define --prev-close token"
    )
    assert "--prev-close" in dark_block, (
        ".dark must override --prev-close token"
    )


def test_prev_close_plugin_reads_prev_close_token():
    """The prevCloseLine plugin must read --prev-close from CSS, not a
    hardcoded color or a generic token like --text-muted."""
    js = common_js()
    assert "--prev-close" in js, (
        "prevCloseLine plugin must read the --prev-close CSS token"
    )


# ── common.js ────────────────────────────────────────────────────────────────


def test_prev_close_line_plugin_exists():
    """setupTimeframeChart must register a chart-local plugin with id
    'prevCloseLine' that draws the horizontal dotted reference line."""
    js = common_js()
    assert "prevCloseLine" in js, (
        "common.js must define a prevCloseLine chart plugin"
    )


def test_prev_close_line_expands_y_axis():
    """The plugin must have a beforeDraw hook that expands the y-axis to
    include prevClose — without this, a stock that gapped up/down would
    draw the line off-screen (invisible)."""
    js = common_js()
    assert "beforeDraw" in js, (
        "prevCloseLine plugin must have a beforeDraw hook to expand the y-axis"
    )


def test_update_prev_close_method_exists():
    """The chart factory must expose an updatePrevClose method on its
    return handle so callers (stock.js, main.js) can feed the value
    without reaching into the closure."""
    js = common_js()
    assert "updatePrevClose" in js, (
        "setupTimeframeChart must expose an updatePrevClose method"
    )


def test_prev_close_line_is_dashed():
    """The reference line must use ctx.setLineDash to draw a dotted/dashed
    line, matching the Google Finance look."""
    js = common_js()
    assert "setLineDash" in js, (
        "prevCloseLine plugin must use setLineDash for a dashed line"
    )


def test_prev_close_label_shows_format_price():
    """The label next to the line must use formatPrice to display the
    value, keeping formatting consistent with the rest of the app."""
    js = common_js()
    assert "formatPrice" in js, (
        "prevCloseLine label must call formatPrice for the value"
    )


def test_prev_close_only_on_1d():
    """The plugin must check the current period and short-circuit when
    it's not '1D' — the line is only meaningful on intraday charts."""
    js = common_js()
    # The plugin must reference "1D" to gate the drawing
    assert '"1D"' in js or "'1D'" in js, (
        "prevCloseLine plugin must reference '1D' to gate rendering"
    )


# ── stock.js ─────────────────────────────────────────────────────────────────


def test_stock_js_reads_previous_close():
    """refreshStockQuote must read quote.previous_close from the API
    response — the value is already sent by the backend, stock.js just
    needs to use it."""
    js = stock_js()
    assert "previous_close" in js, (
        "stock.js must read previous_close from the quote response"
    )


def test_stock_js_calls_update_prev_close():
    """refreshStockQuote must call updatePrevClose on the chart handle
    to feed the previous-close value into the annotation plugin."""
    js = stock_js()
    assert "updatePrevClose" in js, (
        "stock.js must call updatePrevClose on the chart handle"
    )


# ── main.js ──────────────────────────────────────────────────────────────────


def test_main_js_computes_yesterday_value():
    """refreshPortfolioSummary must derive yesterday's portfolio value as
    total_value - day_gain — the two fields the summary endpoint already
    returns."""
    js = main_js()
    assert "total_value" in js, (
        "main.js must reference total_value from the summary response"
    )
    assert "day_gain" in js, (
        "main.js must reference day_gain from the summary response"
    )


def test_main_js_calls_update_prev_close():
    """refreshPortfolioSummary must call updatePrevClose on the chart
    handle to feed yesterday's portfolio value into the annotation."""
    js = main_js()
    assert "updatePrevClose" in js, (
        "main.js must call updatePrevClose on the chart handle"
    )
