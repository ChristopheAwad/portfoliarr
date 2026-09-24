"""Check the fee form's request and display wiring without a browser runner."""

from pathlib import Path


def test_fee_field_connects_to_form_and_native_display(client):
    html = client.get("/ledger").get_data(as_text=True)
    js = Path("static/js/ledger.js").read_text()
    css = Path("static/style.css").read_text()
    assert 'name="fee"' in html
    assert 'data-col="fee"' in html
    assert 'step="any" min="0"' in html
    assert 'fee: fields.fee === "" ? null : Number(fields.fee)' in js
    assert 'txForm.elements.fee.value = tx.fee ?? ""' in js
    assert 'txForm.elements.fee.value = ""' in js
    assert 'fee: body.fee' in js  # PUT sends the edited fee
    assert '`${formatNumber(tx.fee)} ${tx.currency}`' in js
    assert 'fee: feeCell' in js
    assert 'tr.ledger-group td[data-col="fee"] { display: none; }' in css
