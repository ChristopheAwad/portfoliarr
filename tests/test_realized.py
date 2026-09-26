# tests/test_realized.py
# ======================
# Route tests for GET /api/portfolio/realized — the "Closed sales" table's
# data source. Each SELL transaction becomes one row carrying the realized
# result of that sale in CAD: proceeds vs what those shares actually cost.
#
# THE CONTRACTS UNDER TEST HERE:
#   - AVERAGE-COST REPLAY: the ledger is folded oldest-first (date, then
#     id — same tiebreak db.get_transactions uses, reversed). A BUY grows
#     the position's pool (qty + native cost + CAD cost); a SELL covers
#     min(qty, sold) shares and realizes
#         covered × (sell_price × sell_rate − avg_cad_cost)
#     shrinking the pools by the covered shares' average basis. A partial
#     sell leaves the pool carrying its remaining shares at the SAME
#     average — the next sell continues from there.
#   - RECOMPUTE-ON-READ: the endpoint replays the raw facts on every
#     request. Nothing is stored, so editing an old BUY retroactively
#     rewrites history — the honest consequence of an editable ledger.
#   - ZERO NETWORK: every rate is a stored fact (fx_rate captured at log
#     time; CAD rows store 1.0). No quotes, no live FX calls — a realized
#     gain is history, it cannot go stale, so it never needs refreshing.
#   - SHORTS ARE SYMMETRIC, not special-cased: a SELL bigger than the
#     position realizes on the covered shares and opens a short whose
#     basis is the sell price; a later BUY covering it realizes
#     (short basis − buy price). The fold is one uniform formula.
#   - THE TOTAL vs THE ROWS: rows are sell events only, so a short-cover
#     gain (earned on a BUY) appears in total_realized but in NO row.
#     total_realized is the fold's full sum — never just Σ rows.
#   - DEGRADATION, NEVER FABRICATION: a row's CAD math needs every leg of
#     its position to carry a known rate. One NULL-fx (or unsupported-
#     currency) leg in the pool → that pool's sells show realized/pct
#     null + a reason; facts (qty, native prices) still show. The flag
#     follows the POSITION LIFECYCLE: it clears when the pool returns to
#     flat, so a fresh position after a degraded one computes normally.
#     One degraded row poisons total_realized to null — a partial sum
#     that looks complete is a lie.
#   - NATIVE FACTS STAY NATIVE: avg_cost and price are the security's own
#     currency (the ledger's price convention); only realized/pct are CAD.

import pytest
from types import SimpleNamespace

import db


# ── Helpers & fixtures ────────────────────────────────────────────────

@pytest.fixture
def fake_names(monkeypatch):
    """Swap get_name AS APP.PY USES IT (patch where it's used — app.py
    did `from market_data import get_name`, so the module-level name is
    what the route looks up). An absent key raises KeyError, which the
    route's try/except translates to name: null — the deterministic
    stand-in for "Yahoo has no name for this ticker".

    NOTE: no quote/FX patching is needed anywhere in this file — that's
    the point. If the realized route ever grows a get_quote or get_fx_
    rate call, these tests MUST start failing (they'd hit the network).
    """
    names = {}
    import app as app_module
    monkeypatch.setattr(app_module, "get_name",
                        lambda symbol: names[symbol])
    return SimpleNamespace(names=names)


def seed(ticker="AAPL", date="2026-08-01", price=100.0, qty=10,
         tx_type="BUY", currency="CAD", fx_rate=1.0):
    """Insert a ledger row through the db layer (never raw SQL). fx_rate
    is the stored currency fact: 1.0 for CAD rows, the USDCAD close on
    `date` for USD rows, None for "pre-feature row, rate unknown"."""
    return db.add_transaction(ticker, date, price, qty, currency,
                              tx_type, fx_rate, portfolio_id=1)


def get_payload(client):
    """GET the realized endpoint and return the parsed JSON body."""
    res = client.get("/api/portfolio/realized")
    assert res.status_code == 200
    return res.get_json()


def sell_rows(payload):
    """The endpoint's rows, newest-first as shipped."""
    return payload["rows"]


# ── The core math ─────────────────────────────────────────────────────

