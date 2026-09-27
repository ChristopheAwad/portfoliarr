# tests/test_stock_stats.py
# ==========================
# Locks for the expanded stock-detail stats grid (roadmap #52).
#
# The detail page's stats card already paid for ONE heavy `Ticker.info`
# call per page load; #52 reads the REST of that same profile out of it —
# no new endpoint, no new network call, no cache. Two contracts are under
# test here:
#
#   1. DATA LAYER (market_data.get_stats). Yahoo ships some fields as
#      FRACTIONS (0.12 = 12%) and some already scaled (debtToEquity=78.4
#      means 78.4%). get_stats normalizes fractions to percent numbers
#      (×100, NO rounding — the frontend formats) and passes the
#      already-scaled fields through VERBATIM. Missing/non-finite fields
#      degrade to None, never raise; a wholly EMPTY profile still raises
#      ValueError (the "Yahoo doesn't know this symbol" verdict).
#
#   2. TEMPLATE. Every new cell ships as an EMPTY <dd> (the :empty
#      shimmer rule), and the About paragraph ships empty inside its own
#      cluster. A renamed or non-empty cell is a silent break, so pytest
#      makes it loud.
#
# market_data.yf is patched WHERE MARKET_DATA USES IT (tests/test_stock.py's
# NaN test is the pattern) so the REAL get_stats runs — fake_market would
# replace app.get_stats with a dict lookup and bypass the data layer this
# file mostly exists to lock.

import pytest
from types import SimpleNamespace

import market_data


class FakeTicker:
    def __init__(self, info):
        self.info = info


def patch_info(monkeypatch, info):
    """Point market_data.yf at a Ticker whose .info is the given dict.

    The profile read is `yf.Ticker(symbol).info` — one attribute access —
    so a lambda Ticker returning a FakeTicker is all get_stats touches.
    """
    monkeypatch.setattr(
        market_data, "yf",
        SimpleNamespace(Ticker=lambda symbol: FakeTicker(info)),
    )


# A full fake `.info` in Yahoo's own camelCase shape. The exact values
# matter: the fraction→percent assertions below are chosen so a missing or
# extra ×100 is arithmetically visible (0.1204 must not stay 0.1204, and
# 78.445 must not become 7844.5).
FULL_INFO = {
    "open": 148.0, "dayHigh": 152.0, "dayLow": 147.5,
    "regularMarketPreviousClose": 145.0, "volume": 55_000_000,
    "fiftyTwoWeekLow": 164.0, "fiftyTwoWeekHigh": 237.25,
    "marketCap": 3_500_000_000_000,
    "trailingPE": 28.5, "trailingEps": 6.10, "dividendYield": 0.57,
    "beta": 1.2, "fiftyDayAverage": 228.4,
    "twoHundredDayAverage": 210.15, "avgVolume10days": 42_000_000,
    "targetMeanPrice": 260.0, "recommendationKey": "buy",
    "sector": "Technology", "industry": "Consumer Electronics",
    # new:
    "forwardPE": 35.5, "priceToBook": 46.3, "pegRatio": 2.74,
    "payoutRatio": 0.1204, "grossMargins": 0.48653,
    "operatingMargins": 0.32623, "profitMargins": 0.27619,
    "returnOnEquity": 1.4875, "revenueGrowth": 0.164,
    "earningsGrowth": 0.287, "totalCash": 62_399_000_576,
    "totalDebt": 84_343_996_416, "freeCashflow": 107_721_875_456,
    "ebitda": 167_959_003_136, "debtToEquity": 78.445,
    "sharesOutstanding": 14_594_180_000, "floatShares": 14_569_078_010,
    "recommendationMean": 2.20455, "numberOfAnalystOpinions": 39,
    "fullTimeEmployees": 150_000, "targetLowPrice": 215.0,
    "targetHighPrice": 405.0, "targetMedianPrice": 340.0,
    "country": "United States", "quoteType": "EQUITY",
    "website": "https://www.apple.com",
    "longBusinessSummary": "Apple Inc. designs and sells electronics.",
}

