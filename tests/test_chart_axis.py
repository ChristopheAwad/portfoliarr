"""X-axis contract tests for the shared Chart.js chart factory.

These are string checks, not rendering tests — pytest can't run a browser
or JavaScript. What they lock is the x-axis CONTRACT in common.js's
setupTimeframeChart, which serves BOTH pages (the dashboard's portfolio
value chart and the stock detail page's price chart):

  1. labels never rotate — slanted date text was half of the crowding
     mess this feature killed;
  2. the axis paints from a PRECOMPUTED array (xTickLabels) instead of
     Chart.js's auto-skipper, so tick text lands on the exact bars the
     helper chose (5D day boundaries, sparse daily/monthly ticks) — and
     unpicked bars paint "" (nothing);
  3. the old maxTicksLimit on the x-axis is GONE — dead weight with
     autoSkip off, and its presence would mean the old 8-label crowding
     crept back;
  4. the month table and the data-driven year-span flag exist, so the
     "Sep 4" vs "Sep 2025" rule can't silently vanish.

The y-scale is deliberately OUT of scope: it keeps its own
maxTicksLimit: 6 by design (short price labels never crowded).
x_scale_body() slices the x block out so these tests can't bleed into it.

The full label spec lives in feature.md and in the comment block above
buildXTickLabels in common.js.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def common_js() -> str:
    """common.js as one string — same read-the-file pattern as test_docker."""
    return (ROOT / "static" / "js" / "common.js").read_text()


def x_scale_body() -> str:
    """The x: {...} scale block from setupTimeframeChart's options.

    Crude but honest (same spirit as test_ledger_css.rule_containing):
    find the 'scales:' marker, then the 'x: {' that opens the x scale,
    and cut at the 'y: {' that follows — y is the next scale, so
    everything between belongs to x. Fails loudly if the scales block
    moves or loses its x/y halves, rather than asserting nothing.
    """
    text = common_js()
    scales_at = text.find("scales:")
    assert scales_at != -1, "setupTimeframeChart lost its scales block"
    x_at = text.find("x: {", scales_at)
    assert x_at != -1, "no x scale block after scales:"
    y_at = text.find("y: {", x_at)
    assert y_at != -1, "no y scale block after the x block"
    return text[x_at:y_at]


def test_x_axis_never_rotates_labels():
    """maxRotation: 0 is the anti-slant rule: Chart.js would otherwise
    angle long date labels when they don't fit, and angled text was half
    of the old ugly axis. The new scheme never needs rotation — labels
    are short and WE control how many appear — so the zero must stay."""
    assert "maxRotation: 0" in x_scale_body(), (
        "x-axis must keep maxRotation: 0 — labels never slant"
    )


def test_x_axis_paints_precomputed_labels():
    """autoSkip: false hands label placement to US: the tick callback
    reads the precomputed xTickLabels array (rebuilt by refresh() before
    every update) and returns "" for every bar we didn't pick. Locking
    the exact expression pins both halves — the wiring AND the
    hidden-tick default — in one needle."""
    body = x_scale_body()
    assert "autoSkip: false" in body, (
        "x-axis must set autoSkip: false — placement is ours, not Chart.js's"
    )
    assert 'xTickLabels[index] || ""' in body, (
        "x tick callback must read the precomputed xTickLabels array, "
        "defaulting to an empty string for hidden bars"
    )


def test_old_tick_limit_removed_from_x_axis():
    """maxTicksLimit: 8 was the crowding culprit — eight long ISO labels
    was exactly the mess. With autoSkip: false it's dead config, so its
    presence on the x-axis would mean the old behavior (or a half-revert)
    crept back. The y-axis keeps its own maxTicksLimit by design, which
    is why this check is scoped to the x block only."""
    assert "maxTicksLimit" not in x_scale_body(), (
        "x-axis must not carry maxTicksLimit — tick count is the helper's job"
    )


def test_label_formatter_contract():
    """The formatter side: buildXTickLabels turns the backend's ISO label
    strings into short axis text ("Sep 4" / "Sep 2025"), MONTHS is the
    month-number-to-abbreviation table it reads, and spansYears is the
    data-driven flag that flips the format when a window crosses a
    calendar year (1Y/5Y/MAX always; 3M/6M/1M across New Year). If any
    of these names vanishes, the axis either stopped being formatted or
    stopped being year-aware."""
    text = common_js()
    assert "function buildXTickLabels" in text, "formatter helper missing"
    assert "const MONTHS" in text, "month table missing"
    assert "spansYears" in text, "year-span flag missing"


def test_responsive_tick_target():
    """tickTargetForWidth adapts the label count to the chart's pixel
    width — narrow mobile screens get fewer labels so they don't overlap.
    Locking the function name and the width breakpoints keeps the mobile
    fix from silently vanishing."""
    text = common_js()
    assert "function tickTargetForWidth" in text, (
        "responsive tick-target helper missing"
    )
    assert "380" in text, "narrow-mobile breakpoint (380px) missing"
    assert "500" in text, "small-tablet breakpoint (500px) missing"
    assert "700" in text, "tablet breakpoint (700px) missing"