def test_single_buy_sell_twenty_percent(client, fake_names):
    """The scenario that motivated the feature, hand-computed: buy 10
    shares at $100, sell all 10 at $120 → +$200, +20%. Avg cost is the
    buy price; avg_cost_fx is 1.0 because CAD rows store that fact."""
    seed(price=100.0, qty=10, tx_type="BUY")             # id 1
    sell_id = seed(date="2026-08-05", price=120.0, qty=10,
                   tx_type="SELL")                       # id 2

    payload = get_payload(client)
    assert payload["currency"] == "CAD"
    rows = sell_rows(payload)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == sell_id
    assert row["ticker"] == "AAPL"
    assert row["transaction_date"] == "2026-08-05"
    assert row["qty"] == 10
    assert row["price"] == 120.0
    assert row["avg_cost"] == 100.0
    assert row["avg_cost_fx"] == pytest.approx(1.0)
    assert row["realized"] == pytest.approx(200.0)
    assert row["realized_pct"] == pytest.approx(20.0)
    assert row["degraded"] is None
    assert payload["total_realized"] == pytest.approx(200.0)


def test_two_buys_weighted_average_partial_sell(client, fake_names):
    """Two buys at different prices AND different fx rates, then a
    partial sell. The covered shares' basis is the fx-weighted average:
        native pool  10×100 + 10×140      = 2400  → avg 120/share
        CAD pool     10×100×1.35 + 10×140×1.30 = 3170 → avg 158.5/share
        sell 15 @160 USD, stored rate 1.40:
        proceeds  15×160×1.40 = 3360
        basis     15×158.5    = 2377.5
        realized  982.5  (41.329…%)
    The surviving pool must keep the SAME average (5 shares, 600 native,
    792.5 CAD) — a partial sell never reprices what it leaves behind."""
    seed(date="2026-08-01", price=100.0, qty=10, tx_type="BUY",
         currency="USD", fx_rate=1.35)
    seed(date="2026-08-05", price=140.0, qty=10, tx_type="BUY",
         currency="USD", fx_rate=1.30)
    seed(date="2026-08-10", price=160.0, qty=15, tx_type="SELL",
         currency="USD", fx_rate=1.40)

    payload = get_payload(client)
    row = sell_rows(payload)[0]
    assert row["qty"] == 15
    assert row["price"] == 160.0
    assert row["avg_cost"] == pytest.approx(120.0)
    assert row["avg_cost_fx"] == pytest.approx(3170.0 / 2400.0)
    assert row["realized"] == pytest.approx(982.5)
    assert row["realized_pct"] == pytest.approx(982.5 / 2377.5 * 100)
    assert row["degraded"] is None
    assert payload["total_realized"] == pytest.approx(982.5)


def test_sell_then_rebuy_fresh_basis_and_a_loss_row(client, fake_names):
    """Selling flat and re-entering starts a NEW pool — the old basis
    must never bleed into the new position. The second round-trip is a
    LOSS: 10 bought @120 (fx 1.35), sold @115 (fx 1.32):
        proceeds 10×115×1.32 = 1518   basis 10×120×1.35 = 1620
        realized −102 (−6.296…%)
    Both rows carry real numbers; the total nets them (+138)."""
    seed(date="2026-08-01", price=100.0, qty=10, tx_type="BUY",
         currency="USD", fx_rate=1.30)
    seed(date="2026-08-05", price=110.0, qty=10, tx_type="SELL",
         currency="USD", fx_rate=1.40)
    seed(date="2026-08-10", price=120.0, qty=10, tx_type="BUY",
         currency="USD", fx_rate=1.35)
    seed(date="2026-08-15", price=115.0, qty=10, tx_type="SELL",
         currency="USD", fx_rate=1.32)

    payload = get_payload(client)
    rows = sell_rows(payload)
    assert len(rows) == 2
    # Newest first: the August 15 sell leads.
    assert rows[0]["transaction_date"] == "2026-08-15"
    assert rows[0]["realized"] == pytest.approx(-102.0)
    assert rows[0]["realized_pct"] == pytest.approx(-102.0 / 1620.0 * 100)
    assert rows[1]["transaction_date"] == "2026-08-05"
    assert rows[1]["realized"] == pytest.approx(240.0)
    assert rows[1]["realized_pct"] == pytest.approx(240.0 / 1300.0 * 100)
    assert payload["total_realized"] == pytest.approx(138.0)


