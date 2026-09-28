# tests/test_stock_financials.py
# ==============================
# Locks for the stock-detail financials table (roadmap #54).
#
# A small annual income-statement table: 5 rows (Total Revenue,
# Gross Profit, Operating Income, Net Income, Diluted EPS) x the last 4
# fiscal years, from Yahoo's annual `income_stmt` (a pandas DataFrame
# with row labels on the index and year timestamps on the columns).
#
# Two contracts are under test here:
#
#   1. DATA LAYER (market_data.get_financials). Returns raw native-
#      currency floats in the exact reply shape
#      {years: [...], rows: {total_revenue, gross_profit,
#      operating_income, net_income, diluted_eps}} — years ascending,
#      max 4, each row list aligned to years. NO rounding, NO FX. A
#      missing row or NaN/inf cell degrades to None; a wholly EMPTY or
#      all-null statement raises ValueError (the route turns it into a
#      404, and the frontend hides the table — ETFs/crypto/indices).
#      Results ride a 24h process-memory cache, successes only.
#
#   2. TEMPLATE. The financials card ships HIDDEN with an empty head row
#      and five labelled body rows; stock.js builds every year cell from
#      JSON. A renamed id or a baked-in static year is a silent break,
#      so pytest makes it loud.
#
# market_data.yf is patched WHERE MARKET_DATA USES IT (the
# test_stock_stats.py pattern) so the REAL get_financials runs —
# fake_market would replace app.get_financials with a dict lookup and
# bypass the data layer this file mostly exists to lock.

import re
from types import SimpleNamespace

import pandas as pd
import pytest

import market_data


class FakeTicker:
    def __init__(self, stmt):
        self.income_stmt = stmt


def patch_stmt(monkeypatch, stmt):
    """Point market_data.yf at a Ticker whose .income_stmt is the given frame.

    The statement read is `yf.Ticker(symbol).income_stmt` — one attribute
    access — so a lambda Ticker returning a FakeTicker is all
    get_financials touches.
    """
    monkeypatch.setattr(
        market_data, "yf",
        SimpleNamespace(Ticker=lambda symbol: FakeTicker(stmt)),
    )


def full_stmt():
    """A full fake annual statement: exact values so assertions are exact."""
    cols = pd.to_datetime(
        ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
    )
    return pd.DataFrame(
        {
            cols[0]: [100.0, 40.0, 60.0, 25.0, 20.0, 80.0, 15.0, 1.5],
            cols[1]: [110.0, 44.0, 66.0, 27.0, 22.0, 88.0, 16.0, 1.6],
            cols[2]: [120.0, 48.0, 72.0, 29.0, 24.0, 96.0, 17.0, 1.7],
            cols[3]: [130.0, 52.0, 78.0, 31.0, 26.0, 104.0, 18.0, 1.8],
        },
        index=["Total Revenue", "Cost Of Revenue", "Gross Profit",
               "Operating Expense", "Operating Income", "Total Expenses",
               "Net Income", "Diluted EPS"],
    )


# ── Data layer ───────────────────────────────────────────────────────


def test_get_financials_returns_four_years(monkeypatch):
    patch_stmt(monkeypatch, full_stmt())
    fin = market_data.get_financials("AAPL")
    assert fin["years"] == ["2022", "2023", "2024", "2025"]
    assert fin["rows"]["total_revenue"] == [100.0, 110.0, 120.0, 130.0]
    assert fin["rows"]["cost_of_revenue"] == [40.0, 44.0, 48.0, 52.0]
    assert fin["rows"]["gross_profit"] == [60.0, 66.0, 72.0, 78.0]
    assert fin["rows"]["operating_expense"] == [25.0, 27.0, 29.0, 31.0]
    assert fin["rows"]["operating_income"] == [20.0, 22.0, 24.0, 26.0]
    assert fin["rows"]["total_expenses"] == [80.0, 88.0, 96.0, 104.0]
    assert fin["rows"]["net_income"] == [15.0, 16.0, 17.0, 18.0]
    assert fin["rows"]["diluted_eps"] == [1.5, 1.6, 1.7, 1.8]


def test_missing_row_is_all_nulls(monkeypatch):
    stmt = full_stmt().drop("Diluted EPS")
    patch_stmt(monkeypatch, stmt)
    fin = market_data.get_financials("AAPL")
    assert fin["rows"]["diluted_eps"] == [None, None, None, None]
    assert fin["rows"]["total_revenue"] == [100.0, 110.0, 120.0, 130.0]


def test_missing_expense_row_is_all_nulls(monkeypatch):
    stmt = full_stmt().drop("Operating Expense")
    patch_stmt(monkeypatch, stmt)
    fin = market_data.get_financials("AAPL")
    assert fin["rows"]["operating_expense"] == [None, None, None, None]
    assert fin["rows"]["operating_income"] == [20.0, 22.0, 24.0, 26.0]


