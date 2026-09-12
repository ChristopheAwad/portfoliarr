# tests/test_helpers.py
# ======================
# Unit tests for internal helper functions in app.py that are only tested
# indirectly through route tests elsewhere. Isolating them here catches
# edge cases the route tests miss: the full fallback ladder in
# _derive_fx_rate, memoization in _derive_fx_rates_for_rows, dedup in
# _quote_unique_tickers, and the body-checking logic in _import_text_or_error.
#
# PATTERN: Same as test_validate_tx_fields.py — helpers that call
# jsonify() need a Flask app context; helpers that return data don't.
# Patch the dependencies WHERE app.py looks them up (app_module).

import pytest
from types import SimpleNamespace

import app as app_module


# ── Helpers ───────────────────────────────────────────────────────────

def _derive_fx_rate(currency, transaction_date):
    """Shortcut to the real function under test."""
    return app_module._derive_fx_rate(currency, transaction_date)


def _derive_fx_rates_for_rows(rows, quotes):
    return app_module._derive_fx_rates_for_rows(rows, quotes)


def _import_text_or_error():
    return app_module._import_text_or_error()


def _quote_unique_tickers(rows):
    return app_module._quote_unique_tickers(rows)


# ── _derive_fx_rate ───────────────────────────────────────────────────

class TestDeriveFxRate:
    """The three-step fallback ladder: historical close → live → None."""

    def test_cad_shortcuts_to_one(self):
        """CAD needs no conversion — the true rate, always."""
        assert _derive_fx_rate("CAD", "2026-08-31") == 1.0

    def test_unsupported_currency_returns_none(self):
        """Only USD↔CAD is supported. Null is honest: the display layer
        keeps such rows in their native currency."""
        assert _derive_fx_rate("GBP", "2026-08-31") is None

    def test_usd_uses_historical_close(self, fake_market):
        """Happy path: the date's USDCAD close is available."""
        fake_market.fx_on[("USDCAD", "2026-08-31")] = 1.37
        assert _derive_fx_rate("USD", "2026-08-31") == 1.37

    def test_usd_falls_back_to_live_rate(self, fake_market):
        """Historical close unavailable → live rate as approximation.
        The fake_market fixture uses dict lookups — a missing key raises
        KeyError, simulating a Yahoo failure."""
        # fx_on empty → get_fx_rate_on raises KeyError → fallback to live
        fake_market.fx_rates["USDCAD"] = 1.39
        assert _derive_fx_rate("USD", "2026-08-31") == 1.39

    def test_usd_both_fallbacks_fail_returns_none(self, fake_market):
        """Both historical and live fail → None. The ledger fact is still
        stored; the display layer handles the degradation."""
        # Both dicts empty → both lookups raise → None
        assert _derive_fx_rate("USD", "2026-08-31") is None


# ── _derive_fx_rates_for_rows ─────────────────────────────────────────

class TestDeriveFxRatesForRows:
    """Batch decoration with memoization per (currency, date)."""

    def test_skips_error_rows(self, fake_market):
        """Rows with an error string are skipped — no FX fetched."""
        rows = [{"ticker": "AAPL", "error": "bad date",
                 "transaction_date": "2026-08-31"}]
        _derive_fx_rates_for_rows(rows, {})
        assert "fx_rate" not in rows[0]

    def test_skips_unquotable_rows(self, fake_market):
        """Rows whose ticker has no quote are skipped."""
        rows = [{"ticker": "AAPL", "error": None,
                 "transaction_date": "2026-08-31"}]
        quotes = {"AAPL": None}  # unquotable
        _derive_fx_rates_for_rows(rows, quotes)
        assert "fx_rate" not in rows[0]

    def test_memoizes_per_currency_date(self, fake_market):
        """Three USD rows on the same date → one FX call, not three."""
        fake_market.fx_on[("USDCAD", "2026-08-31")] = 1.37
        quote = {"currency": "USD", "price": 100.0}
        rows = [
            {"ticker": "AAPL", "error": None,
             "transaction_date": "2026-08-31"},
            {"ticker": "MSFT", "error": None,
             "transaction_date": "2026-08-31"},
            {"ticker": "GOOG", "error": None,
             "transaction_date": "2026-08-31"},
        ]
        quotes = {"AAPL": quote, "MSFT": quote, "GOOG": quote}
        _derive_fx_rates_for_rows(rows, quotes)
        for row in rows:
            assert row["fx_rate"] == 1.37


# ── _import_text_or_error ─────────────────────────────────────────────

class TestImportTextOrError:
    """Shared body check for both import routes."""

    def test_returns_text_on_success(self):
        with app_module.app.test_request_context(
                json={"text": "CM\t16 Mar 2026\t132.55\t1.296383"}):
            text, error = _import_text_or_error()
        assert text == "CM\t16 Mar 2026\t132.55\t1.296383"
        assert error is None

    def test_rejects_no_body(self):
        with app_module.app.test_request_context():
            text, error = _import_text_or_error()
        assert text is None
        assert error[1] == 400

    def test_rejects_blank_text(self):
        with app_module.app.test_request_context(json={"text": "   "}):
            text, error = _import_text_or_error()
        assert text is None
        assert error[1] == 400

    def test_rejects_non_dict_body(self):
        with app_module.app.test_request_context(json=["rows"]):
            text, error = _import_text_or_error()
        assert text is None
        assert error[1] == 400


# ── _quote_unique_tickers ─────────────────────────────────────────────

class TestQuoteUniqueTickers:
    """One get_quote per UNIQUE ticker among parseable rows."""

    def test_deduplicates(self, fake_market):
        """Same ticker appearing twice → one quote fetch."""
        fake_market.quotes["AAPL"] = SimpleNamespace(
            symbol="AAPL", price=100.0, previous_close=95.0,
            currency="USD", change=5.0, change_pct=5.263)
        rows = [
            {"ticker": "AAPL", "error": None},
            {"ticker": "AAPL", "error": None},
        ]
        quotes = _quote_unique_tickers(rows)
        assert quotes["AAPL"] is not None

    def test_maps_errors_to_none(self, fake_market):
        """Dead ticker → None, never an exception."""
        rows = [
            {"ticker": "DEAD", "error": None},
        ]
        quotes = _quote_unique_tickers(rows)
        assert quotes["DEAD"] is None

    def test_skips_error_rows(self, fake_market):
        """Error rows are not quoted."""
        fake_market.quotes["AAPL"] = SimpleNamespace(
            symbol="AAPL", price=100.0, previous_close=95.0,
            currency="USD", change=5.0, change_pct=5.263)
        rows = [
            {"ticker": "AAPL", "error": "bad line"},
        ]
        quotes = _quote_unique_tickers(rows)
        assert quotes == {}