def test_oversell_opens_short_cover_gain_in_total_only(client, fake_names):
    """SELL 8 with only 5 held: 5 covered shares realize
    5×110 − 5×100 = +50; the 3-share excess opens a short at 110.
    A later BUY 3 @90 covers it: (110 − 90) × 3 = +60 — earned on a BUY
    event, so NO row carries it, but total_realized (the fold's sum)
    must. Rows ⊂ total is the documented divergence."""
    seed(price=100.0, qty=5, tx_type="BUY")
    seed(date="2026-08-05", price=110.0, qty=8, tx_type="SELL")
    seed(date="2026-08-10", price=90.0, qty=3, tx_type="BUY")

    payload = get_payload(client)
    rows = sell_rows(payload)
    assert len(rows) == 1
    assert rows[0]["qty"] == 8            # the row IS the sell event
    assert rows[0]["avg_cost"] == pytest.approx(100.0)  # covered basis
    assert rows[0]["realized"] == pytest.approx(50.0)
    assert rows[0]["realized_pct"] == pytest.approx(10.0)
    assert payload["total_realized"] == pytest.approx(110.0)


def test_short_opening_sell_realizes_zero(client, fake_names):
    """A SELL with nothing held (SELL-only ticker) opens a short — it
    realizes NOTHING at that moment (basis = its own price). A covering
    BUY later books the gain into the total, still with one row."""
    seed(price=100.0, qty=10, tx_type="SELL")
    seed(date="2026-08-05", price=80.0, qty=10, tx_type="BUY")

    payload = get_payload(client)
    rows = sell_rows(payload)
    assert len(rows) == 1
    assert rows[0]["avg_cost"] == pytest.approx(100.0)
    assert rows[0]["realized"] == pytest.approx(0.0)
    assert rows[0]["realized_pct"] is None   # zero basis → no meaningful %
    assert payload["total_realized"] == pytest.approx(200.0)


# ── Degradation: never fabricate ──────────────────────────────────────

def test_missing_fx_degrades_row_and_total(client, fake_names):
    """A NULL-fx BUY (pre-feature row, or Yahoo couldn't answer at log
    time) makes the pool's CAD cost unknowable. The sell's row keeps its
    FACTS (native prices, qty, dates) but realized/pct go null with a
    reason — and one degraded row poisons the total to null."""
    seed(price=100.0, qty=10, tx_type="BUY", currency="USD", fx_rate=None)
    seed(date="2026-08-05", price=120.0, qty=10, tx_type="SELL",
         currency="USD", fx_rate=1.40)

    payload = get_payload(client)
    row = sell_rows(payload)[0]
    assert row["qty"] == 10
    assert row["price"] == pytest.approx(120.0)
    assert row["avg_cost"] == pytest.approx(100.0)  # native math survives
    assert row["avg_cost_fx"] is None
    assert row["realized"] is None
    assert row["realized_pct"] is None
    assert row["degraded"] is not None
    assert "fx" in row["degraded"].lower()
    assert payload["total_realized"] is None


def test_degradation_follows_position_lifecycle(client, fake_names):
    """The unrated-leg flag belongs to the POOL, not the ticker forever:
        round 1 (rated buys)  → row computes
        round 2 (NULL-fx buy) → row degrades
        round 3 (fresh pool after going flat, rated again) → row computes
    Going flat wipes the ancestry; a fresh position is judged fresh."""
    seed(date="2026-08-01", price=100.0, qty=10, tx_type="BUY",
         currency="USD", fx_rate=1.30)
    seed(date="2026-08-02", price=110.0, qty=10, tx_type="SELL",
         currency="USD", fx_rate=1.40)
    seed(date="2026-08-03", price=100.0, qty=10, tx_type="BUY",
         currency="USD", fx_rate=None)
    seed(date="2026-08-04", price=110.0, qty=10, tx_type="SELL",
         currency="USD", fx_rate=1.40)
    seed(date="2026-08-05", price=100.0, qty=10, tx_type="BUY",
         currency="USD", fx_rate=1.30)
    seed(date="2026-08-06", price=110.0, qty=10, tx_type="SELL",
         currency="USD", fx_rate=1.40)

    payload = get_payload(client)
    rows = sell_rows(payload)          # newest first: 08-06, 08-04, 08-02
    assert len(rows) == 3
    assert rows[0]["degraded"] is None
    assert rows[0]["realized"] == pytest.approx(240.0)
    assert rows[1]["degraded"] is not None
    assert rows[1]["realized"] is None
    assert rows[2]["degraded"] is None
    assert rows[2]["realized"] == pytest.approx(240.0)
    assert payload["total_realized"] is None