# The app-shape keys #52 adds, each with its expected value. Kept as one
# table so test 1 and test 4 read from the same source of truth.
NEW_KEYS = {
    "forward_pe": 35.5, "price_to_book": 46.3, "peg_ratio": 2.74,
    "payout_ratio": 12.04, "gross_margin": 48.653,
    "operating_margin": 32.623, "profit_margin": 27.619,
    "return_on_equity": 148.75, "revenue_growth": 16.4,
    "earnings_growth": 28.7, "total_cash": 62_399_000_576,
    "total_debt": 84_343_996_416, "free_cashflow": 107_721_875_456,
    "ebitda": 167_959_003_136, "debt_to_equity": 78.445,
    "shares_outstanding": 14_594_180_000, "float_shares": 14_569_078_010,
    "recommendation_mean": 2.20455, "num_analyst_opinions": 39,
    "employees": 150_000, "target_low": 215.0,
    "target_high": 405.0, "target_median": 340.0,
    "country": "United States", "quote_type": "EQUITY",
    "website": "https://www.apple.com",
    "business_summary": "Apple Inc. designs and sells electronics.",
}


# ── Data layer ────────────────────────────────────────────────────────

def test_get_stats_returns_new_keys(monkeypatch):
    """Every new app key rides out of the one profile call with the right
    value. Ratios ~ plain numbers, fractions ~ percent numbers, text ~
    strings. This is the broad presence+value lock."""
    patch_info(monkeypatch, FULL_INFO)
    stats = market_data.get_stats("AAPL")

    for key, expected in NEW_KEYS.items():
        assert key in stats, f"get_stats dropped the new key {key!r}"
        assert stats[key] == pytest.approx(expected), (
            f"{key}: expected {expected!r}, got {stats[key]!r}"
        )


def test_fraction_fields_are_percent_numbers(monkeypatch):
    """Yahoo fractions become percent numbers (×100), with NO rounding —
    the raw product, because the frontend owns display rounding."""
    patch_info(monkeypatch, FULL_INFO)
    stats = market_data.get_stats("AAPL")

    assert stats["payout_ratio"] == 12.04
    assert stats["gross_margin"] == 48.653
    assert stats["operating_margin"] == pytest.approx(32.623)
    assert stats["profit_margin"] == pytest.approx(27.619)
    assert stats["return_on_equity"] == pytest.approx(148.75)
    assert stats["revenue_growth"] == pytest.approx(16.4)
    assert stats["earnings_growth"] == pytest.approx(28.7)


def test_debt_to_equity_verbatim(monkeypatch):
    """debtToEquity is ALREADY scaled by Yahoo (78.445 = 78.4%) — a ×100
    here is the double-scaling class of bug the dividend_yield note warns
    about, and would show 7844.5%."""
    patch_info(monkeypatch, FULL_INFO)
    stats = market_data.get_stats("AAPL")

    assert stats["debt_to_equity"] == 78.445
    assert stats["debt_to_equity"] != 7844.5


def test_missing_fields_are_none(monkeypatch):
    """A sparse profile (an index, a non-payer) must not raise: every new
    key is present and None, exactly like today's missing-field rule."""
    patch_info(monkeypatch, {"marketCap": 5})
    stats = market_data.get_stats("AAPL")  # must not raise

    for key in NEW_KEYS:
        assert key in stats, f"get_stats dropped {key!r} on a sparse profile"
        assert stats[key] is None, (
            f"{key}: expected None for a missing field, got {stats[key]!r}"
        )


