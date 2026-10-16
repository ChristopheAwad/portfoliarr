"""Run compare-overlay reconciliation in a small JavaScript engine.

Source-string checks cannot prove the kept/removed/added decision. This
pins the behavior that keeps a failed benchmark refresh from leaving a
removed chip's line on screen, or silently omitting an added one.
"""

import json
from pathlib import Path

import pytest


COMMON = (Path(__file__).resolve().parents[1] / "static/js/common.js")


def _reconcile(reply, picker):
    MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer
    js = MiniRacer()
    src = COMMON.read_text()
    start = src.index("function reconcileOverlays(")
    end = src.index("\n}", start) + 2
    js.eval(src[start:end])
    return json.loads(js.eval(
        "JSON.stringify(reconcileOverlays("
        f"{json.dumps(reply)}, {json.dumps(picker)}))"
    ))


def test_kept_symbol_reuses_painted_data_and_added_symbol_is_unavailable():
    painted = [{"symbol": "SPY", "values": [100.0, 105.0], "error": None}]
    assert _reconcile(painted, ["SPY", "QQQ"]) == [
        {"symbol": "SPY", "values": [100.0, 105.0], "error": None},
        {"symbol": "QQQ", "values": None, "error": "refresh failed"},
    ]


def test_removed_symbol_is_dropped():
    painted = [
        {"symbol": "SPY", "values": [100.0], "error": None},
        {"symbol": "QQQ", "values": [100.0], "error": None},
    ]
    assert _reconcile(painted, ["SPY"]) == [
        {"symbol": "SPY", "values": [100.0], "error": None},
    ]


def test_empty_picker_yields_no_overlays():
    assert _reconcile([{"symbol": "SPY", "values": [1]}], []) == []


def test_failed_visible_refresh_reconciles_overlays():
    """A failed visible refresh must call the reconcile path (so the
    picker and the chart cannot disagree), not just leave the old chart."""
    js = (Path(__file__).resolve().parents[1]
          / "static/js/common.js").read_text()
    catch = js[js.index("chart refresh failed:"):]
    catch = catch[:catch.index("// ── The render half")]
    assert "reconcileOverlaysOnFailure()" in catch
    assert "reconcileOverlays(painted, current)" in js