def test_unsupported_currency_degrades(client, fake_names):
    """USD↔CAD is the only supported conversion (permanent rule). A
    ticker in any other currency keeps its facts but its CAD fields
    degrade, with the offending currency named in the reason."""
    seed(ticker="SAP.DE", price=100.0, qty=10, tx_type="BUY",
         currency="EUR", fx_rate=1.0)
    seed(ticker="SAP.DE", date="2026-08-05", price=120.0, qty=10,
         tx_type="SELL", currency="EUR", fx_rate=1.0)

    payload = get_payload(client)
    row = sell_rows(payload)[0]
    assert row["avg_cost"] == pytest.approx(100.0)   # native facts stand
    assert row["realized"] is None
    assert "EUR" in row["degraded"]
    assert payload["total_realized"] is None


def test_covering_buy_shrinks_unrated_short_native_pool(client, fake_names):
    """REGRESSION (review blocking #1): the BUY-covers-short branch used
    to gate BOTH pool adjustments on pos["rated"] — but the native pool
    is always exact (currency purity), unlike the CAD pool. Trace: SELL
    10 @100 fx=NULL opens an unrated short; BUY 14 @90 fx=1.35 covers it
    and opens a 4-share long; the next SELL must show avg_cost 90.0 —
    the old code left the native pool unshrunk and displayed -160.0, a
    corrupted "fact" in exactly the legacy-NULL-fx scenario degradation
    exists for. The rows still DEGRADE (the pool's CAD ancestry is
    unknowable) and the total stays null — withholding, never
    fabricating."""
    seed(date="2026-08-01", price=100.0, qty=10, tx_type="SELL",
         currency="USD", fx_rate=None)                   # opens the short
    seed(date="2026-08-02", price=90.0, qty=14, tx_type="BUY",
         currency="USD", fx_rate=1.35)                   # cover + long
    seed(date="2026-08-03", price=120.0, qty=4, tx_type="SELL",
         currency="USD", fx_rate=1.40)                   # sells the long

    payload = get_payload(client)
    rows = sell_rows(payload)          # newest first: 08-03, 08-01
    assert len(rows) == 2
    # THE REGRESSION: the surviving long's native basis must be exact.
    assert rows[0]["avg_cost"] == pytest.approx(90.0)
    # The ancestry is still unrated: degraded rows, null total.
    assert rows[0]["degraded"] is not None
    assert rows[0]["realized"] is None
    assert rows[1]["degraded"] is not None
    assert payload["total_realized"] is None


def test_fractional_positions_still_go_flat(client, fake_names):
    """REGRESSION (review blocking #2): binary float residue — buy 0.1 +
    0.2, sell 0.3 → net 5.55e-17, not 0 — used to defeat the exact-zero
    flat-wipe, so an unrated ancestry stuck to the ticker FOREVER (round
    3 degraded, total poisoned for life). The wipe now uses a 1e-9
    tolerance, so a fractional position that sold out counts as flat and
    the NEXT position is judged fresh — the integer lifecycle contract,
    extended to the importer's 6-decimal flagship input."""
    # Round 1 — rated, computes (0.3 × (110×1.4 − 100×1.3) = 7.2)
    seed(date="2026-08-01", price=100.0, qty=0.1, currency="USD",
         fx_rate=1.3)
    seed(date="2026-08-02", price=100.0, qty=0.2, currency="USD",
         fx_rate=1.3)
    seed(date="2026-08-03", price=110.0, qty=0.3, tx_type="SELL",
         currency="USD", fx_rate=1.4)
    # Round 2 — one NULL-fx leg poisons the pool; its sell degrades
    seed(date="2026-08-04", price=100.0, qty=0.1, currency="USD",
         fx_rate=None)
    seed(date="2026-08-05", price=100.0, qty=0.2, currency="USD",
         fx_rate=1.3)
    seed(date="2026-08-06", price=110.0, qty=0.3, tx_type="SELL",
         currency="USD", fx_rate=1.4)
    # Round 3 — fresh pool after going flat: must compute again
    seed(date="2026-08-07", price=100.0, qty=0.1, currency="USD",
         fx_rate=1.3)
    seed(date="2026-08-08", price=100.0, qty=0.2, currency="USD",
         fx_rate=1.3)
    seed(date="2026-08-09", price=110.0, qty=0.3, tx_type="SELL",
         currency="USD", fx_rate=1.4)

    payload = get_payload(client)
    rows = sell_rows(payload)          # newest first: 08-09, 08-06, 08-03
    assert len(rows) == 3
    assert rows[0]["degraded"] is None, \
        "round 3 must be judged fresh — float residue must not glue the " \
        "unrated ancestry to the ticker forever"
    assert rows[0]["realized"] == pytest.approx(7.2)
    assert rows[0]["avg_cost"] == pytest.approx(100.0)
    assert rows[1]["degraded"] is not None
    assert rows[2]["degraded"] is None
    assert payload["total_realized"] is None   # round 2 poisons the total


