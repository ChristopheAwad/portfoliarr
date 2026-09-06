"""CSS contract tests for the ledger table.

These are string checks, not layout tests — pytest can't run a browser.
What they lock is the CONTRACT between main.js's stamped cells and
style.css's selectors: every ledger cell is identified by a data-col
attribute (stampCell in main.js), never by a class. A CSS rule that
targets a class like td.date therefore matches NOTHING and dies silently
— that bug shipped once: the ≤600px card layout's td.type/td.ticker/…
selectors were dead, so phones showed stray blank "Type"/"Price" lines
and lost the ticker-as-card-title row. These tests keep both directions
honest:

  1. the wrap-proofing rule names all four short columns by data-col,
  2. the card-mode block keys its cell rules on data-col too,
  3. the [hidden] !important guard survives — it's what makes collapsed
     detail rows actually collapse in card mode, where an author
     `display: block` on tr would otherwise outrank the browser's
     built-in [hidden] rule.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def css() -> str:
    """style.css as one string — same read-the-file pattern as test_docker."""
    return (ROOT / "static" / "style.css").read_text()


def rule_containing(needle: str) -> str:
    """Return the first CSS rule block whose text contains `needle`.

    Crude but honest: find the needle, walk back to the '{' that opens its
    rule, forward to the closing '}'. Selector lists share one body, so a
    needle found in a selector list still lands on the right block.
    """
    text = css()
    i = text.find(needle)
    assert i != -1, f"needle not found in style.css: {needle!r}"
    start = text.rfind("{", 0, i)
    end = text.find("}", i)
    assert start != -1 and end != -1, "malformed rule around needle"
    return text[start : end + 1]


def test_group_row_meta_cells_never_wrap():
    """The date/ticker/type/actions cells are the only wrap-capable cells in
    a group row (.num cells already carry nowrap). Right after a page load —
    all groups collapsed, so the auto-layout table sizes columns from the
    least content it will ever see — those columns can come up too narrow
    and break '▸ 1 txn' onto two lines, growing the row until some later
    rebuild happens to widen the columns again. The nowrap rule makes a
    group row's height deterministic instead of a layout-coin-flip."""
    body = rule_containing('td[data-col="date"]')
    for col in ("date", "ticker", "type", "actions"):
        assert f'td[data-col="{col}"]' in body, f"missing column: {col}"
    assert "white-space" in body and "nowrap" in body


def test_card_mode_cell_rules_key_on_data_col():
    """The ≤600px card layout re-lays out cells BY MEANING — and meaning is
    the data-col attribute, because no cell carries a .date/.ticker/… class.
    Each per-cell rule below must therefore name its column via
    [data-col="…"], or it is a dead rule and phone users get the raw
    unlabeled fallback (blank Type/Price lines, no title row)."""
    text = css()
    for col in ("type", "price", "date", "ticker", "value", "actions"):
        assert f'tr.ledger-group td[data-col="{col}"]' in text, (
            f"card-mode rule for {col} must use data-col"
        )
    # …and the dead class form must never come back.
    dead = re.search(r"\btd\.(type|price|date|ticker|value|actions)\b", text)
    assert dead is None, f"dead class selector in style.css: td.{dead.group(1)}"


def test_hidden_attribute_guard_unchanged():
    """[hidden] { display: none !important } is load-bearing: in card mode an
    author rule sets tr { display: block }, which outranks the browser's
    built-in [hidden] rule and would force every 'collapsed' detail row
    visible. The guard (standard HTML5 Boilerplate fix) restores the
    attribute's authority for every element at once."""
    body = rule_containing("[hidden]")
    assert "display: none" in body
    assert "!important" in body