def test_non_finite_cells_become_none(monkeypatch):
    import math
    stmt = full_stmt()
    stmt.iloc[2, 2] = float("nan")  # Gross Profit 2024
    stmt.iloc[6, 3] = float("inf")  # Net Income 2025
    patch_stmt(monkeypatch, stmt)
    fin = market_data.get_financials("AAPL")
    assert fin["rows"]["gross_profit"][2] is None
    assert fin["rows"]["gross_profit"][1] == 66.0
    assert fin["rows"]["net_income"][3] is None
    assert fin["rows"]["net_income"][2] == 17.0
    assert math.isfinite(fin["rows"]["total_revenue"][0])


def test_empty_statement_raises(monkeypatch):
    patch_stmt(monkeypatch, pd.DataFrame())
    with pytest.raises(ValueError):
        market_data.get_financials("AAPL")


def test_all_null_statement_raises(monkeypatch):
    import math
    stmt = full_stmt()
    stmt.iloc[:, :] = float("nan")
    assert math.isnan(stmt.iloc[0, 0])
    patch_stmt(monkeypatch, stmt)
    with pytest.raises(ValueError):
        market_data.get_financials("AAPL")


def test_more_than_four_columns_takes_last_four(monkeypatch):
    cols = pd.to_datetime(
        ["2020-12-31", "2021-12-31", "2022-12-31", "2023-12-31",
         "2024-12-31"]
    )
    stmt = pd.DataFrame(
        {c: [float(i + 1), 1.0, 1.0, 1.0, 0.1] for i, c in enumerate(cols)},
        index=["Total Revenue", "Gross Profit", "Operating Income",
               "Net Income", "Diluted EPS"],
    )
    patch_stmt(monkeypatch, stmt)
    fin = market_data.get_financials("AAPL")
    assert fin["years"] == ["2021", "2022", "2023", "2024"]
    assert fin["rows"]["total_revenue"] == [2.0, 3.0, 4.0, 5.0]


def test_cache_serves_second_call(monkeypatch):
    patch_stmt(monkeypatch, full_stmt())
    first = market_data.get_financials("AAPL")
    # A different statement must NOT leak through: the cache owns the
    # second answer (the autouse fresh_market_caches fixture isolates us).
    patch_stmt(monkeypatch, full_stmt() * 2)
    second = market_data.get_financials("AAPL")
    assert first == second
    assert second["rows"]["total_revenue"] == [100.0, 110.0, 120.0, 130.0]


# ── Route ────────────────────────────────────────────────────────────


def test_financials_route_passes_through(client, fake_market):
    reply = {
        "years": ["2024", "2025"],
        "rows": {
            "total_revenue": [120.0, 130.0],
            "cost_of_revenue": [48.0, 52.0],
            "gross_profit": [72.0, 78.0],
            "operating_expense": [29.0, 31.0],
            "operating_income": [24.0, 26.0],
            "total_expenses": [96.0, 104.0],
            "net_income": [17.0, 18.0],
            "diluted_eps": [1.7, 1.8],
        },
    }
    fake_market.financials["AAPL"] = reply
    response = client.get("/api/stock/AAPL/financials")
    assert response.status_code == 200
    assert response.get_json() == reply


def test_financials_route_404_when_empty(client, fake_market):
    # Key absent = Yahoo failure (the fake_market KeyError convention).
    response = client.get("/api/stock/NOPE/financials")
    assert response.status_code == 404
    assert "error" in response.get_json()


# ── Template ─────────────────────────────────────────────────────────


def _stock_html(client):
    return client.get("/stock/AAPL").get_data(as_text=True)


def test_stock_page_has_financials_ids(client):
    html = _stock_html(client)
    for element_id in ("financials-card", "fin-table", "fin-head-row",
                       "fin-row-total-revenue", "fin-row-cost-of-revenue",
                       "fin-row-gross-profit", "fin-row-operating-expense",
                       "fin-row-operating-income", "fin-row-total-expenses",
                       "fin-row-net-income", "fin-row-diluted-eps",
                       "fin-chart"):
        assert f'id="{element_id}"' in html


def test_financials_rows_follow_statement_order(client):
    # Income-statement order: revenue, cost, gross, opex, op income,
    # total expenses, net, EPS — a shuffled table misreads.
    html = _stock_html(client)
    positions = [
        html.index(f'id="{element_id}"')
        for element_id in ("fin-row-total-revenue",
                           "fin-row-cost-of-revenue",
                           "fin-row-gross-profit",
                           "fin-row-operating-expense",
                           "fin-row-operating-income",
                           "fin-row-total-expenses",
                           "fin-row-net-income",
                           "fin-row-diluted-eps")
    ]
    assert positions == sorted(positions)


def test_financials_card_ships_hidden(client):
    html = _stock_html(client)
    assert re.search(
        r'<div class="card financials-card" id="financials-card" hidden>',
        html,
    )


def test_financials_head_ships_empty(client):
    html = _stock_html(client)
    assert re.search(
        r'<tr id="fin-head-row"><th scope="col"></th></tr>', html,
    )


def test_financials_chart_canvas_ships_bare(client):
    # The canvas carries no static content: stock.js builds the whole
    # chart from JSON, so any baked-in child would masquerade as data.
    html = _stock_html(client)
    assert re.search(r'<canvas id="fin-chart"></canvas>', html)