# ── Shape, ordering, names, recompute-on-read ─────────────────────────

def test_empty_ledger_returns_zero_total_and_no_rows(client, fake_names):
    """No transactions → no closed sales, total 0.0 (an empty sum). A
    normal state, not an error — the frontend shows its empty-state row."""
    payload = get_payload(client)
    assert payload["rows"] == []
    assert payload["total_realized"] == pytest.approx(0.0)
    assert payload["currency"] == "CAD"


def test_same_day_transactions_replay_in_insertion_order(client, fake_names):
    """db.get_transactions is newest-first; the replay must reverse it.
    Same-date rows tiebreak by id: BUY(id 1) → SELL(id 2) → BUY(id 3),
    all on 2026-08-01. Replay in insertion order: the sell covers the
    first buy → 5×150 − 5×100 = +250. Reversed, the sell would hit an
    empty pool (short opening, realized 0) — the assertion pins order."""
    seed(date="2026-08-01", price=100.0, qty=5, tx_type="BUY")    # id 1
    seed(date="2026-08-01", price=150.0, qty=5, tx_type="SELL")   # id 2
    seed(date="2026-08-01", price=100.0, qty=5, tx_type="BUY")    # id 3

    payload = get_payload(client)
    rows = sell_rows(payload)
    assert len(rows) == 1
    assert rows[0]["realized"] == pytest.approx(250.0)
    assert rows[0]["realized_pct"] == pytest.approx(50.0)
    assert payload["total_realized"] == pytest.approx(250.0)


def test_editing_a_buy_retroactively_changes_history(client, fake_names):
    """RECOMPUTE-ON-READ, proven end to end: correct an old BUY's price
    through the PUT route and the realized gain changes — because the
    endpoint replays the ledger fresh on every request. Nothing stored,
    nothing stale. (PUT takes {date, price, qty, type} only.)"""
    buy_id = seed(price=100.0, qty=10, tx_type="BUY")
    seed(date="2026-08-05", price=120.0, qty=10, tx_type="SELL")

    assert get_payload(client)["total_realized"] == pytest.approx(200.0)

    res = client.put(f"/api/transactions/{buy_id}",
                     json={"date": "2026-08-01", "price": 110.0,
                           "qty": 10, "type": "BUY"})
    assert res.status_code == 200

    payload = get_payload(client)
    assert payload["total_realized"] == pytest.approx(100.0)
    assert payload["rows"][0]["avg_cost"] == pytest.approx(110.0)


def test_row_json_contract_keys(client, fake_names):
    """Lock the exact key set: the frontend renders from this shape, and
    an accidental key add/rename would silently break the table."""
    seed(price=100.0, qty=10, tx_type="BUY")
    seed(date="2026-08-05", price=120.0, qty=10, tx_type="SELL")

    payload = get_payload(client)
    assert set(payload.keys()) == {"currency", "total_realized", "rows"}
    assert set(payload["rows"][0].keys()) == {
        "id", "ticker", "name", "transaction_date", "qty", "currency",
        "price", "avg_cost", "avg_cost_fx", "realized", "realized_pct",
        "degraded",
    }


def test_names_attach_when_known_degrade_when_not(client, fake_names):
    """Name comes from the same cache the ledger uses. A ticker Yahoo
    can't name still gets its full row — name null is a cosmetic gap,
    never a reason to drop realized history."""
    seed(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed(ticker="AAPL", date="2026-08-05", price=120.0, qty=10,
         tx_type="SELL")
    seed(ticker="ZZZ", date="2026-08-06", price=10.0, qty=5,
         tx_type="BUY", currency="USD", fx_rate=1.35)
    seed(ticker="ZZZ", date="2026-08-07", price=12.0, qty=5,
         tx_type="SELL", currency="USD", fx_rate=1.40)
    fake_names.names["AAPL"] = "Apple Inc."

    payload = get_payload(client)
    by_ticker = {row["ticker"]: row for row in payload["rows"]}
    assert by_ticker["AAPL"]["name"] == "Apple Inc."
    assert by_ticker["ZZZ"]["name"] is None
    assert by_ticker["ZZZ"]["realized"] == pytest.approx(
        5 * 12.0 * 1.40 - 5 * 10.0 * 1.35)
    assert payload["total_realized"] == pytest.approx(
        (10 * 120.0 - 10 * 100.0)
        + (5 * 12.0 * 1.40 - 5 * 10.0 * 1.35))