def test_non_finite_becomes_none(monkeypatch):
    """Yahoo's NaN/inf sentinels must become None BEFORE any JSON — a bare
    NaN token is invalid JSON for a browser (the blank-chart outage rule,
    applied to the grid)."""
    patch_info(monkeypatch, {
        "profitMargins": float("nan"),
        "totalCash": float("inf"),
    })
    stats = market_data.get_stats("AAPL")

    assert stats["profit_margin"] is None
    assert stats["total_cash"] is None


def test_empty_info_raises(monkeypatch):
    """An EMPTY profile means Yahoo doesn't know the symbol — that is a
    named failure, not "real but all-None" stats."""
    patch_info(monkeypatch, {})
    with pytest.raises(ValueError):
        market_data.get_stats("NOPE")


# ── Route (pure pass-through) ─────────────────────────────────────────

def test_stats_route_passes_new_keys_through(client, fake_market):
    """The /stats route is a pure pass-through of whatever get_stats
    returns — new keys included, unchanged. fake_market replaces
    app.get_stats with a dict lookup, so equality proves no translation."""
    app_shape = {
        "forward_pe": 35.5, "gross_margin": 48.653, "total_cash": 62_399_000_576,
        "country": "United States", "business_summary": "Apple Inc.",
        "debt_to_equity": 78.445,
    }
    fake_market.stats["AAPL"] = app_shape

    res = client.get("/api/stock/AAPL/stats")
    assert res.status_code == 200
    assert res.get_json() == app_shape


# ── Template meta-locks ───────────────────────────────────────────────

NEW_STAT_IDS = [
    "stat-forward-pe", "stat-price-to-book", "stat-peg",
    "stat-payout-ratio", "stat-target-low", "stat-target-high",
    "stat-target-median", "stat-num-analysts", "stat-recommendation-mean",
    "stat-gross-margin", "stat-operating-margin", "stat-profit-margin",
    "stat-return-on-equity", "stat-revenue-growth", "stat-earnings-growth",
    "stat-total-cash", "stat-total-debt", "stat-debt-to-equity",
    "stat-free-cash-flow", "stat-ebitda", "stat-shares-out",
    "stat-float-shares",
    "stat-country", "stat-quote-type", "stat-employees", "stat-website",
]


def test_stock_page_has_all_new_stat_ids(client):
    """Every new id stock.js fills must render — a missing one is a silently
    dead cell (getElementById returns null). stat-about is a <p>, so it is
    checked separately from the <dd> list."""
    html = client.get("/stock/AAPL").get_data(as_text=True)

    missing = [i for i in NEW_STAT_IDS if f'id="{i}"' not in html]
    assert missing == [], f"stock page lost new stat ids: {missing}"
    assert 'id="stat-about"' in html


def test_new_stat_cells_ship_empty(client):
    """The shimmer is CSS keyed on `:empty`, so every new numeric cell must
    ship with NOTHING between its tags. The About paragraph follows the
    same rule inside its own cluster. stat-website is the one exception:
    its id sits on an <a>, and an anchor's href is an attribute, not
    content — it must still ship EMPTY text (and no href)."""
    html = client.get("/stock/AAPL").get_data(as_text=True)

    import re
    for stat_id in NEW_STAT_IDS:
        if stat_id == "stat-website":
            continue
        match = re.search(rf'<dd id="{stat_id}">([^<]*)</dd>', html)
        assert match, f"{stat_id} dd not found"
        assert match.group(1) == "", (
            f"{stat_id} must ship empty (:empty shimmer)"
        )

    website = re.search(r'<a id="stat-website"[^>]*>([^<]*)</a>', html)
    assert website, "stat-website anchor not found"
    assert website.group(1) == "", "stat-website must ship empty"
    assert 'id="stat-website" href' not in html, (
        "stat-website must ship WITHOUT href (no dead link)"
    )

    about = re.search(
        r'<p class="stats-about" id="stat-about">([^<]*)</p>', html)
    assert about, "stat-about paragraph not found"
    assert about.group(1) == "", "stat-about must ship empty (:empty shimmer)"
