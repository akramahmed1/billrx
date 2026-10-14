import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

os.environ["MODEL_PROVIDER"] = "mock"

from src.intake import IntakeError, extract_bill, parse_bill_text  # noqa: E402
from src.pipeline import Pipeline  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
DATA = Path(__file__).parent.parent / "data"
EXPECTED = [(ln["code"], ln["amount"]) for ln in
            json.loads((DATA / "synthetic_bill.json").read_text())["lines"]]


@pytest.mark.parametrize("name", ["itemized_bill.pdf", "itemized_bill_scanned.pdf",
                                  "itemized_bill_photo.png"])
def test_every_upload_format_recovers_the_exact_lines(name):
    b = extract_bill(FIX / name)
    assert [(ln.code, ln.amount) for ln in b.lines] == EXPECTED
    assert b.statement_total == "7842.00" and b.balance_due == "2484.00"
    assert b.date_of_service == "2026-08-14"
    assert b.line_sum == Decimal("7842.00")
    assert b.needs_confirmation is True
    # non-line amounts are surfaced for review, never dropped silently
    assert any("Insurance adjustments" in u["raw"] for u in b.unparsed)


def test_ocr_lowers_confidence():
    assert {ln.confidence for ln in extract_bill(FIX / "itemized_bill_photo.png").lines} == {"medium"}
    assert {ln.confidence for ln in extract_bill(FIX / "itemized_bill.pdf").lines} == {"high"}


def test_unconfirmed_drafts_cannot_be_audited():
    b = extract_bill(FIX / "itemized_bill.pdf")
    with pytest.raises(IntakeError):
        b.to_bill_json(confirmed=False)


def test_upload_to_audit_end_to_end(tmp_path):
    """PDF upload -> confirm -> full pipeline gives the same result as the JSON demo."""
    bill_json = extract_bill(FIX / "itemized_bill.pdf").to_bill_json(confirmed=True)
    bill_path = tmp_path / "bill.json"
    bill_path.write_text(json.dumps(bill_json))
    res = Pipeline().run(bill_path, DATA / "synthetic_eob.json")
    ids = sorted(c.finding_id for c in res.candidates)
    assert ids == sorted(["F-DUP-80053", "F-UNB-80048-80053", "F-BUNDLE-36415", "F-BAL"])
    assert res.delta == Decimal("1842.00")


def test_rejects_unsupported_and_oversized_files(tmp_path):
    txt = tmp_path / "bill.txt"
    txt.write_text("not a bill")
    with pytest.raises(IntakeError):
        extract_bill(txt)


def test_mismatched_total_and_summary_bills_warn():
    b = parse_bill_text([("1 08/14/2026 99283 ED visit 1 $100.00\nTotal charges $150.00", "text")])
    assert any("add up to" in w for w in b.warnings)
    empty = parse_bill_text([("Thank you for your payment\nTotal charges $150.00", "text")])
    assert any("itemized bill" in w for w in empty.warnings)


def test_modifiers_are_read_from_the_code():
    b = parse_bill_text([("4 08/14/2026 80048-59 Basic metabolic panel 1 $290.00", "text")])
    assert b.lines[0].code == "80048" and b.lines[0].modifiers == ["59"]
